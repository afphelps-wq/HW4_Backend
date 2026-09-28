BODY = {"methodology": "Spatial RNA-seq", "organism": "Human", "tissue": "Pancreas",
        "conditions": ["PDAC"], "data_availability": "TLS annotations"}


def test_search_requires_auth(client):
    assert client.post("/search", json=BODY).status_code == 401


def test_search_validation(client, auth_headers):
    h = auth_headers()
    assert client.post("/search", json={**BODY, "tissue": " "}, headers=h).status_code == 422
    assert client.post("/search", json={**BODY, "max_results": 99}, headers=h).status_code == 422
    missing = {k: v for k, v in BODY.items() if k != "organism"}
    assert client.post("/search", json=missing, headers=h).status_code == 422


def test_search_joins_and_drops_bad_ranker_items(client, auth_headers, stub_upstreams):
    r = client.post("/search", json=BODY, headers=auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert data["cached"] is False
    assert [x["accession"] for x in data["results"]] == ["GSE1"]  # hallucinated + bad label dropped
    res = data["results"][0]
    assert res["title"] == "Spatial atlas of PDAC"
    assert res["n_samples"] == 12
    assert res["geo_url"].endswith("acc=GSE1")
    assert res["download_links"][1].endswith("/GSE1/suppl/")


def test_second_identical_search_hits_cache(client, auth_headers, stub_upstreams):
    h = auth_headers()
    client.post("/search", json=BODY, headers=h)
    same_but_reworded = {**BODY, "methodology": "  spatial rna-seq ", "max_results": 5}
    r = client.post("/search", json=same_but_reworded, headers=h)
    assert r.json()["cached"] is True
    assert r.json()["cached_at"] is not None
    assert stub_upstreams["live"] == 1


def test_upstream_failure_is_502(client, auth_headers, monkeypatch):
    import requests

    def boom(user_input):
        raise requests.ConnectionError("ncbi down")

    monkeypatch.setattr("app.services.search.generate_query_variants", boom)
    assert client.post("/search", json=BODY, headers=auth_headers()).status_code == 502


def _rank_returning(items):
    return lambda user_input, candidates: items


def test_confidence_casing_is_normalized_not_dropped(client, auth_headers, stub_upstreams, monkeypatch):
    item = {"accession": "GSE1", "match_summary": "m", "matched_conditions": [],
            "meets_data_availability": True, "confidence": " High "}
    monkeypatch.setattr("app.services.search.rank_with_ai", _rank_returning([item]))
    r = client.post("/search", json=BODY, headers=auth_headers())
    assert [x["confidence"] for x in r.json()["results"]] == ["high"]


def test_empty_results_are_not_cached(client, auth_headers, stub_upstreams, monkeypatch):
    h = auth_headers()
    monkeypatch.setattr("app.services.search.rank_with_ai", _rank_returning([]))
    first = client.post("/search", json=BODY, headers=h)
    assert first.json() == {"cached": False, "cached_at": None, "results": []}

    monkeypatch.setattr("app.services.search.rank_with_ai", _rank_returning([
        {"accession": "GSE1", "match_summary": "m", "matched_conditions": [],
         "meets_data_availability": True, "confidence": "high"}]))
    second = client.post("/search", json=BODY, headers=h)
    assert second.json()["cached"] is False  # went live again instead of serving []
    assert len(second.json()["results"]) == 1
    assert stub_upstreams["live"] == 2


def test_dropped_ranker_items_and_pipeline_are_logged(client, auth_headers, stub_upstreams, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="app.services.search"):
        client.post("/search", json=BODY, headers=auth_headers())
    text = caplog.text
    assert "Query variants: ['q1', 'q2']" in text
    assert "Merged 1 unique candidates" in text and "GSE1" in text
    assert "Dropped ranker item 'GSE_HALLUCINATED': accession not in fetched candidates" in text
    assert "Dropped ranker item GSE1: malformed" in text  # the "very-high" label


def test_refresh_is_admin_only(client, auth_headers, stub_upstreams):
    h = auth_headers()  # not an admin
    assert client.post("/search?refresh=true", json=BODY, headers=h).status_code == 403
    assert stub_upstreams["live"] == 0  # rejected before any upstream work


def test_admin_refresh_bypasses_and_overwrites_cache(client, auth_headers, stub_upstreams):
    h = auth_headers(is_admin=True)
    client.post("/search", json=BODY, headers=h)
    assert client.post("/search", json=BODY, headers=h).json()["cached"] is True

    refreshed = client.post("/search?refresh=true", json=BODY, headers=h)
    assert refreshed.status_code == 200
    assert refreshed.json()["cached"] is False
    assert stub_upstreams["live"] == 2
    # the refreshed entry is what later requests see
    assert client.post("/search", json=BODY, headers=h).json()["cached"] is True


def test_empty_refresh_keeps_existing_cache_entry(client, auth_headers, stub_upstreams, monkeypatch):
    h = auth_headers(is_admin=True)
    client.post("/search", json=BODY, headers=h)  # populates the cache
    monkeypatch.setattr("app.services.search.rank_with_ai", _rank_returning([]))
    assert client.post("/search?refresh=true", json=BODY, headers=h).json()["results"] == []
    kept = client.post("/search", json=BODY, headers=h).json()
    assert kept["cached"] is True and len(kept["results"]) == 1
