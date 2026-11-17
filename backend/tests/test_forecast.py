"""M-05: set-up forecast service and endpoint. Arithmetic is checked against hand-calculated cases."""
from datetime import date

import numpy as np
import pytest
import yaml

from app.api.forecast import forecast_model
from app.config import REPO_ROOT
from app.main import app
from app.ml import forecast as fc
from app.models import Forecast
from app.rules import get_rules
from tests.conftest import SHOP, login

COUNTS = {"homes": 180, "schools": 2, "transit": 5, "banks_atms": 2, "competitors": 3}
PROFILE = {"size_sqft": 220.0, "city_tier": 2, "monthly_rent": 9000.0, "staff_count": 1, "budget": 300000.0}
STATS = {f: {"min": 0, "median": 1, "max": 1e9} for f in fc.RANGE_CHECKED}


# ---- arithmetic, by hand ----
def test_gross_margin_assumption_matches_the_synthetic_config():
    cfg = yaml.safe_load((REPO_ROOT / "data/synthetic/config.yaml").read_text(encoding="utf-8"))
    blended = sum(cfg["category_mix"]["base"][c] * sum(cfg["margins"][c]) / 2 for c in cfg["categories"])
    a = get_rules().forecast
    assert blended == pytest.approx(0.12815) and a.gross_margin == pytest.approx(blended, abs=0.0005)
    assert a.staff_wage_monthly == sum(cfg["staff"]["monthly_wage"]) / 2 and a.other_fixed_costs_monthly == 0


def test_payback_by_hand():
    op = np.array([-5000, 0, 5000, 10000, 10000, 10000, 20000, 20000, 20000, 20000, 20000, 20000], dtype=float)
    assert op.sum() == 150000 and op[6:].mean() == 20000
    assert fc.payback_month(op, 30000, 7, 60) == 6           # cumulative 30,000 at the end of month 6
    assert fc.payback_month(op, 150000, 7, 60) == 12
    assert fc.payback_month(op, 150001, 7, 60) == 13         # month 13 earns the months 7-12 mean
    assert fc.payback_month(op, 300000, 7, 60) == 20         # 150,000 + 8 x 20,000 = 310,000 (7 months is short)
    assert fc.payback_month(op, 150000 + 48 * 20000, 7, 60) == 60
    assert fc.payback_month(op, 150000 + 48 * 20000 + 1, 7, 60) is None
    assert fc.payback_month(-np.ones(12), 1, 7, 60) is None  # never profitable


def test_investment_split_by_hand():
    rule = get_rules().investment          # deposit 3 x rent, reserve 3 x fixed costs, remainder 65 / 35
    s = fc.investment_split(300000, 9000, 19000, rule)
    assert (s["deposit"], s["cash_reserve"], s["stock"], s["fixtures"]) == (27000, 57000, 140400, 75600)
    assert s["deposit"] + s["cash_reserve"] + s["stock"] + s["fixtures"] == 300000
    assert s["budget_too_low"] is False and s["shortfall"] == 0 and s["is_assumption"] is True
    low = fc.investment_split(80000, 9000, 19000, rule)
    assert low["budget_too_low"] is True and low["shortfall"] == 4000 and low["stock"] is None and low["fixtures"] is None
    edge = fc.investment_split(84000, 9000, 19000, rule)
    assert edge["budget_too_low"] is False and edge["stock"] == 0 and edge["fixtures"] == 0


def test_open_date_sources():
    today = date(2026, 11, 16)
    assert fc.resolve_open_date(date(2027, 1, 5), date(2026, 8, 1), today) == (date(2027, 1, 5), "request")
    assert fc.resolve_open_date(None, date(2026, 8, 1), today) == (date(2026, 8, 1), "shop")
    assert fc.resolve_open_date(None, None, today) == (date(2026, 12, 1), "assumed_next_month")
    assert fc.next_month_start(date(2026, 12, 31)) == date(2027, 1, 1)


