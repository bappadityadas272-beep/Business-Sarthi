"""Hardening (DEC-90, DEC-91): error shape, logs, rate limits, body limit, CORS, dev gate, ready, about, model status."""
import hashlib
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import ratelimit
from app.api import health as health_api
from app.config import get_settings
from app.db import get_db, make_engine
from app.main import app, startup_checks
from app.ml import forecast as fc
from app.ml.train import MODEL_FILE, MODEL_VERSION
from app.obs import JsonFormatter, mask_phone, redact
from app.rules import FILES
from tests.conftest import SHOP

PHONE = "+919812345678"
OK_MODEL = {"ok": True, "reason": None, "version": MODEL_VERSION, "is_synthetic": True, "fix": None}


@pytest.fixture
def dev_off(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "0")
    monkeypatch.setenv("JWT_SECRET", "s" * 40)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


# ---- one error shape ----
def test_every_error_has_the_same_envelope(client, consented):
    nf = client.get("/api/no-such-route").json()
    assert nf == {"error": {"code": "not_found", "message": "Not found.", "details": {}}}
    assert client.delete("/api/health").json()["error"]["code"] == "method_not_allowed"
    shop = client.get("/api/shops/999", headers=consented).json()["error"]
    assert shop["code"] == "shop_not_found" and shop["message"] and shop["details"] == {}
    bad = client.post("/api/auth/otp/verify", json={"phone": PHONE, "otp": {"secret": PHONE}})
    e = bad.json()["error"]
    assert bad.status_code == 422 and e["code"] == "invalid_input" and e["details"]["fields"][0]["loc"][0] == "body"
    assert PHONE not in bad.text and "secret" not in bad.text          # submitted values are never echoed


def test_a_crash_answers_500_without_internals(client, auth_headers, caplog):
    def boom():
        raise RuntimeError("database at /secret/path.db broke for +919812345678")
        yield
    app.dependency_overrides[get_db] = boom                  # the client fixture clears overrides afterwards
    with caplog.at_level(logging.ERROR, logger="sarthi.errors"):
        r = TestClient(app, raise_server_exceptions=False).get("/api/me", headers=auth_headers)
    assert r.status_code == 500 and r.json() == {"error": {"code": "internal_error",
                                                           "message": "Something went wrong on our side.",
                                                           "details": {}}}
    assert "secret" not in r.text and "9812345678" not in r.text
    assert caplog.records[-1].request_id                    # the log line can be found from the request id


# ---- logs ----
def test_phones_and_keys_are_masked():
    assert mask_phone("+91 98123 45678") == "********78"
    for p in ("+919812345678", "919812345678", "9812345678", "+91-9812345678"):
        assert redact(f"user {p} logged in") == "user ********78 logged in", p
    assert "AIza" not in redact("key AIza" + "x" * 30) and "sk-ant" not in redact("sk-ant-" + "y" * 20)
    assert redact("Authorization: Bearer abc.def.ghi123") == "Authorization: [redacted]"
    assert redact("revenue 300000 for 90 days") == "revenue 300000 for 90 days"         # numbers stay


def test_log_lines_are_json_and_masked():
    rec = logging.makeLogRecord({"name": "t", "levelname": "INFO", "msg": "otp for %s", "args": (PHONE,),
                                 "path": "/api/x", "status": 200})
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "otp for ********78" and out["path"] == "/api/x" and out["status"] == 200 and out["ts"]
    try:
        raise ValueError(f"bad phone {PHONE}")
    except ValueError:
        import sys
        rec = logging.makeLogRecord({"name": "t", "levelname": "ERROR", "msg": "x", "exc_info": sys.exc_info()})
    assert PHONE not in JsonFormatter().format(rec)


def test_mock_otp_log_line_shows_only_the_last_two_digits(client, caplog):
    with caplog.at_level(logging.WARNING, logger="sarthi.auth"):
        otp = client.post("/api/auth/otp/request", json={"phone": PHONE}).json()["dev_otp"]
    assert otp in caplog.text and "********78" in caplog.text and "9812345678" not in caplog.text


