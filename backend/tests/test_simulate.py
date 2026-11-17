"""M-10 expansion simulator (ML9, DEC-88). Ranges are the assumption ranges of data/rules/expansion.yaml."""
from datetime import date, timedelta

import numpy as np
import pytest

from app.api.simulate import pick_margin
from app.ml import simulate as ml9
from app.models import DailyLog, Forecast
from app.rules import get_rules
from app.services import clock
from tests.conftest import SHOP, login

EX = get_rules().expansion
BAND = {"p10": 240000.0, "p50": 300000.0, "p90": 380000.0}


def months(start: date, n: int = 12, p50: float = 300000.0) -> list[dict]:
    out, s = [], start
    for k in range(n):
        e = s + timedelta(days=29)
        out.append({"k": k, "start": s, "end": e, "p10": p50 * 0.8, "p50": p50, "p90": p50 * 1.25})
        s = e + timedelta(days=1)
    return out


def test_band_uses_the_next_months_per_30_days():
    m = months(date(2026, 9, 1))
    band, ahead = ml9.monthly_band(m, date(2026, 10, 15), 3)
    assert [x["k"] for x in ahead] == [1, 2, 3]                 # month 1 has not ended on Oct 15
    assert band == pytest.approx({"p10": 240000, "p50": 300000, "p90": 375000})
    with pytest.raises(ValueError):
        ml9.monthly_band(m, date(2030, 1, 1), 3)


def test_revenue_draws_follow_the_band():
    r = ml9.draw_revenue(BAND, np.random.default_rng(0), 200_000)
    assert np.percentile(r, 10) == pytest.approx(240000, rel=0.01)
    assert np.percentile(r, 50) == pytest.approx(300000, rel=0.01)
    assert np.percentile(r, 90) == pytest.approx(380000, rel=0.01)
    assert (ml9.draw_revenue({"p10": 0, "p50": 10, "p90": 20}, np.random.default_rng(0), 1000) >= 0).all()


def test_three_options_with_payback_range_and_probability():
    out = ml9.simulate(BAND, 0.128, EX, seed=1, horizon_months=60)
    assert [o["option"] for o in out] == list(EX.options) and len(out) == 3
    for o in out:
        pb = o["payback_months"]
        assert set(pb) == {"p10", "p50", "p90"} and 0 <= o["p_payback_under_target"] <= 1
        assert o["payback_target_months"] == EX.payback_target_months and o["assumptions"]["assumption"] is True
        e = o["extra_revenue_month"]
        assert e["p10"] <= e["p50"] <= e["p90"]
        if pb["p10"] is not None and pb["p90"] is not None:
            assert pb["p10"] <= pb["p50"] <= pb["p90"]


def test_hand_check_of_one_option():
    """add_product_line at a fixed base: payback = cost / (base x uplift x margin), within the assumed extremes."""
    band = {"p10": 300000.0, "p50": 300000.0, "p90": 300000.0}
    o = next(x for x in ml9.simulate(band, 0.10, EX, seed=3, horizon_months=60) if x["option"] == "add_product_line")
    a = EX.options["add_product_line"]
    fastest = a.one_time_cost.low / (300000 * a.uplift.high * 0.10)
    slowest = a.one_time_cost.high / (300000 * a.uplift.low * 0.10)
    assert fastest <= o["payback_months"]["p10"] <= o["payback_months"]["p90"] <= slowest
    assert o["share_no_payback"] == 0 and o["no_upfront_cost"] is False


def test_same_seed_same_answer_and_more_margin_pays_back_sooner():
    a = ml9.simulate(BAND, 0.128, EX, seed=7, horizon_months=60)
    assert a == ml9.simulate(BAND, 0.128, EX, seed=7, horizon_months=60)
    hi = ml9.simulate(BAND, 0.25, EX, seed=7, horizon_months=60)
    for lo_o, hi_o in zip(a, hi, strict=True):
        assert hi_o["p_payback_under_target"] >= lo_o["p_payback_under_target"]


def test_no_payback_when_costs_eat_the_extra_profit():
    tiny = {"p10": 5000.0, "p50": 6000.0, "p90": 7000.0}
    out = {o["option"]: o for o in ml9.simulate(tiny, 0.10, EX, seed=1, horizon_months=60)}
    sc = out["second_counter"]
    assert sc["share_no_payback"] == 1 and sc["p_payback_under_target"] == 0
    assert sc["payback_months"] == {"p10": None, "p50": None, "p90": None}
    eh = out["extend_hours"]                                    # no one-time cost in the rules
    assert eh["no_upfront_cost"] is True