def test_confidence_is_never_above_medium_and_low_has_reasons():
    prof = {**PROFILE, **COUNTS}
    assert fc.confidence("live", prof, STATS)["level"] == "medium"
    assert fc.confidence("cache", prof, STATS)["reasons"] == [{"key": "confidence.synthetic_training", "params": {}}]
    for src in ("mock", "fallback_assumed"):
        c = fc.confidence(src, prof, STATS)
        assert c["level"] == "low" and c["reasons"][1]["key"] == f"confidence.location_{src}"
    tight = {**STATS, "size_sqft": {"min": 100, "median": 245, "max": 400}, "homes": {"min": 20, "median": 89, "max": 100}}
    c = fc.confidence("live", {**prof, "size_sqft": 900.0}, tight)
    assert c["level"] == "low"
    assert c["reasons"][1] == {"key": "confidence.outside_training_range", "params": {"features": ["size_sqft", "homes"]}}


# ---- with a small trained model ----
def run(model_small, **over):
    model, card = model_small
    kw = {"shop": PROFILE, "counts": COUNTS, "location_source": "live", "open_date": date(2026, 12, 1)}
    kw.update(over)
    r = get_rules()
    return fc.setup_forecast(model=model, card=card, assumptions=r.forecast, split_rule=r.investment, **kw)


def test_twelve_ordered_months_and_derived_numbers_agree(model_small):
    out = run(model_small)
    months = out["months"]
    assert [m["k"] for m in months] == list(range(1, 13))
    assert months[0]["start"] == date(2026, 12, 1) and months[0]["end"] == date(2026, 12, 31)
    assert months[2]["start"] == date(2027, 2, 1) and months[2]["end"] == date(2027, 2, 28)
    assert months[11]["end"] == date(2027, 11, 30)
    fixed = 9000 + 1 * 10000
    assert out["fixed_costs_monthly"] == fixed and out["break_even"]["revenue_monthly"] == round(fixed / 0.128)
    for m in months:
        assert 0 < m["p10"] <= m["p50"] <= m["p90"]
        for p in ("p10", "p50", "p90"):
            assert m["gross_profit"][p] == pytest.approx(m[p] * 0.128, abs=1)
            assert m["operating_profit"][p] == pytest.approx(m[p] * 0.128 - fixed, abs=1)
    reached = out["break_even"]["first_month_p50_reaches"]
    assert reached is None or (months[reached - 1]["p50"] >= fixed / 0.128
                               and all(m["p50"] < fixed / 0.128 for m in months[:reached - 1]))
    assert out["is_estimate"] is True and out["trained_on_synthetic"] is True and "synthetic" in out["notice"]
    assert out["assumptions"]["is_assumption"] is True and out["payback"]["is_assumption"] is True


def test_payback_range_is_ordered(model_small):
    pay = run(model_small, shop={**PROFILE, "budget": 60000.0})["payback"]
    fast, typical, slow = (pay[k] if pay[k] is not None else 10**6 for k in ("fastest_months", "typical_months", "slowest_months"))
    assert fast <= typical <= slow and pay["max_months"] == 60 and pay["investment"] == 60000
    assert pay["extended_beyond_forecast"] == any(v > 12 for v in (fast, typical, slow))


def test_drivers_are_at_most_three_from_the_allowed_inputs(model_small):
    out = run(model_small)
    assert 1 <= len(out["drivers"]) <= 3
    for d in out["drivers"]:
        assert d["feature"] in get_rules().forecast.driver_features and d["feature"] not in ("monthly_rent", "staff_count")
        assert d["direction"] in ("up", "down") and d["message_key"] == f"driver.{d['feature']}.{d['direction']}"
        assert (d["effect_inr_per_month"] > 0) == (d["direction"] == "up") and d["text"]
    sizes = [abs(d["effect_inr_per_month"]) for d in out["drivers"]]
    assert sizes == sorted(sizes, reverse=True)


def test_more_competitors_never_raise_and_more_homes_never_lower_the_forecast(model_small):
    def p50(counts):
        return [m["p50"] for m in run(model_small, counts=counts)["months"]]
    base = p50(COUNTS)
    assert all(a >= b for a, b in zip(base, p50({**COUNTS, "competitors": 9}), strict=True))
    assert all(a <= b for a, b in zip(base, p50({**COUNTS, "homes": 350}), strict=True))