def test_each_request_gets_a_request_id_and_one_log_line(client, caplog):
    with caplog.at_level(logging.INFO, logger="sarthi.http"):
        r = client.get("/api/health")
    line = [x for x in caplog.records if x.name == "sarthi.http"][-1]
    assert line.path == "/api/health" and line.status == 200 and line.request_id == r.headers["x-request-id"]


# ---- rate limits (moderate) ----
def test_otp_limit_per_phone(client):
    for _ in range(3):
        assert client.post("/api/auth/otp/request", json={"phone": PHONE}).status_code == 200
    r = client.post("/api/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert 1 <= r.json()["error"]["details"]["retry_after"] <= 600 and r.headers["retry-after"]
    assert client.post("/api/auth/otp/request", json={"phone": "+919812345679"}).status_code == 200


def test_otp_limit_per_client_address(client):
    for i in range(20):
        assert client.post("/api/auth/otp/request", json={"phone": f"+9198100000{i:02d}"}).status_code == 200
    assert client.post("/api/auth/otp/request", json={"phone": "+919810000099"}).status_code == 429


def test_chat_limit_per_user(client, consented):
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    user_id = client.get("/api/me", headers=consented).json()["id"]
    for _ in range(20):
        ratelimit.check((ratelimit.CHAT_PER_USER, str(user_id)))
    r = client.post("/api/chat", headers=consented, json={"shop_id": shop_id, "message": "profit?"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def test_window_slides_and_a_refused_hit_is_not_counted():
    ratelimit.reset()
    rule = ("t", 2, 60)
    ratelimit.check((rule, "k"), now=0)
    ratelimit.check((rule, "k"), now=10)
    with pytest.raises(Exception) as e:
        ratelimit.check((rule, "k"), now=30)
    assert e.value.detail["retry_after"] == 30
    ratelimit.check((rule, "k"), now=60.5)            # the first hit has left the window
    ratelimit.reset()


# ---- body size ----
def test_large_bodies_get_413(client):
    big = {"phone": PHONE, "pad": "x" * 70_000}
    r = client.post("/api/auth/otp/request", json=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "request_too_large"
    chunked = client.post("/api/auth/otp/request", content=iter([b'{"phone": "', b"x" * 70_000, b'"}']),
                          headers={"content-type": "application/json"})
    assert chunked.status_code == 413
    ok = client.post("/api/auth/otp/request", content=iter([json.dumps({"phone": PHONE}).encode()]),
                     headers={"content-type": "application/json"})
    assert ok.status_code == 200                       # a small chunked body still reaches the endpoint


# ---- CORS ----
def test_cors_only_for_configured_origins(client):
    pre = {"access-control-request-method": "POST", "access-control-request-headers": "authorization"}
    ok = client.options("/api/chat", headers={"origin": "http://localhost:5173", **pre})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/chat", headers={"origin": "https://evil.example", **pre})
    assert "access-control-allow-origin" not in bad.headers
    s = get_settings().model_copy(update={"cors_origins": "*, https://a.example ,"})
    assert s.cors_origin_list == ["https://a.example"]                    # a wildcard is never allowed


# ---- dev routes with DEV_MODE off (DEC-91) ----
def test_dev_routes_look_absent_when_dev_mode_is_off(client, consented, dev_off):
    unknown = client.get("/api/no-such-route")
    for r in (client.get("/api/dev/clock"), client.post("/api/dev/advance-time", json={"days": 1}),
              client.post("/api/dev/advance-time", headers=consented, content=b"{not json")):
        assert r.status_code == 404 and r.json() == unknown.json()
    assert not [p for p in client.get("/openapi.json").json()["paths"] if p.startswith("/api/dev")]


def test_dev_routes_are_documented_in_dev_mode(client):
    assert "/api/dev/advance-time" in client.get("/openapi.json").json()["paths"]


# ---- ready ----
def test_ready_when_everything_is_in_place(client, monkeypatch):
    monkeypatch.setattr(health_api.fc, "model_status", lambda: OK_MODEL)
    r = client.get("/api/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert r.json()["checks"]["llm"] == {"ok": True, "provider": "stub", "reason": "offline_stub_answers"}


def test_not_ready_says_why(client, monkeypatch):
    monkeypatch.setattr(health_api.fc, "model_status",
                        lambda: {**OK_MODEL, "ok": False, "reason": "model_files_missing", "fix": "make train"})
    no_key = get_settings().model_copy(update={"llm_provider": "gemini", "llm_api_key": ""})
    monkeypatch.setattr(health_api, "get_settings", lambda: no_key)     # .env may hold a real key: never read here
    r = client.get("/api/ready")
    c = r.json()["checks"]
    assert r.status_code == 503 and r.json()["status"] == "not_ready" and c["database"]["ok"]
    assert c["model"]["reason"] == "model_files_missing" and c["model"]["fix"] == "make train"
    assert c["llm"] == {"ok": False, "provider": "gemini", "reason": "llm_api_key_missing"}
    fake = "not-a-real-key-" + "z" * 12
    with_key = no_key.model_copy(update={"llm_api_key": fake})
    monkeypatch.setattr(health_api, "get_settings", lambda: with_key)
    r = client.get("/api/ready")
    assert r.json()["checks"]["llm"]["ok"] and fake not in r.text


def test_not_ready_when_the_database_has_no_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(health_api.fc, "model_status", lambda: OK_MODEL)
    empty = sessionmaker(bind=make_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"))

    def _db():
        with empty() as s:
            yield s
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            r = c.get("/api/ready")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503 and r.json()["checks"]["database"]["fix"] == "make migrate"
    assert "empty.db" not in r.text


# ---- model status: missing or stale ----
def _fake_model(d, cfg, *, version=MODEL_VERSION):
    d.mkdir(parents=True, exist_ok=True)
    (d / MODEL_FILE).write_bytes(b"model-bytes")
    cfg.write_bytes(b"seed: 1\n")
    card = {"version": version, "is_synthetic": True,
            "files_sha256": {MODEL_FILE: hashlib.sha256(b"model-bytes").hexdigest()},
            "data": {"config_sha256": hashlib.sha256(b"seed: 1\n").hexdigest()}}
    (d / "model_card.json").write_text(json.dumps(card), encoding="utf-8")


def test_model_status_finds_missing_changed_and_stale_models(tmp_path):
    d, cfg = tmp_path / "m", tmp_path / "config.yaml"
    assert fc.model_status(d, cfg)["reason"] == "model_files_missing"
    _fake_model(d, cfg)
    assert fc.model_status(d, cfg) == {**OK_MODEL}
    cfg.write_bytes(b"seed: 2\n")                                         # SYNTHETIC config edited after training
    assert fc.model_status(d, cfg)["reason"] == "model_stale_config_changed"
    _fake_model(d, cfg)
    (d / MODEL_FILE).write_bytes(b"other model")
    assert fc.model_status(d, cfg)["reason"] == "model_file_changed"
    _fake_model(d, cfg, version="ml2-0.9.0")
    assert fc.model_status(d, cfg)["reason"] == "model_version_mismatch"
    (d / MODEL_FILE).unlink()
    assert fc.model_status(d, cfg)["reason"] == "model_files_missing"


def test_forecast_says_503_with_the_reason_when_the_model_is_stale(client, consented, monkeypatch):
    from app.api.forecast import forecast_model
    app.dependency_overrides.pop(forecast_model, None)
    monkeypatch.setattr(fc, "model_status",
                        lambda: {**OK_MODEL, "ok": False, "reason": "model_stale_config_changed", "fix": "make train"})
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    e = client.post(f"/api/shops/{shop_id}/forecast", headers=consented).json()["error"]
    assert e["code"] == "model_not_ready" and e["details"] == {"reason": "model_stale_config_changed",
                                                               "fix": "make train"}


def test_startup_logs_a_clear_error_for_a_missing_model(monkeypatch, caplog):
    monkeypatch.setattr(fc, "model_status",
                        lambda: {**OK_MODEL, "ok": False, "reason": "model_files_missing", "fix": "make train"})
    with caplog.at_level(logging.ERROR, logger="sarthi.startup"):
        out = startup_checks()
    assert not out["model"]["ok"] and "model_files_missing" in caplog.text and "make train" in caplog.text


# ---- about ----
def test_about_shows_the_model_card_and_assumption_flags(client, monkeypatch):
    a = client.get("/api/about").json()
    assert a["is_prototype"] is True and a["model"]["is_synthetic"] is True and "SYNTHETIC" in a["notice"]
    assert set(a["rules"]) == set(FILES) and all("assumption" in v for v in a["rules"].values())
    if a["model"]["card"] is not None:
        assert a["model"]["card"]["is_synthetic"] is True and a["model"]["card"]["version"]
    monkeypatch.setattr(health_api.fc, "model_status",
                        lambda: {**OK_MODEL, "ok": False, "reason": "model_files_missing", "fix": "make train"})
    gone = client.get("/api/about").json()["model"]
    assert gone["card"] is None and gone["status"]["reason"] == "model_files_missing" and gone["is_synthetic"]


# ---- login configuration outside dev mode (audit A2-2, DEC-97) ----
@pytest.fixture
def prod_secret(monkeypatch):
    """Switch auth to DEV_MODE off with a chosen JWT_SECRET; only the auth module's settings change."""
    from app.services import auth as auth_service

    def use(secret: str):
        s = get_settings().model_copy(update={"dev_mode": False, "jwt_secret": secret})
        monkeypatch.setattr(auth_service, "get_settings", lambda: s)
    return use


@pytest.mark.parametrize(("secret", "reason"), [("", "jwt_secret_not_set"),
                                                ("dev-only-change-me-not-a-secret-placeholder", "jwt_secret_not_set"),
                                                ("short-secret", "jwt_secret_too_short")])
def test_without_a_real_jwt_secret_ready_and_login_say_so(client, monkeypatch, prod_secret, caplog, secret, reason):
    from app.services import auth as auth_service
    token = auth_service.create_token(1)[0]                  # made while the dev secret is still allowed
    monkeypatch.setattr(health_api.fc, "model_status", lambda: OK_MODEL)
    prod_secret(secret)
    r = client.get("/api/ready")
    assert r.status_code == 503 and r.json()["checks"]["auth"]["reason"] == reason
    assert "JWT_SECRET" in r.json()["checks"]["auth"]["fix"] and (secret == "" or secret not in r.text)
    for path, body in (("/api/auth/otp/request", {"phone": PHONE}), ("/api/auth/otp/verify", {"phone": PHONE, "otp": "123456"})):
        x = client.post(path, json=body)
        assert x.status_code == 503 and x.json()["error"]["code"] == "auth_not_configured", x.text
    x = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})     # reading a token is refused too
    assert x.status_code == 503 and x.json()["error"]["code"] == "auth_not_configured"
    with caplog.at_level(logging.ERROR, logger="sarthi.startup"):
        assert startup_checks()["auth"]["ok"] is False
    assert reason in caplog.text and "JWT_SECRET" in caplog.text


def test_a_real_jwt_secret_outside_dev_mode_is_ready(client, monkeypatch, prod_secret):
    monkeypatch.setattr(health_api.fc, "model_status", lambda: OK_MODEL)
    prod_secret("x" * 40)
    r = client.get("/api/ready")
    assert r.status_code == 200 and r.json()["checks"]["auth"] == {"ok": True, "reason": None}
    otp = client.post("/api/auth/otp/request", json={"phone": PHONE})
    assert otp.status_code == 200 and otp.json()["sent"] is True