def test_unknown_option():
    with pytest.raises(KeyError):
        ml9.simulate(BAND, 0.1, EX, seed=1, horizon_months=60, options=["open_a_mall"])


def test_margin_choice_dec_88():
    r = get_rules()
    assert pick_margin(0.15, 45, r) == {"value": 0.15, "source": "own_logs", "reason": None, "logged_days": 45,
                                        "window_days": EX.margin_window_days}
    few = pick_margin(0.15, EX.margin_min_logged_days - 1, r)
    assert few["source"] == "assumed" and few["value"] == r.forecast.gross_margin and few["reason"] == "few_logged_days"
    assert pick_margin(-0.2, 60, r)["reason"] == "own_margin_out_of_range"
    assert pick_margin(None, 60, r)["source"] == "assumed"


# ---- endpoint ----
def make_shop(client, headers, with_forecast=True) -> int:
    shop_id = client.post("/api/shops", headers=headers, json=SHOP).json()["id"]
    if with_forecast:
        assert client.post(f"/api/shops/{shop_id}/forecast", headers=headers).status_code == 200
    return shop_id


def test_endpoint_three_options_assumed_margin(client, consented, with_model):
    shop_id = make_shop(client, consented)
    r = client.post(f"/api/shops/{shop_id}/simulate", headers=consented)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["is_estimate"] and out["assumption"] and len(out["options"]) == 3
    assert out["margin"]["source"] == "assumed" and out["margin"]["reason"] == "few_logged_days"
    assert {"simulate.assumed_ranges", "simulate.not_a_promise", "simulate.assumed_margin",
            "simulate.no_upfront_cost"} <= set(out["notes"])
    assert out["base"]["forecast_kind"] == "setup" and len(out["base"]["months_used"]) == EX.months_ahead
    b = out["base"]["monthly_revenue"]
    assert b["p10"] <= b["p50"] <= b["p90"]
    assert r.json() == client.post(f"/api/shops/{shop_id}/simulate", headers=consented).json()   # reproducible
    one = client.post(f"/api/shops/{shop_id}/simulate", headers=consented, json={"options": ["extend_hours"]}).json()
    assert [o["option"] for o in one["options"]] == ["extend_hours"]
    bad = client.post(f"/api/shops/{shop_id}/simulate", headers=consented, json={"options": ["open_a_mall"]})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_option"


def test_endpoint_uses_the_shops_own_margin(client, consented, with_model, db_factory):
    shop_id = make_shop(client, consented)
    today = clock.today()
    with db_factory() as db:
        for i in range(1, 41):
            db.add(DailyLog(shop_id=shop_id, day=today - timedelta(days=i), category="staples", sales=10000.0,
                            purchases=8500.0, expenses=0.0))
        db.commit()
    m = client.post(f"/api/shops/{shop_id}/simulate", headers=consented).json()["margin"]
    assert m == {"value": 0.15, "source": "own_logs", "reason": None, "logged_days": 40,
                 "window_days": EX.margin_window_days}


def test_endpoint_needs_a_forecast_ahead(client, consented, with_model, db_factory):
    shop_id = make_shop(client, consented, with_forecast=False)
    r = client.post(f"/api/shops/{shop_id}/simulate", headers=consented)
    assert r.status_code == 409 and r.json()["error"]["code"] == "forecast_missing"
    with db_factory() as db:
        db.add(Forecast(shop_id=shop_id, kind="setup", made_on=date(2020, 1, 1), drivers=[],
                        horizon_months=[{"k": 0, "start": "2020-01-01", "end": "2020-01-30", "p10": 1, "p50": 2,
                                         "p90": 3}]))
        db.commit()
    r = client.post(f"/api/shops/{shop_id}/simulate", headers=consented)
    assert r.status_code == 409 and r.json()["error"]["code"] == "forecast_has_no_month_ahead"


def test_endpoint_access(client, consented, with_model):
    shop_id = make_shop(client, consented)
    assert client.post(f"/api/shops/{shop_id}/simulate").status_code == 401
    other = login(client, "+919800000002")
    assert client.post(f"/api/shops/{shop_id}/simulate", headers=other).status_code == 403
    client.post("/api/consents", headers=other, json={"purpose": "shop_data"})
    assert client.post(f"/api/shops/{shop_id}/simulate", headers=other).status_code == 404
