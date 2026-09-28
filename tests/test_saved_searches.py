from tests.test_search import BODY

RESULT = {"accession": "GSE1", "title": "t", "organism": "Homo sapiens", "n_samples": 3,
          "confidence": "high", "match_summary": "s", "matched_conditions": [],
          "meets_data_availability": True, "geo_url": "https://x", "download_links": []}


def test_saved_search_crud(client, auth_headers):
    h = auth_headers()
    created = client.post("/saved-searches", headers=h,
                          json={"name": "PDAC", "query": BODY, "results": [RESULT]})
    assert created.status_code == 201
    sid = created.json()["id"]
    assert client.get("/saved-searches", headers=h).json()[0]["id"] == sid
    assert client.get(f"/saved-searches/{sid}", headers=h).json()["results"][0]["accession"] == "GSE1"
    assert client.delete(f"/saved-searches/{sid}", headers=h).status_code == 204
    assert client.get(f"/saved-searches/{sid}", headers=h).status_code == 404


def test_saved_searches_are_private_per_user(client, auth_headers):
    alice = auth_headers("alice@lab.org")
    bob = auth_headers("bob@lab.org")
    sid = client.post("/saved-searches", headers=alice,
                      json={"name": "mine", "query": BODY, "results": [RESULT]}).json()["id"]
    assert client.get("/saved-searches", headers=bob).json() == []
    assert client.get(f"/saved-searches/{sid}", headers=bob).status_code == 404
    assert client.delete(f"/saved-searches/{sid}", headers=bob).status_code == 404
    assert client.get(f"/saved-searches/{sid}", headers=alice).status_code == 200


def test_saved_searches_require_auth(client):
    assert client.get("/saved-searches").status_code == 401
