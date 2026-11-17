"""B-03: profile language, consent give / withdraw, and shop creation refused (403) without a consent record."""
from tests.conftest import SHOP, login


def test_language_update_and_validation(client, auth_headers):
    assert client.get("/api/me", headers=auth_headers).json()["language"] == "hi"
    r = client.put("/api/me", headers=auth_headers, json={"language": "en"})
    assert r.status_code == 200 and r.json()["language"] == "en"
    assert client.get("/api/me", headers=auth_headers).json()["language"] == "en"
    assert client.put("/api/me", headers=auth_headers, json={"language": "xx"}).status_code == 422
    assert client.put("/api/me", json={"language": "en"}).status_code == 401


def test_shop_creation_refused_403_without_consent(client, auth_headers):
    r = client.post("/api/shops", headers=auth_headers, json=SHOP)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "consent_required" and r.json()["error"]["details"] == {"purpose": "shop_data"}
    assert client.get("/api/shops", headers=auth_headers).json() == []          # nothing was stored


def test_optional_consent_alone_is_not_enough(client, auth_headers):
    assert client.post("/api/consents", headers=auth_headers, json={"purpose": "benchmarking"}).status_code == 201
    assert client.post("/api/shops", headers=auth_headers, json=SHOP).status_code == 403


def test_give_consent_then_shop_creation_works(client, auth_headers):
    r = client.post("/api/consents", headers=auth_headers, json={"purpose": "shop_data"})
    assert r.status_code == 201 and r.json()["active"] is True and r.json()["required"] is True
    again = client.post("/api/consents", headers=auth_headers, json={"purpose": "shop_data"})
    assert again.status_code == 200 and again.json()["given_at"] == r.json()["given_at"]       # no duplicate record
    assert client.post("/api/shops", headers=auth_headers, json=SHOP).status_code == 201


def test_list_shows_every_purpose(client, auth_headers):
    client.post("/api/consents", headers=auth_headers, json={"purpose": "shop_data"})
    got = {c["purpose"]: c for c in client.get("/api/consents", headers=auth_headers).json()}
    assert set(got) == {"shop_data", "benchmarking", "hosted_llm"}                # hosted_llm: DEC-95
    assert got["shop_data"]["active"] is True and got["benchmarking"]["active"] is False
    assert got["benchmarking"]["required"] is False and got["hosted_llm"]["required"] is False
    assert got["hosted_llm"]["active"] is False                                    # never on by default


def test_withdraw_blocks_new_writes_keeps_data_and_history(client, auth_headers):
    client.post("/api/consents", headers=auth_headers, json={"purpose": "shop_data"})
    shop_id = client.post("/api/shops", headers=auth_headers, json=SHOP).json()["id"]
    r = client.delete("/api/consents", headers=auth_headers, params={"purpose": "shop_data"})
    assert r.status_code == 200 and r.json()["active"] is False
    assert client.post("/api/shops", headers=auth_headers, json=SHOP).status_code == 403
    assert client.get(f"/api/shops/{shop_id}", headers=auth_headers).status_code == 200      # data stays until delete-my-data
    client.post("/api/consents", headers=auth_headers, json={"purpose": "shop_data"})
    hist = client.get("/api/consents/history", headers=auth_headers).json()
    assert len(hist) == 2 and hist[0]["withdrawn_at"] is not None and hist[1]["withdrawn_at"] is None
    assert client.post("/api/shops", headers=auth_headers, json=SHOP).status_code == 201


def test_consent_is_per_user_and_unknown_purpose_rejected(client, auth_headers):
    client.post("/api/consents", headers=auth_headers, json={"purpose": "shop_data"})
    other = login(client, "+919800000002")
    assert client.post("/api/shops", headers=other, json=SHOP).status_code == 403
    assert client.post("/api/consents", headers=auth_headers, json={"purpose": "marketing"}).status_code == 422
    assert client.post("/api/consents", json={"purpose": "shop_data"}).status_code == 401
