"""B-10 SOS (DEC-83): shareable summary of alerts, EMI and the last 30 days, plus a checklist chosen by code."""
from datetime import timedelta

from sqlalchemy import func, select

from app.models import Alert, DailyLog, Loan
from app.services import clock, privacy
from tests.conftest import SHOP, login


def make_shop(client, h, db_factory, *, sales: float, purchases: float, expenses: float, days: int = 30,
              loan: bool = False, alerts: tuple = ()):
    sid = client.post("/api/shops", headers=h, json=SHOP).json()["id"]
    today = clock.today()
    with db_factory() as db:
        for i in range(1, days + 1):
            db.add(DailyLog(shop_id=sid, day=today - timedelta(days=i), category="staples", sales=sales,
                            purchases=purchases, expenses=expenses))
        if loan:
            due = today + timedelta(days=3)
            db.add(Loan(shop_id=sid, principal=200000, emi=6500, due_day=due.day,
                        start_date=today - timedelta(days=70), tenure_months=24))
        for kind, params in alerts:
            db.add(Alert(shop_id=sid, kind=kind, severity="warn", message_key=f"alert.{kind}", params=params,
                         dedupe_key=kind, raised_on=today))
        db.commit()
    return sid


def sos(client, h, sid, language=None):
    r = client.post("/api/sos", headers=h, json={"shop_id": sid, **({"language": language} if language else {})})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_shop_in_trouble_gets_the_urgent_steps_first(client, consented, db_factory):
    sid = make_shop(client, consented, db_factory, sales=2000, purchases=1800, expenses=400, loan=True,
                    alerts=(("sales_dip", {"drop_percent": 30}), ("dead_stock", {"value": 4200})))
    out = sos(client, consented, sid, "en")
    assert [s["key"] for s in out["steps"]] == ["emi_soon", "loss", "sales_dip", "dead_stock", "share", "official"]
    assert out["last_30_days"]["operating_profit"] == -6000 and out["last_30_days"]["days_logged"] == 30
    assert out["emi"][0]["days_to_next_due"] == 3 and out["emi"][0]["instalments_left"] > 0
    text = out["share_text"]
    for piece in ("₹6,000", "₹6,500", "₹4,200", "30%", "Talk to your lender", "not financial advice"):
        assert piece in text, piece
    assert out["stored"] is False and out["steps_are_rules"] and out["not_advice"]


def test_a_quiet_shop_gets_no_urgent_step(client, consented, db_factory):
    sid = make_shop(client, consented, db_factory, sales=3000, purchases=2000, expenses=300)
    out = sos(client, consented, sid, "en")
    assert [s["key"] for s in out["steps"]] == ["no_urgent", "share", "official"]
    assert "No loan recorded." in out["share_text"] and out["alerts"] == []


def test_few_logged_days_are_flagged(client, consented, db_factory):
    sid = make_shop(client, consented, db_factory, sales=3000, purchases=2000, expenses=300, days=10)
    keys = [s["key"] for s in sos(client, consented, sid, "en")["steps"]]
    assert "few_logs" in keys and "no_urgent" not in keys


def test_languages_default_to_the_profile(client, consented, db_factory):
    sid = make_shop(client, consented, db_factory, sales=2000, purchases=1800, expenses=400, loan=True)
    hi = sos(client, consented, sid)                                     # profile language is Hindi by default
    assert hi["language"] == "hi" and "अब क्या करें" in hi["share_text"] and "₹" in hi["share_text"]
    assert "Ab kya karein" in sos(client, consented, sid, "hinglish")["share_text"]
    client.put("/api/me", headers=consented, json={"language": "en"})
    assert sos(client, consented, sid)["language"] == "en"


def test_nothing_is_stored_and_no_phone_in_the_text(client, consented, db_factory):
    sid = make_shop(client, consented, db_factory, sales=2000, purchases=1800, expenses=400, loan=True)
    uid = client.get("/api/me", headers=consented).json()["id"]
    with db_factory() as db:
        before = privacy.owned_counts(db, uid)
    out = sos(client, consented, sid, "en")
    with db_factory() as db:
        assert privacy.owned_counts(db, uid) == before
        assert db.scalar(select(func.count()).select_from(Alert)) == 0
    assert "9800000001" not in out["share_text"] and "+91" not in out["share_text"]


def test_owner_only_needs_consent_and_login(client, consented, db_factory):
    sid = make_shop(client, consented, db_factory, sales=1, purchases=0, expenses=0, days=1)
    other = login(client, "+919800000099")
    client.post("/api/consents", headers=other, json={"purpose": "shop_data"})
    r = client.post("/api/sos", headers=other, json={"shop_id": sid})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "shop_not_found"
    assert client.post("/api/sos", json={"shop_id": sid}).status_code == 401
    client.delete("/api/consents", params={"purpose": "shop_data"}, headers=consented)
    assert client.post("/api/sos", headers=consented, json={"shop_id": sid}).status_code == 403
    assert client.post("/api/sos", headers=other, json={"shop_id": sid, "language": "fr"}).status_code == 422
