"""B-02: request and verify OTP returns a JWT; wrong OTP is rejected; a protected route needs the token."""
import logging
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import get_settings
from app.services import auth
from tests.conftest import login

PHONE = "+919800000001"


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def test_request_and_verify_returns_jwt_and_me_works(client):
    r = client.post("/api/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 200
    body = r.json()
    assert body["is_mock"] is True and len(body["dev_otp"]) == 6 and body["expires_in_seconds"] == 300
    r = client.post("/api/auth/otp/verify", json={"phone": PHONE, "otp": body["dev_otp"]})
    assert r.status_code == 200
    tok = r.json()
    assert tok["token_type"] == "bearer" and tok["is_new_user"] is True and tok["expires_in_seconds"] == 7 * 86400
    me = client.get("/api/me", headers={"Authorization": f"Bearer {tok['access_token']}"})
    assert me.status_code == 200 and me.json()["phone"] == PHONE and me.json()["language"] == "hi"


def test_second_login_is_the_same_user(client):
    a = client.get("/api/me", headers=login(client)).json()
    otp = client.post("/api/auth/otp/request", json={"phone": "98000 00001"}).json()["dev_otp"]   # same number, typed loosely
    r = client.post("/api/auth/otp/verify", json={"phone": PHONE, "otp": otp})
    assert r.json()["is_new_user"] is False
    b = client.get("/api/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert a["id"] == b["id"]


def test_wrong_otp_is_rejected_and_right_one_still_works(client):
    otp = client.post("/api/auth/otp/request", json={"phone": PHONE}).json()["dev_otp"]
    r = client.post("/api/auth/otp/verify", json={"phone": PHONE, "otp": _wrong(otp)})
    assert r.status_code == 401 and r.json()["error"]["code"] == "otp_wrong"
    assert client.post("/api/auth/otp/verify", json={"phone": PHONE, "otp": otp}).status_code == 200


def test_otp_works_only_once(client):
    otp = client.post("/api/auth/otp/request", json={"phone": PHONE}).json()["dev_otp"]
    assert client.post("/api/auth/otp/verify", json={"phone": PHONE, "otp": otp}).status_code == 200
    r = client.post("/api/auth/otp/verify", json={"phone": PHONE, "otp": otp})
    assert r.status_code == 401 and r.json()["error"]["code"] == "otp_not_requested"


def test_five_wrong_tries_burn_the_code(client):
    otp = client.post("/api/auth/otp/request", json={"phone": PHONE}).json()["dev_otp"]
    codes = [client.post("/api/auth/otp/verify", json={"phone": PHONE, "otp": _wrong(otp)}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 401, 429]
    assert client.post("/api/auth/otp/verify", json={"phone": PHONE, "otp": otp}).status_code == 401


def test_verify_without_request_and_bad_phone(client):
    r = client.post("/api/auth/otp/verify", json={"phone": PHONE, "otp": "123456"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "otp_not_requested"
    assert client.post("/api/auth/otp/request", json={"phone": "not-a-phone"}).status_code == 422


def test_otp_expires_after_five_minutes():
    auth.reset_store()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    code = auth.request_otp(PHONE, now=t0)
    with pytest.raises(auth.AuthError, match="otp_expired"):
        auth.verify_otp(PHONE, code, now=t0 + timedelta(minutes=5, seconds=1))
    code = auth.request_otp(PHONE, now=t0)
    assert auth.verify_otp(PHONE, code, now=t0 + timedelta(minutes=4, seconds=59)) == PHONE


def test_protected_route_needs_a_valid_token(client, auth_headers):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    forged = jwt.encode({"sub": "1", "exp": datetime.now(UTC) + timedelta(days=1)}, "x" * 40, algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    old, _ = auth.create_token(1, now=datetime.now(UTC) - timedelta(days=8))
    assert client.get("/api/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    ghost, _ = auth.create_token(999)                       # signed correctly, but no such user
    assert client.get("/api/me", headers={"Authorization": f"Bearer {ghost}"}).status_code == 401
    assert client.get("/api/me", headers=auth_headers).status_code == 200


def test_otp_is_logged_in_dev_mode_and_hidden_otherwise(client, caplog, monkeypatch):
    with caplog.at_level(logging.WARNING, logger="sarthi.auth"):
        otp = client.post("/api/auth/otp/request", json={"phone": PHONE}).json()["dev_otp"]
    assert otp in caplog.text and "MOCK OTP" in caplog.text
    monkeypatch.setenv("DEV_MODE", "0")
    monkeypatch.setenv("JWT_SECRET", "s" * 40)
    get_settings.cache_clear()
    try:
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="sarthi.auth"):
            r = client.post("/api/auth/otp/request", json={"phone": PHONE})
        assert r.status_code == 200 and r.json()["dev_otp"] is None and "MOCK OTP" not in caplog.text
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_default_secret_refused_outside_dev_mode(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "0")
    monkeypatch.setenv("JWT_SECRET", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            auth.create_token(1)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
