"""Q-05 / audit: access rules checked on EVERY documented operation, read from the OpenAPI schema, so a new route
cannot slip in without login, ownership or consent checks.

Rules (ARCHITECTURE section 11, AGENTS rule 5, DEC-84, DEC-91):
- Every operation needs a login except the public ones below; without a token it answers 401.
- An operation on a shop (`{shop_id}` in the path, or `shop_id` in the query or body) answers 404 `shop_not_found`
  for another owner's shop: the same answer as for a missing shop, so ids cannot be probed.
- With consent withdrawn, every operation that stores or computes on shop data answers 403 `consent_required`.
  Reading what is already stored stays allowed until delete-my-data (DEC-84).
"""
import pytest

from app.main import app
from tests.conftest import SHOP, login

PUBLIC = {("GET", "/api/health"), ("GET", "/api/ready"), ("GET", "/api/about"),
          ("POST", "/api/auth/otp/request"), ("POST", "/api/auth/otp/verify")}
# Shop operations that work without consent, each with the reason. Everything else on a shop must refuse.
NO_CONSENT_NEEDED = {
    ("GET", "/api/shops/{shop_id}"): "read stored data",
    ("GET", "/api/shops/{shop_id}/logs"): "read stored data",
    ("GET", "/api/shops/{shop_id}/stock"): "read stored data",
    ("GET", "/api/shops/{shop_id}/assets"): "read stored data",
    ("GET", "/api/shops/{shop_id}/loans"): "read stored data",
    ("GET", "/api/shops/{shop_id}/reviews/latest"): "read stored data",
    ("GET", "/api/shops/{shop_id}/reviews"): "read stored data",
    ("GET", "/api/shops/{shop_id}/alerts"): "read stored data",
    ("POST", "/api/shops/{shop_id}/alerts/{alert_id}/resolve"):
        "flags an existing alert as resolved or muted; stores no new shop data",
}
# Operations that take the shop id in the query or the body instead of the path.
SHOP_IN_QUERY = {("GET", "/api/schemes/match")}
SHOP_IN_BODY = {("POST", "/api/chat"), ("POST", "/api/sos")}


def operations() -> list[tuple[str, str, dict]]:
    ops = []
    for path, methods in app.openapi()["paths"].items():
        for method, op in methods.items():
            if not path.startswith("/api/dev"):          # dev routes: 404 with DEV_MODE off (test_hardening)
                ops.append((method.upper(), path, op))
    return ops


OPS = operations()
SHOP_OPS = [(m, p) for m, p, _ in OPS if "{shop_id}" in p]


def url(path: str, shop_id: int) -> str:
    return path.replace("{shop_id}", str(shop_id)).replace("{alert_id}", "1").replace("{notification_id}", "1")


def call(client, method: str, path: str, shop_id: int, headers: dict | None):
    key = (method, path)
    params = {"shop_id": shop_id, "state": "Delhi"} if key in SHOP_IN_QUERY else None
    body = {"shop_id": shop_id, "message": "namaste", "text": "help"} if key in SHOP_IN_BODY else {}
    kw = {"headers": headers or {}, "params": params}
    if method in ("POST", "PUT", "PATCH"):
        kw["json"] = body
    return client.request(method, url(path, shop_id), **kw)


@pytest.fixture
def two_owners(client):
    """Owner A with a shop, owner B with a shop; both consented."""
    a, b = login(client, "+919800000101"), login(client, "+919800000102")
    for h in (a, b):
        assert client.post("/api/consents", headers=h, json={"purpose": "shop_data"}).status_code == 201
    shop_a = client.post("/api/shops", headers=a, json=SHOP).json()["id"]
    client.post("/api/shops", headers=b, json=SHOP)
    return a, b, shop_a


def test_the_schema_lists_the_operations_this_test_relies_on():
    keys = {(m, p) for m, p, _ in OPS}
    assert PUBLIC <= keys and set(NO_CONSENT_NEEDED) <= keys and (SHOP_IN_QUERY | SHOP_IN_BODY) <= keys
    assert len(SHOP_OPS) >= 20                               # the sweep below is not silently empty (23 today)


@pytest.mark.parametrize(("method", "path"), [(m, p) for m, p, _ in OPS if (m, p) not in PUBLIC])
def test_every_non_public_operation_needs_a_login(client, method, path):
    r = call(client, method, path, 1, None)
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] in ("not_logged_in", "invalid_token")


@pytest.mark.parametrize(("method", "path"), SHOP_OPS + sorted(SHOP_IN_QUERY | SHOP_IN_BODY))
def test_another_owners_shop_looks_missing(client, two_owners, method, path):
    _, b, shop_a = two_owners
    r = call(client, method, path, shop_a, b)
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "shop_not_found"
    missing = call(client, method, path, 999_999, b)
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "shop_not_found")


@pytest.mark.parametrize(("method", "path"),
                         [k for k in SHOP_OPS + sorted(SHOP_IN_QUERY | SHOP_IN_BODY) if k not in NO_CONSENT_NEEDED])
def test_without_consent_nothing_is_stored_or_computed(client, two_owners, method, path):
    a, _, shop_a = two_owners
    assert client.delete("/api/consents", headers=a, params={"purpose": "shop_data"}).status_code == 200
    r = call(client, method, path, shop_a, a)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "consent_required"


def test_creating_a_shop_needs_consent(client):
    h = login(client, "+919800000103")
    r = client.post("/api/shops", headers=h, json=SHOP)
    assert (r.status_code, r.json()["error"]["code"]) == (403, "consent_required")


def test_another_owners_notification_cannot_be_marked_read(client, two_owners):
    _, b, _ = two_owners
    r = client.post("/api/notifications/999999/read", headers=b)
    assert r.status_code == 404


def test_no_table_has_a_column_for_identity_documents_or_contact_details():
    """Data minimisation (ARCHITECTURE section 11): the phone number is the only personal identifier stored."""
    import re

    from app.db import Base
    bad = re.compile(r"aadhaar|aadhar|\bpan\b|pan_|email|address|dob|birth|gender|caste|religion|income_cert", re.IGNORECASE)
    cols = [(t.name, c.name) for t in Base.metadata.sorted_tables for c in t.columns]
    assert not [x for x in cols if bad.search(x[1])], cols
    assert [c for t, c in cols if t == "user"] == ["id", "phone", "language", "created_at"]


def test_scheme_profile_fields_are_never_stored(client, two_owners, db_factory):
    """DEC-86: age, category, state and the free-text need are request-only."""
    from sqlalchemy import text

    a, _, shop_a = two_owners
    marker = "Zorbaville"
    r = client.get("/api/schemes/match", headers=a,
                   params={"shop_id": shop_a, "state": marker, "age": 41, "category": "sc", "need": f"{marker} loan"})
    assert r.status_code == 200, r.text
    with db_factory() as db:
        tables = [t[0] for t in db.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))]
        for t in tables:
            for row in db.execute(text(f'SELECT * FROM "{t}"')):
                assert marker not in " ".join(map(str, row)), t
