from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


def test_health_ok():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_docs_served():
    assert TestClient(app).get("/docs").status_code == 200


def test_empty_env_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("DEV_MODE", "0")
    s = Settings(_env_file=None)
    assert s.llm_provider == "stub"
    assert s.dev_mode is False
