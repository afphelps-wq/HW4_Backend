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
