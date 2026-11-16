"""M-06: re-forecast (shrinkage blend of the set-up forecast and the shop's own sales)."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.ml import reforecast as rf
from app.models import Forecast
from app.rules import get_rules
from app.services import clock
from tests.conftest import SHOP

OPEN = date(2026, 1, 1)
WEEK = np.array([1.0, 0.9, 0.95, 1.0, 1.1, 1.3, 1.25])      # a weekly pattern, mean about 1.07


def prior(p50: float = 30000.0, open_date: date = OPEN) -> list[dict]:
    return [{"k": i + 1, "start": a, "end": b, "p10": 0.7 * p50, "p50": p50, "p90": 1.4 * p50}
            for i, (a, b) in enumerate(rf.month_windows(open_date))]


def sales(days: int, level: float = 2000.0, seed: int = 1, open_date: date = OPEN) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(open_date, periods=days, freq="D")
    return pd.Series(level * WEEK[np.arange(days) % 7] * rng.normal(1.0, 0.05, days), index=idx)


def drop(s: pd.Series, share: float, seed: int = 7) -> pd.Series:
    """Remove exactly round(share x n) days at random (they become MISSING, not zero)."""
    gone = np.random.default_rng(seed).choice(len(s), size=round(share * len(s)), replace=False)
    return s.drop(s.index[gone])


def run(s: pd.Series, days: int = 90, **kw) -> dict:
    return rf.reforecast(s, OPEN + timedelta(days=days - 1), prior(), get_rules().blend, start=OPEN, **kw)


def test_month_windows_follow_the_opening_day():
    w = rf.month_windows(date(2026, 1, 31), 3)
    assert w[0] == (date(2026, 1, 31), date(2026, 2, 27)) and w[1][0] == date(2026, 2, 28)
    assert rf.month_windows(OPEN)[11] == (date(2026, 12, 1), date(2026, 12, 31))


def test_weight_is_n_over_n_plus_k():
    rule = get_rules().blend
    out = run(sales(90))
    assert out["n_days"] == 90 and out["k"] == rule.k
    assert out["weight_own"] == pytest.approx(90 / (90 + rule.k), abs=1e-4)
    assert run(sales(90), k=90)["weight_own"] == 0.5
    assert run(drop(sales(90), 0.5))["weight_own"] == pytest.approx(45 / (45 + rule.k), abs=1e-4)   # logged days count


def test_blend_sits_between_prior_and_own_model():
    out = run(sales(90))                                     # the shop sells about 2x what the prior said
    for m in out["months"]:
        if m["days_logged"] == 0:
            lo, hi = sorted((m["prior_p50"], m["own_p50"]))
            assert lo <= m["p50"] <= hi
    nxt = out["months"][0]
    assert nxt["k"] == 4 and nxt["start"] == date(2026, 4, 1) and nxt["own_p50"] > 1.6 * nxt["prior_p50"]


@pytest.mark.parametrize("share", [0.0, 0.1, 0.3, 0.5])
def test_gaps_are_missing_not_zero(share):
    full = run(sales(90))
    out = run(drop(sales(90), share))
    assert out["missing_share"] == pytest.approx(share, abs=0.006)
    assert all(m["p10"] <= m["p50"] <= m["p90"] for m in out["months"])
    # the shop's own model still sees about 2,140 a day; zero-filling would pull this down by the missing share
    own, own_full = out["months"][0]["own_p50"], full["months"][0]["own_p50"]
    assert own == pytest.approx(own_full, rel=0.10)
    keys = [r["key"] for r in out["confidence"]["reasons"]]
    if share > 0.3:
        assert out["confidence"]["level"] == "low" and "confidence.many_days_missing" in keys
        why = next(r for r in out["confidence"]["reasons"] if r["key"] == "confidence.many_days_missing")
        assert why["params"] == {"missing_percent": 50, "limit_percent": 30}
    else:                                                    # exactly 30% missing is not "more than 30%"
        assert out["confidence"]["level"] == "medium" and keys == ["confidence.synthetic_training"]


def test_days_missing_in_the_running_month_are_estimated_not_counted_as_zero():
    s = sales(75)                                            # origin in the middle of month 3 (March)
    holes = drop(s, 0.3)
    a, b = run(s, days=75)["months"][0], run(holes, days=75)["months"][0]
    assert a["k"] == b["k"] == 3 and b["days_logged"] < a["days_logged"] and b["days_open"] > a["days_open"]
    assert b["actual_so_far"] < a["actual_so_far"]
    assert b["own_p50"] == pytest.approx(a["own_p50"], rel=0.05)     # own model: gaps filled at its daily rate
    prior_filled = b["actual_so_far"] + 30000 / 31 * b["days_open"]   # every open day at the prior daily rate
    assert prior_filled < b["p50"] < b["own_p50"]            # the blend fills gaps between the two, never with zero


def test_nothing_after_the_origin_is_used():
    s = sales(200)
    origin_days = 60
    cut = s.iloc[:origin_days]
    poisoned = s.copy()
    poisoned.iloc[origin_days:] = 9e9
    assert run(cut, days=origin_days) == run(s, days=origin_days) == run(poisoned, days=origin_days)


def test_level_only_below_28_days_and_low_confidence_with_reason():
    short = run(sales(20), days=20)
    assert short["own_model"] == "level_only" and short["confidence"]["level"] == "low"
    assert {"key": "confidence.few_days_logged", "params": {"days_logged": 20, "needed": 30}} in short["confidence"]["reasons"]
    assert run(sales(28), days=28)["own_model"] == "ets_damped_trend_weekly"
    assert run(drop(sales(40), 0.5), days=40)["own_model"] == "level_only"      # 20 logged days in a 40-day span


def test_too_little_data_or_a_finished_horizon_is_refused():
    with pytest.raises(rf.NotEnoughData):
        run(sales(6), days=6)
    with pytest.raises(rf.NotEnoughData):
        run(sales(400), days=400)


def test_band_ordered_never_negative_and_follows_the_observed_error():
    rule = get_rules().blend
    close = rf.reforecast(sales(90, level=1000.0), OPEN + timedelta(days=89), prior(32000.0), rule, start=OPEN)
    far = run(sales(90, level=3000.0))                       # about 3x the prior: band at the upper rescale limit
    assert close["interval_rescale"] == rule.error_rescale_min and far["interval_rescale"] == rule.error_rescale_max
    assert close["observed_error"] < 0.1 < far["observed_error"]
    for out in (close, far, run(drop(sales(90), 0.5)), run(sales(90), interval_scale=50.0)):
        for m in out["months"]:
            assert 0 <= m["p10"] <= m["p50"] <= m["p90"]
    width = lambda o: (o["months"][0]["p90"] - o["months"][0]["p10"]) / o["months"][0]["p50"]
    assert width(far) > width(close)
    one, two = run(sales(90), interval_scale=1.0), run(sales(90), interval_scale=2.0)
    assert width(two) == pytest.approx(2 * width(one), rel=0.01)


def test_ets_handles_a_gap_week_and_a_flat_series():
    y = sales(60).reindex(pd.date_range(OPEN, periods=60, freq="D"))
    y.iloc[20:27] = np.nan                                   # a whole week not logged
    out = rf.ets_daily(y, 30, level_only=False)
    assert out["forecast"].shape == (30,) and np.isfinite(out["forecast"]).all() and (out["forecast"] >= 0).all()
    flat = rf.ets_daily(pd.Series(500.0, index=pd.date_range(OPEN, periods=40, freq="D")), 10, level_only=False)
    assert flat["forecast"] == pytest.approx(np.full(10, 500.0), rel=0.01)


def test_sum_sd_by_hand():
    assert rf.sum_sd(0.0, 10.0, 1, 4) == pytest.approx(20.0)             # independent days: 10 x sqrt(4)
    assert rf.sum_sd(1.0, 10.0, 1, 3) == pytest.approx(10 * 14 ** 0.5)   # random walk: weights 3, 2, 1
    assert rf.sum_sd(0.5, 2.0, 2, 3) == pytest.approx(2 * (1.0 + 2.25 + 1.0) ** 0.5)   # e1 x (0.5 + 0.5), e2 x 1.5, e3 x 1


# ---- endpoint ----
def shop_with_history(client, h, days: int, missing: float = 0.0, forecast: bool = True) -> tuple[int, date]:
    """A shop that opened `days` days ago (app clock), with a set-up forecast and logs up to yesterday."""
    opened = clock.today() - timedelta(days=days)
    sid = client.post("/api/shops", headers=h, json={**SHOP, "launch_date": opened.isoformat()}).json()["id"]
    if forecast:
        assert client.post(f"/api/shops/{sid}/forecast", headers=h).status_code == 200
    s = drop(sales(days, open_date=opened), missing)
    entries = [{"day": d.date().isoformat(), "category": c, "sales": round(float(v) * share, 2)}
               for d, v in s.items() for c, share in (("staples", 0.6), ("dairy", 0.4))]
    for i in range(0, len(entries), 200):
        assert client.post(f"/api/shops/{sid}/logs", headers=h, json={"entries": entries[i:i + 200]}).status_code == 200
    return sid, opened


def test_endpoint_blends_stores_and_reports(client, consented, with_model, db_factory):
    sid, _ = shop_with_history(client, consented, 60)
    r = client.post(f"/api/shops/{sid}/reforecast", headers=consented)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["kind"] == "reforecast" and out["is_estimate"] is True and out["trained_on_synthetic"] is True
    assert out["origin"] == (clock.today() - timedelta(days=1)).isoformat()
    k = get_rules().blend.k
    assert out["n_days"] == out["span_days"] == 60 and out["missing_share"] == 0
    assert out["k"] == k and out["weight_own"] == pytest.approx(60 / (60 + k), abs=1e-4)
    assert all(m["p10"] <= m["p50"] <= m["p90"] for m in out["months"]) and out["months"][-1]["k"] == 12
    assert out["confidence"]["level"] == "medium"
    with db_factory() as db:
        row = db.get(Forecast, out["forecast_id"])
        assert row.kind == "reforecast" and row.made_on == clock.today() and row.shop_id == sid
        assert [m["p50"] for m in row.horizon_months] == [m["p50"] for m in out["months"]]
        assert db.get(Forecast, out["based_on_forecast_id"]).kind == "setup"


def test_endpoint_low_confidence_when_half_the_days_are_missing(client, consented, with_model):
    sid, _ = shop_with_history(client, consented, 90, missing=0.5)
    out = client.post(f"/api/shops/{sid}/reforecast", headers=consented).json()
    assert out["n_days"] == 45 and out["missing_share"] == 0.5 and out["confidence"]["level"] == "low"
    assert "confidence.many_days_missing" in [x["key"] for x in out["confidence"]["reasons"]]


def test_endpoint_ignores_a_log_dated_today(client, consented, with_model):
    sid, _ = shop_with_history(client, consented, 60)
    before = client.post(f"/api/shops/{sid}/reforecast", headers=consented).json()
    client.post(f"/api/shops/{sid}/logs", headers=consented,
                json={"entries": [{"day": clock.today().isoformat(), "category": "staples", "sales": 9e7}]})
    after = client.post(f"/api/shops/{sid}/reforecast", headers=consented).json()
    assert after["months"] == before["months"]               # today is not finished: origin is yesterday


def test_endpoint_errors(client, consented, with_model):
    no_forecast, _ = shop_with_history(client, consented, 40, forecast=False)
    r = client.post(f"/api/shops/{no_forecast}/reforecast", headers=consented)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "setup_forecast_missing"
    few, _ = shop_with_history(client, consented, 5)
    r = client.post(f"/api/shops/{few}/reforecast", headers=consented)
    assert r.status_code == 422 and r.json()["detail"] == {"code": "not_enough_days_logged", "days_logged": 5, "needed": 7}
    assert client.post(f"/api/shops/{few}/reforecast").status_code == 401
    client.delete("/api/consents", headers=consented, params={"purpose": "shop_data"})
    assert client.post(f"/api/shops/{few}/reforecast", headers=consented).status_code == 403
