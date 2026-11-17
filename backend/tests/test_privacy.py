"""B-11 delete-my-data (DEC-84): no row tied to the owner remains, others are untouched, the old token dies."""
from datetime import date

from sqlalchemy import select

from app.llm.client import answer_cache
from app.models import (
    Alert,
    Asset,
    ChatMessage,
    DailyLog,
    Forecast,
    Loan,
    Notification,
    Review,
    Shop,
    StockItem,
    StockMove,
    User,
)
from app.services import auth, privacy
from tests.conftest import SHOP, login

D = date(2026, 3, 1)


def fill(db, user_id: int, shop_id: int) -> None:
    """One row in every table tied to this owner."""
    item = StockItem(shop_id=shop_id, name="atta", category="staples", unit="kg", cost=30, price=35)
    db.add_all([DailyLog(shop_id=shop_id, day=D, category="staples", sales=1000),
                Forecast(shop_id=shop_id, kind="setup", made_on=D, horizon_months=[]),
                Review(shop_id=shop_id, period_start=D, period_end=D, decision="hold", indicators={}, reasons=[],
                       actions=[]),
                Loan(shop_id=shop_id, principal=100000, emi=3000, due_day=5),
                Alert(shop_id=shop_id, kind="emi_due", severity="warn", message_key="x"),
                Asset(shop_id=shop_id, name="fridge", cost=20000),
                ChatMessage(shop_id=shop_id, role="user", text="profit?"),
                Notification(user_id=user_id, kind="alert"), item])
    db.flush()
    db.add(StockMove(item_id=item.id, day=D, qty=5, kind="purchase"))
    db.commit()


def setup_two_owners(client, db_factory):
    a, b = login(client, "+919800000011"), login(client, "+919800000022")
    ids = {}
    for name, h in (("a", a), ("b", b)):
        client.post("/api/consents", headers=h, json={"purpose": "shop_data"})
        sid = client.post("/api/shops", headers=h, json=SHOP).json()["id"]
        uid = client.get("/api/me", headers=h).json()["id"]
        with db_factory() as db:
            fill(db, uid, sid)
        ids[name] = (uid, sid)
    return a, b, ids


def test_every_row_of_the_owner_goes_and_nothing_else(client, db_factory):
    a, _, ids = setup_two_owners(client, db_factory)
    with db_factory() as db:
        before_b = privacy.owned_counts(db, ids["b"][0])
        before_a = privacy.owned_counts(db, ids["a"][0])
    assert all(v >= 1 for v in before_a.values()), before_a          # the test really covers every table

    r = client.delete("/api/me/data", headers=a)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["deleted"] == before_a and out["backups_touched"] is False
    with db_factory() as db:
        assert set(privacy.owned_counts(db, ids["a"][0]).values()) == {0}
        assert db.get(Shop, ids["a"][1]) is None
        assert privacy.owned_counts(db, ids["b"][0]) == before_b      # the other owner keeps everything
        assert db.scalars(select(User.phone)).all() == ["+919800000022"]


def test_the_old_token_stops_working_even_if_the_id_is_reused(client, db_factory):
    a = login(client, "+919800000033")
    uid = client.get("/api/me", headers=a).json()["id"]
    assert client.delete("/api/me/data", headers=a).status_code == 200
    assert client.get("/api/me", headers=a).status_code == 401
    assert client.delete("/api/me/data", headers=a).status_code == 401
    with db_factory() as db:            # a new user that gets the same id (SQLite reuses the top rowid)
        db.add(User(id=uid, phone="+919800000044"))
        db.commit()
    r = client.get("/api/me", headers=a)
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
    assert client.get("/api/me", headers=login(client, "+919800000044")).json()["id"] == uid   # its own token works


def test_a_token_without_the_account_stamp_is_refused(client):
    a = login(client, "+919800000088")
    uid = client.get("/api/me", headers=a).json()["id"]
    bare, _ = auth.create_token(uid)
    assert client.get("/api/me", headers={"Authorization": f"Bearer {bare}"}).status_code == 401


def test_logging_in_again_starts_an_empty_account(client):
    a = login(client, "+919800000055")
    client.post("/api/consents", headers=a, json={"purpose": "shop_data"})
    client.post("/api/shops", headers=a, json=SHOP)
    client.delete("/api/me/data", headers=a)
    again = login(client, "+919800000055")
    assert client.get("/api/shops", headers=again).json() == []
    assert client.get("/api/consents/history", headers=again).json() == []


def test_works_after_consent_is_withdrawn_and_needs_login(client):
    a = login(client, "+919800000066")
    client.post("/api/consents", headers=a, json={"purpose": "shop_data"})
    client.delete("/api/consents", params={"purpose": "shop_data"}, headers=a)
    assert client.delete("/api/me/data", headers=a).status_code == 200
    assert client.delete("/api/me/data").status_code == 401


def test_in_memory_copies_go_too(client, db_factory):
    a, _, ids = setup_two_owners(client, db_factory)
    sid_a, sid_b = ids["a"][1], ids["b"][1]
    answer_cache.put(answer_cache.key(sid_a, D, "q", "{}"), "A")
    answer_cache.put(answer_cache.key(sid_b, D, "q", "{}"), "B")
    auth.request_otp("+919800000011")
    client.delete("/api/me/data", headers=a)
    assert answer_cache.get(answer_cache.key(sid_a, D, "q", "{}")) is None
    assert answer_cache.get(answer_cache.key(sid_b, D, "q", "{}")) == "B"
    assert "+919800000011" not in auth._store


def test_the_log_line_has_no_phone(client, caplog):
    import logging
    a = login(client, "+919800000077")
    caplog.clear()                      # the mock OTP line of the login is hardening item, not B-11
    with caplog.at_level(logging.INFO, logger="sarthi.privacy"):
        client.delete("/api/me/data", headers=a)
    assert "delete-my-data" in caplog.text and "9800000077" not in caplog.text
