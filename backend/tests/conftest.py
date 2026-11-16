"""Shared API test fixtures: a fresh SQLite file per test and helpers to log in."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db, make_engine
from app.main import app
from app.services import auth


@pytest.fixture
def db_factory(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def client(db_factory):
    def _db():
        with db_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    auth.reset_store()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login(client: TestClient, phone: str = "+919800000001") -> dict:
    """Mock-OTP login; returns the Authorization header."""
    otp = client.post("/api/auth/otp/request", json={"phone": phone}).json()["dev_otp"]
    r = client.post("/api/auth/otp/verify", json={"phone": phone, "otp": otp})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_headers(client):
    return login(client)
