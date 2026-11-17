"""M-08 review engine: the 20 hand-labelled scenarios, the pure helpers, and the endpoints."""
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from app.ml import review as engine
from app.models import DailyLog, Forecast, Loan
from app.rules import get_rules
from app.services import clock
from app.services import review as review_service
from tests.conftest import SHOP, login

END = date(2026, 9, 30)
START = END - timedelta(days=89)
SCENARIOS = yaml.safe_load((Path(__file__).parent / "review_scenarios.yaml").read_text(encoding="utf-8"))


def build_logs(sc: dict, start: date = START) -> dict[date, dict]:
    """Scenario blocks -> {day: {sales, purchases, expenses}} (see the header of review_scenarios.yaml)."""
    logs, step = {}, 2 if sc.get("pattern") == "alternate" else 1
    for b, block in enumerate(sc["blocks"]):
        for i in range(block["logged"]):
            day = start + timedelta(days=30 * b + i * step)
            logs[day] = {"sales": float(block["sales"]), "purchases": float(block["purchases"]),
                         "expenses": float(block["expenses"]) if i == 0 else 0.0}
    return logs


def run_scenario(sc: dict) -> dict:
    rules = get_rules()
    months = None if sc["p50_per_day"] is None else [{"start": START, "end": END, "p50": sc["p50_per_day"] * 90}]
    return engine.review(period_end=END, rule=rules.review, actions=rules.actions, logs=build_logs(sc),
                         forecast_months=months, monthly_emi=sc["emi"], cash=sc["cash"])


def test_there_are_20_scenarios_and_each_gives_a_decision():
    assert len(SCENARIOS) == 20
    assert len({s["name"] for s in SCENARIOS}) == 20
    assert all(s["expect"]["decision"] in ("grow", "hold", "pivot") and s["why"].strip() for s in SCENARIOS)
    assert {s["expect"]["decision"] for s in SCENARIOS} == {"grow", "hold", "pivot"}