def test_opening_month_changes_the_calendar(model_small):
    assert run(model_small)["months"] != run(model_small, open_date=date(2027, 4, 1))["months"]


# ---- endpoint ----
def test_endpoint_returns_the_full_forecast_and_stores_it(client, consented, with_model, db_factory):
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    r = client.post(f"/api/shops/{shop_id}/forecast", headers=consented)
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out["months"]) == 12 and all(m["p10"] <= m["p50"] <= m["p90"] for m in out["months"])
    assert out["break_even"]["revenue_monthly"] > 0 and {"fastest_months", "typical_months", "slowest_months"} <= set(out["payback"])
    assert out["drivers"] and out["investment_split"]["budget"] == 300000
    assert out["open_date_source"] == "assumed_next_month" and out["kind"] == "setup" and out["shop_id"] == shop_id
    # default OSM mode is mock: labelled, not measured, confidence low with the reason
    assert out["location"]["source"] == "mock" and out["location"]["is_measured"] is False
    assert out["confidence"]["level"] == "low"
    assert "confidence.location_mock" in [x["key"] for x in out["confidence"]["reasons"]]
    with db_factory() as db:
        row = db.get(Forecast, out["forecast_id"])
        assert row.shop_id == shop_id and row.kind == "setup" and len(row.horizon_months) == 12
        assert row.horizon_months[0]["p50"] == out["months"][0]["p50"] and row.drivers == out["drivers"]


def test_endpoint_open_date_from_request_and_from_shop(client, consented, with_model):
    a = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    r = client.post(f"/api/shops/{a}/forecast", headers=consented, json={"open_date": "2027-03-10"}).json()
    assert r["open_date"] == "2027-03-10" and r["open_date_source"] == "request" and r["months"][0]["end"] == "2027-04-09"
    b = client.post("/api/shops", headers=consented, json={**SHOP, "launch_date": "2026-08-01"}).json()["id"]
    r = client.post(f"/api/shops/{b}/forecast", headers=consented, json={}).json()
    assert r["open_date"] == "2026-08-01" and r["open_date_source"] == "shop"


def test_endpoint_flags_inputs_outside_the_training_range_and_low_budget(client, consented, with_model):
    big = client.post("/api/shops", headers=consented, json={**SHOP, "size_sqft": 3000, "budget": 20000}).json()["id"]
    out = client.post(f"/api/shops/{big}/forecast", headers=consented).json()
    outside = [x for x in out["confidence"]["reasons"] if x["key"] == "confidence.outside_training_range"]
    assert outside and "size_sqft" in outside[0]["params"]["features"]
    assert out["investment_split"]["budget_too_low"] is True and out["investment_split"]["stock"] is None


def test_endpoint_needs_login_consent_and_ownership(client, consented, with_model):
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    assert client.post(f"/api/shops/{shop_id}/forecast").status_code == 401
    other = login(client, "+919800000002")
    assert client.post(f"/api/shops/{shop_id}/forecast", headers=other).status_code == 403      # no consent yet
    client.post("/api/consents", headers=other, json={"purpose": "shop_data"})
    assert client.post(f"/api/shops/{shop_id}/forecast", headers=other).status_code == 404      # not their shop
    client.delete("/api/consents", headers=consented, params={"purpose": "shop_data"})
    r = client.post(f"/api/shops/{shop_id}/forecast", headers=consented)
    assert r.status_code == 403 and r.json()["error"]["code"] == "consent_required"            # withdrawn: no computing


def test_endpoint_says_503_when_the_model_is_missing(client, consented, monkeypatch, tmp_path):
    app.dependency_overrides.pop(forecast_model, None)
    real_load = fc.load_model.__wrapped__                    # the uncached loader, pointed at an empty folder
    monkeypatch.setattr(fc, "load_model", lambda: real_load(tmp_path))
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    r = client.post(f"/api/shops/{shop_id}/forecast", headers=consented)
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_not_ready"
