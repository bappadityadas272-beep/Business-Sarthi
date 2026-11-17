"""D-05: the demo seed (two SYNTHETIC shops, dates shifted to the seed day)."""
import json
import shutil
from datetime import timedelta

import pytest
import yaml
from sqlalchemy import func, select

from app import seed as sd
from app.models import Alert, DailyLog, Forecast, Loan, Shop, StockItem, User
from app.services import clock, consent
from tests.conftest import login

RAMESH, SUNITA = "+919000000001", "+919000000002"


@pytest.fixture
def seeded(client, db_factory, synth_small, model_small):
    with db_factory() as db:
        return sd.seed(db, clock.today(), demo_dir=synth_small / "demo", model=model_small)


def test_seed_creates_the_demo_users_and_shops_with_three_months_of_logs(seeded, db_factory):
    """The acceptance line of D-05 (demo script step 4: the pre-loaded logs are there)."""
    today = clock.today()
    assert seeded["is_synthetic"] is True and seeded["is_demo"] is True
    assert [s["phone"] for s in seeded["shops"]] == [RAMESH, SUNITA]
    with db_factory() as db:
        for s in seeded["shops"]:
            shop = db.get(Shop, s["shop_id"])
            user = db.get(User, shop.user_id)
            assert shop.is_demo is True and user.phone == s["phone"]
            assert consent.active(db, user.id, consent.SHOP_DATA) is not None         # consent before any shop data
            assert shop.launch_date == today - timedelta(days=88) and shop.opening_cash > 0
            first, last, days = db.execute(select(func.min(DailyLog.day), func.max(DailyLog.day), func.count(
                func.distinct(DailyLog.day))).where(DailyLog.shop_id == shop.id)).one()
            assert (first, last, days) == (shop.launch_date, today - timedelta(days=1), 88)
            rent_days = db.scalars(select(DailyLog.day).where(DailyLog.shop_id == shop.id, DailyLog.expenses > 0)
                                   .order_by(DailyLog.day)).all()
            assert rent_days == [sd.add_months(shop.launch_date, n) for n in range(3)]
            fc_row = db.scalars(select(Forecast).where(Forecast.shop_id == shop.id)).one()
            assert fc_row.kind == "setup" and len(fc_row.horizon_months) == 12
            assert fc_row.horizon_months[0]["start"] == shop.launch_date.isoformat()
            loan = db.scalars(select(Loan).where(Loan.shop_id == shop.id)).one()
            assert loan.start_date == shop.launch_date and loan.due_day == shop.launch_date.day
            assert db.scalar(select(func.count()).select_from(StockItem).where(StockItem.shop_id == shop.id)) == 7
            assert s["first_review_due"] == today + timedelta(days=2)


def test_demo_login_sees_only_its_own_shop_and_the_replayed_alerts(seeded, client):
    ramesh, sunita = login(client, RAMESH), login(client, SUNITA)
    mine = client.get("/api/shops", headers=ramesh).json()
    assert [s["name"] for s in mine] == ["Ramesh Kirana"]
    assert [s["name"] for s in client.get("/api/shops", headers=sunita).json()] == ["Sunita General Store"]
    shop_id = mine[0]["id"]
    assert client.get(f"/api/shops/{shop_id}", headers=sunita).status_code == 404
    logs = client.get(f"/api/shops/{shop_id}/logs", headers=ramesh)
    assert logs.status_code == 200
    alerts = client.get(f"/api/shops/{shop_id}/alerts", headers=ramesh).json()
    kinds = {a["kind"] for a in alerts}
    assert {"low_stock", "dead_stock", "emi_due", "sales_dip"} <= kinds                # demo script step 5
    dip = [a for a in alerts if a["kind"] == "sales_dip"]
    assert len(dip) == 1 and dip[0]["still_active"] is False      # fired in month 2 (DEC-72), kept open (DEC-67b)
    live_emi = [a for a in alerts if a["kind"] == "emi_due" and a["cleared_on"] is None]
    assert len(live_emi) == 1 and 0 <= live_emi[0]["params"]["days_to_due"] <= 5


def test_advance_time_gives_pivot_for_ramesh_and_grow_for_sunita(seeded, client):
    """Demo script step 6. The decision comes from the review rules, not from the seed."""
    ramesh, sunita = login(client, RAMESH), login(client, SUNITA)
    ids = {s["phone"]: s["shop_id"] for s in seeded["shops"]}
    assert client.get(f"/api/shops/{ids[RAMESH]}/reviews/latest", headers=ramesh).status_code == 404
    r = client.post("/api/dev/advance-time", headers=ramesh, json={"days": 2})
    assert r.status_code == 200 and r.json()["reviews_created"] == 2 and r.json()["errors"] == 0
    a = client.get(f"/api/shops/{ids[RAMESH]}/reviews/latest", headers=ramesh).json()
    b = client.get(f"/api/shops/{ids[SUNITA]}/reviews/latest", headers=sunita).json()
    assert a["decision"] == "pivot" and b["decision"] == "grow"
    assert a["indicators"]["days_logged"] == 88 and a["period_start"] == (clock.today() - timedelta(days=90)).isoformat()
    for headers in (ramesh, sunita):
        kinds = [n["kind"] for n in client.get("/api/notifications", headers=headers).json()["items"]]
        assert kinds.count("review_ready") == 1


def test_seeding_again_replaces_the_demo_data(seeded, db_factory, synth_small, model_small):
    with db_factory() as db:
        before = [db.scalar(select(func.count()).select_from(m)) for m in (User, Shop, DailyLog, Alert, StockItem)]
        sd.seed(db, clock.today(), demo_dir=synth_small / "demo", model=model_small)
        after = [db.scalar(select(func.count()).select_from(m)) for m in (User, Shop, DailyLog, Alert, StockItem)]
    assert before == after and before[:2] == [2, 2]


def test_seed_refuses_unlabelled_or_stale_demo_data(tmp_path, synth_small):
    d = tmp_path / "demo"
    shutil.copytree(synth_small / "demo", d)
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    (d / "metadata.json").write_text(json.dumps({**meta, "config_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(sd.SeedError, match="different config"):
        sd.load_demo(demo_dir=d)
    (d / "metadata.json").write_text(json.dumps({**meta, "is_synthetic": False}), encoding="utf-8")
    with pytest.raises(sd.SeedError, match="is_synthetic"):
        sd.load_demo(demo_dir=d)
    with pytest.raises(sd.SeedError, match="make synth"):
        sd.load_demo(demo_dir=tmp_path / "missing")


def test_demo_stock_never_sells_more_than_is_on_hand():
    cfg = yaml.safe_load(sd.CONFIG.read_text(encoding="utf-8"))
    for k, spec in enumerate(cfg["demo_stock"]):
        on_hand, last_sale = 0.0, None
        for offset, qty, kind in sd.stock_moves(spec, 88, k):
            on_hand += qty
            assert on_hand >= 0, spec["name"]
            if kind == "sale":
                last_sale = offset
        if spec["pattern"] == "dead":
            assert on_hand > 0 and last_sale <= 20