@pytest.mark.parametrize("sc", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_scenario(sc):
    out, exp = run_scenario(sc), sc["expect"]
    assert out["decision"] == exp["decision"], out["indicators"]
    if "reasons" in exp:
        assert [r["indicator"] for r in out["reasons"]] == exp["reasons"]
    if "actions" in exp:
        assert [a["id"] for a in out["actions"]] == exp["actions"]
    if "confidence" in exp:
        assert out["confidence"] == exp["confidence"]
    for note in exp.get("notes", []):
        assert note in out["notes"]
    for key, want in exp.get("indicators", {}).items():
        got = out["indicators"][key]
        assert got == (None if want is None else pytest.approx(want, abs=1e-4)), key
    if "dscr_by_month" in exp:
        assert out["indicators"]["dscr_by_month"] == pytest.approx(exp["dscr_by_month"], abs=1e-4)
    assert len(out["reasons"]) <= 3 and len(out["actions"]) <= 3
    assert out["confidence"] in ("low", "medium") and out["is_estimate"] is True
    assert out["data_completeness"] == out["indicators"]["data_completeness"]


def test_pivot_reasons_hold_and_hold_reasons_do_not():
    by_name = {s["name"]: run_scenario(s) for s in SCENARIOS}
    assert all(r["holds"] for r in by_name["emi_not_covered_in_the_last_two_months"]["reasons"])
    r = by_name["emi_not_covered_in_the_last_two_months"]["reasons"][0]
    assert r["for_months"] == 2 and r["values_by_month"] == [0.8, 0.9] and r["threshold"] == 1.0
    assert not any(r["holds"] for r in by_name["flat_sales_growth_exactly_zero"]["reasons"])


def test_days_before_launch_are_not_expected():
    """A shop opened 30 days before the period end: 30 expected days, older blocks have no values."""
    rules = get_rules()
    launch = END - timedelta(days=29)
    logs = {launch + timedelta(days=i): {"sales": 1000.0, "purchases": 850.0, "expenses": 0.0} for i in range(30)}
    out = engine.review(period_end=END, rule=rules.review, actions=rules.actions, logs=logs,
                        forecast_months=[{"start": START, "end": END, "p50": 90000}], monthly_emi=None, cash=None,
                        launch_date=launch)
    ind = out["indicators"]
    assert ind["days_expected"] == 30 and ind["data_completeness"] == 1.0 and out["period_start"] == launch
    assert ind["growth_rate"] is None and out["decision"] == "hold"            # one block: no trend yet
    assert "no_expenses_logged_profit_overstated" in out["notes"]


def test_thin_block_has_no_values():
    """Fewer than min_block_logged_days (7) logged days in a block: its dscr is unknown, so no '2 months' pivot."""
    sc = {"blocks": [{"logged": 30, "sales": 1000, "purchases": 800, "expenses": 2000},
                     {"logged": 30, "sales": 1000, "purchases": 800, "expenses": 2000},
                     {"logged": 6, "sales": 1000, "purchases": 800, "expenses": 2000}],
          "p50_per_day": 1000, "emi": 5000, "cash": None}
    out = run_scenario(sc)
    assert out["indicators"]["dscr_by_month"] == [0.8, 0.8, None]
    assert out["decision"] == "hold"


def test_stock_indicators_pick_actions():
    rules = get_rules()
    sc = next(s for s in SCENARIOS if s["name"] == "flat_sales_growth_exactly_zero")
    out = engine.review(period_end=END, rule=rules.review, actions=rules.actions, logs=build_logs(sc),
                        forecast_months=[{"start": START, "end": END, "p50": 90000}], monthly_emi=1000, cash=None,
                        stockout_days=5, dead_stock_value=1200.0)
    assert [a["id"] for a in out["actions"]] == ["reduce_slow_stock", "restock_fast_movers", "extend_hours"]


def test_cash_position_and_loan_figures():
    logs = {date(2026, 7, 1): {"sales": 1000.0, "purchases": 600.0, "expenses": 100.0}}
    assert review_service.cash_position(None, logs, 0.0) is None
    assert review_service.cash_position(5000.0, logs, 2000.0) == 3300.0
    dated = Loan(principal=100000, emi=5000, due_day=5, start_date=date(2026, 6, 10), tenure_months=12)
    undated = Loan(principal=50000, emi=2000, due_day=5, start_date=None, tenure_months=None)
    n_due = sum(d <= END for d in review_service.loan_dates.schedule(date(2026, 6, 10), 5, 12))
    assert review_service.loan_figures([dated], START, END) == (5000.0, 5000.0 * n_due, False)
    assert review_service.loan_figures([dated, undated], START, END) == (7000.0, 5000.0 * n_due, True)
    assert review_service.loan_figures([], START, END) == (None, 0.0, False)
    finished = Loan(principal=1000, emi=500, due_day=5, start_date=date(2025, 1, 1), tenure_months=3)
    assert review_service.loan_figures([finished], START, END) == (None, 1500.0, False)


# ---- endpoints ----
def _seed(db_factory, shop_id: int, sales: float, p50_per_day: float) -> date:
    """90 logged days ending yesterday, plus a set-up forecast row covering them."""
    end = clock.today() - timedelta(days=1)
    start = end - timedelta(days=89)
    with db_factory() as s:
        for i in range(90):
            s.add(DailyLog(shop_id=shop_id, day=start + timedelta(days=i), category="all", sales=sales,
                           purchases=sales * 0.85, expenses=2000.0 if i % 30 == 0 else 0.0))
        s.add(Forecast(shop_id=shop_id, kind="setup", made_on=start, horizon_months=[
            {"k": 1, "start": start.isoformat(), "end": end.isoformat(), "p10": 0, "p50": p50_per_day * 90, "p90": 0}]))
        s.commit()
    return end


def test_run_persists_and_latest_returns_it(client, consented, db_factory):
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    assert client.get(f"/api/shops/{shop_id}/reviews/latest", headers=consented).json()["error"]["code"] == "review_missing"
    end = _seed(db_factory, shop_id, sales=500.0, p50_per_day=1000.0)

    r = client.post(f"/api/shops/{shop_id}/reviews/run", headers=consented)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "pivot" and body["period_end"] == end.isoformat()
    assert [x["indicator"] for x in body["reasons"]] == ["revenue_vs_p50"]
    assert body["indicators"]["revenue_vs_p50"] == 0.5 and body["data_completeness"] == 1.0
    assert body["confidence"] == "medium" and body["is_estimate"] and body["thresholds_are_assumptions"]
    assert {"no_loan_dscr_not_applicable", "cash_unknown_runway_rule_skipped", "no_stock_records"} <= set(body["notes"])

    latest = client.get(f"/api/shops/{shop_id}/reviews/latest", headers=consented)
    assert latest.status_code == 200 and latest.json() == body
    # running again for the same period replaces the row instead of adding one
    assert client.post(f"/api/shops/{shop_id}/reviews/run", headers=consented).json()["id"] == body["id"]
    assert len(client.get(f"/api/shops/{shop_id}/reviews", headers=consented).json()) == 1


def test_opening_cash_enables_the_runway_rule(client, consented, db_factory):
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    assert client.get(f"/api/shops/{shop_id}", headers=consented).json()["opening_cash"] is None
    _seed(db_factory, shop_id, sales=1000.0, p50_per_day=1000.0)
    loan = {"principal": 200000, "emi": 9000, "due_day": 5, "tenure_months": 24,
            "start_date": (clock.today() - timedelta(days=200)).isoformat()}
    assert client.post(f"/api/shops/{shop_id}/loans", headers=consented, json=loan).status_code == 201

    # profit 150 x 30 - 2000 = 2500 a month against an EMI of 9000: dscr 0.2778 in every block -> pivot
    first = client.post(f"/api/shops/{shop_id}/reviews/run", headers=consented).json()
    assert first["decision"] == "pivot" and first["indicators"]["cash_runway_days"] is None
    assert [x["indicator"] for x in first["reasons"]] == ["dscr"]

    r = client.patch(f"/api/shops/{shop_id}", headers=consented, json={"opening_cash": 60000})
    assert r.status_code == 200 and r.json()["opening_cash"] == 60000
    second = client.post(f"/api/shops/{shop_id}/reviews/run", headers=consented).json()
    ind = second["indicators"]
    # cash = 60000 + 90 x 150 - 6000 - EMIs due so far; net flow = (2500 - 9000) / 30 a day
    start, end = clock.today() - timedelta(days=200), clock.today() - timedelta(days=1)
    n_due = sum(d <= end for d in review_service.loan_dates.schedule(start, 5, 24))
    assert n_due in (6, 7) and ind["cash"] == pytest.approx(60000 + 13500 - 6000 - 9000 * n_due)
    assert ind["net_cash_flow_per_day"] == pytest.approx(-216.67)
    assert ind["cash_runway_days"] == pytest.approx(max(ind["cash"], 0) / 216.6667, abs=0.1)
    assert "cash_unknown_runway_rule_skipped" not in second["notes"]
    assert client.patch(f"/api/shops/{shop_id}", headers=consented, json={"opening_cash": -5}).status_code == 422
    assert client.patch(f"/api/shops/{shop_id}", headers=consented, json={"name": "x"}).status_code == 422


def test_review_needs_consent_and_ownership(client, consented, db_factory):
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    other = login(client, "+919800000002")
    assert client.post(f"/api/shops/{shop_id}/reviews/run", headers=other).status_code in (403, 404)
    assert client.get(f"/api/shops/{shop_id}/reviews/latest", headers=other).status_code in (403, 404)
    assert client.post(f"/api/shops/{shop_id}/reviews/run").status_code == 401


def test_review_with_no_logs_is_hold_low_confidence(client, consented):
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    body = client.post(f"/api/shops/{shop_id}/reviews/run", headers=consented).json()
    assert body["decision"] == "hold" and body["confidence"] == "low" and body["data_completeness"] == 0.0
    assert [a["id"] for a in body["actions"]] == ["log_daily"]
