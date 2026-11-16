"""B-04: an owner can create and read only their own shops."""
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect

from app.db import make_engine
from tests.conftest import SHOP, login

BACKEND = Path(__file__).resolve().parent.parent


def test_create_and_read_own_shop(client, consented):
    r = client.post("/api/shops", headers=consented, json=SHOP)
    assert r.status_code == 201
    shop = r.json()
    assert shop["id"] > 0 and shop["is_demo"] is False and shop["launch_date"] is None
    assert {k: shop[k] for k in SHOP} == SHOP
    got = client.get(f"/api/shops/{shop['id']}", headers=consented)
    assert got.status_code == 200 and got.json() == shop
    assert client.get("/api/shops", headers=consented).json() == [shop]


def test_other_owner_cannot_read_or_list_it(client, consented):
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    other = login(client, "+919800000002")
    client.post("/api/consents", headers=other, json={"purpose": "shop_data"})
    r = client.get(f"/api/shops/{shop_id}", headers=other)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "shop_not_found"
    assert client.get("/api/shops", headers=other).json() == []
    mine = client.post("/api/shops", headers=other, json={**SHOP, "name": "Second Shop"}).json()
    assert [s["id"] for s in client.get("/api/shops", headers=other).json()] == [mine["id"]]
    assert client.get(f"/api/shops/{mine['id']}", headers=consented).status_code == 404


def test_needs_login_and_missing_shop_is_404(client, consented):
    assert client.post("/api/shops", json=SHOP).status_code == 401
    assert client.get("/api/shops/1").status_code == 401
    assert client.get("/api/shops/9999", headers=consented).status_code == 404


def test_bad_input_is_rejected(client, consented):
    for bad in ({"city_tier": 4}, {"size_sqft": 5}, {"budget": 0}, {"lat": 120}, {"shop_type": "pharmacy"},
                {"name": ""}, {"staff_count": -1}, {"monthly_rent": -5}):
        assert client.post("/api/shops", headers=consented, json={**SHOP, **bad}).status_code == 422, bad
    missing = {k: v for k, v in SHOP.items() if k != "size_sqft"}
    assert client.post("/api/shops", headers=consented, json=missing).status_code == 422


def test_launch_date_round_trips(client, consented):
    r = client.post("/api/shops", headers=consented, json={**SHOP, "launch_date": "2026-08-01"})
    assert r.status_code == 201 and r.json()["launch_date"] == "2026-08-01"


def test_migration_adds_shop_columns_and_downgrades(tmp_path):
    db = tmp_path / "mig.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db.as_posix()}"}

    def alembic(*args):
        r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True,
                           text=True, check=False)
        assert r.returncode == 0, r.stderr
        return {c["name"] for c in inspect(make_engine(f"sqlite:///{db.as_posix()}")).get_columns("shop")}

    assert {"name", "size_sqft", "city_tier"} <= alembic("upgrade", "head")
    assert not {"name", "size_sqft", "city_tier"} & alembic("downgrade", "0001")
