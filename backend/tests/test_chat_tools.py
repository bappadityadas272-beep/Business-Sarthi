"""C-04: chat tools return valid JSON with units and a source for both demo shops; ownership is enforced."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import seed as sd
from app.llm import tools
from app.models import DailyLog, Shop
from app.services import clock, consent

RAMESH, SUNITA = "+919000000001", "+919000000002"
UNITS = {"INR", "percent", "ratio", "days", "count", "units", "date", "label"}


@pytest.fixture
def demo(client, db_factory, synth_small, model_small):
    with db_factory() as db:
        out = sd.seed(db, clock.today(), demo_dir=synth_small / "demo", model=model_small)
        shops = {s["phone"]: db.get(Shop, s["shop_id"]) for s in out["shops"]}
        return {p: (s.user_id, s.id) for p, s in shops.items()}


def check(out: dict, name: str):
    text = json.dumps(out, allow_nan=False)            # strict: no dates, NaN or objects left inside
    assert json.loads(text) == out
    assert out["tool"] == name and out["source"]["id"] in tools.SOURCES and out["source"]["label"]
    for f in out["facts"]:
        assert set(f) >= {"key", "value", "unit", "period"} and f["unit"] in UNITS and f["value"] is not None
        if f["unit"] not in {"date", "label"}:
            assert isinstance(f["value"], int | float) and not isinstance(f["value"], bool), f


@pytest.mark.parametrize("phone", [RAMESH, SUNITA])
def test_every_tool_gives_valid_json_with_units_and_source_for_both_demo_shops(demo, db_factory, phone):
    """The acceptance line of C-04."""
    uid, sid = demo[phone]
    with db_factory() as db:
        for name in tools.TOOLS:
            check(tools.run(db, uid, sid, name), name)
        for period in tools.PERIODS:
            check(tools.run(db, uid, sid, "get_profit_summary", period=period), "get_profit_summary")


def test_values_match_the_stored_data(demo, db_factory):
    uid, sid = demo[RAMESH]
    today = clock.today()
    with db_factory() as db:
        fc = tools.run(db, uid, sid, "get_forecast")
        assert fc["is_estimate"] is True and len(fc["data"]["months"]) == 12
        assert all(m["p10"] <= m["p50"] <= m["p90"] for m in fc["data"]["months"])

        p = tools.run(db, uid, sid, "get_profit_summary", period="last_30_days")
        first, last = today - timedelta(days=30), today - timedelta(days=1)
        s, pu, e = db.execute(select(func.sum(DailyLog.sales), func.sum(DailyLog.purchases),
                                     func.sum(DailyLog.expenses)).where(
            DailyLog.shop_id == sid, DailyLog.day >= first, DailyLog.day <= last)).one()
        assert p["data"]["operating_profit"] == pytest.approx(s - pu - e, abs=0.01)
        assert p["data"]["emi_subtracted"] is False and p["data"]["monthly_emi"] > 0
        assert {f["key"] for f in p["facts"]} >= {"sales", "operating_profit", "monthly_emi"}

        al = tools.run(db, uid, sid, "get_alerts")
        kinds = {a["kind"] for a in al["data"]["alerts"]}
        assert {"low_stock", "dead_stock", "emi_due", "sales_dip"} <= kinds
        assert any(f["key"] == "alert.sales_dip.drop_percent" and f["unit"] == "percent" for f in al["facts"])

        st = tools.run(db, uid, sid, "get_stock_advice")
        assert st["data"]["dead_stock"] and st["data"]["dead_stock_value"] > 0


def test_review_tool_before_and_after_the_first_review(demo, db_factory, client):
    from tests.conftest import login
    uid, sid = demo[RAMESH]
    with db_factory() as db:
        assert tools.run(db, uid, sid, "get_latest_review")["note"] == "no_review_yet"
    client.post("/api/dev/advance-time", headers=login(client, RAMESH), json={"days": 2})
    with db_factory() as db:
        r = tools.run(db, uid, sid, "get_latest_review")
        check(r, "get_latest_review")
        assert r["data"]["decision"] == "pivot" and {"key": "decision", "value": "pivot"}.items() <= r["facts"][0].items()


def test_match_schemes_returns_nothing_without_a_verified_source(demo, db_factory):
    uid, sid = demo[SUNITA]
    with db_factory() as db:
        out = tools.run(db, uid, sid, "match_schemes", profile={"shop_type": "kirana"})
    assert out["data"]["schemes"] == [] and out["note"] == "no_verified_source" and out["facts"] == []


def test_a_user_cannot_read_another_users_shop(demo, db_factory):
    """The acceptance line of C-04 (ownership)."""
    r_uid, r_sid = demo[RAMESH]
    s_uid, s_sid = demo[SUNITA]
    with db_factory() as db:
        for name in tools.TOOLS:
            with pytest.raises(tools.ToolAccessDenied, match="shop_not_found"):
                tools.run(db, s_uid, r_sid, name)
            with pytest.raises(tools.ToolAccessDenied, match="shop_not_found"):
                tools.run(db, r_uid, s_sid, name)
            with pytest.raises(tools.ToolAccessDenied, match="shop_not_found"):
                tools.run(db, r_uid, 99999, name)
        with pytest.raises(tools.UnknownTool):
            tools.run(db, r_uid, r_sid, "drop_tables")


def test_no_tool_runs_after_consent_is_withdrawn(demo, db_factory):
    uid, sid = demo[RAMESH]
    with db_factory() as db:
        consent.withdraw(db, uid, consent.SHOP_DATA)
        with pytest.raises(tools.ToolAccessDenied):
            tools.run(db, uid, sid, "get_profit_summary")


def test_period_bounds():
    from datetime import date
    t = date(2026, 11, 17)
    assert tools.period_bounds("this_month", t) == (date(2026, 11, 1), date(2026, 11, 16))
    assert tools.period_bounds("last_month", t) == (date(2026, 10, 1), date(2026, 10, 31))
    assert tools.period_bounds("last_30_days", t) == (date(2026, 10, 18), date(2026, 11, 16))
    first, last = tools.period_bounds("this_month", date(2026, 12, 1))
    assert last < first                                   # the 1st: empty period, the tool says so
