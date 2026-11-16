"""M-04: split conformal on actual / P50 uses only calibration shops; band stays ordered; eval report runs."""
import importlib.util
import json

import numpy as np
import pandas as pd
import pytest

from app.config import REPO_ROOT
from app.ml import calibrate as cal_mod
from app.ml.calibrate import calibrate, conformal_bounds, fit_calibration, month_groups
from app.ml.features import month_rows
from app.ml.train import active_band, load, predict_quantiles, train


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("synthetic_generate", "data/synthetic/generate.py")
ev = _load("forecast_eval", "eval/forecast_eval.py")


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("syn")
    gen.main(["--out", str(d), "--n-shops", "150"])
    return d


@pytest.fixture(scope="module")
def models(data, tmp_path_factory):
    out = tmp_path_factory.mktemp("models")
    train(data, out, seed=42)
    calibrate(data, out)
    return out


def test_conformal_bounds_use_the_finite_sample_ranks():
    s = np.arange(1, 41) / 10.0                       # n = 40, alpha = 0.2
    lo, hi = conformal_bounds(s[::-1], 0.2)           # order of the input must not matter
    assert hi == pytest.approx(3.7)                   # ceil(41 * 0.9) = 37th smallest
    assert lo == pytest.approx(0.4)                   # floor(41 * 0.1) = 4th smallest
    lo, hi = conformal_bounds(np.array([1.0, 2.0, 3.0]), 0.2)
    assert (lo, hi) == (1.0, 3.0)                     # ranks clipped to 1..n when n is tiny


def test_conformal_bounds_are_wider_than_plain_quantiles():
    s = np.random.default_rng(0).lognormal(0, 0.3, 40)
    lo, hi = conformal_bounds(s, 0.2)
    assert lo <= np.quantile(s, 0.1) and hi >= np.quantile(s, 0.9)


def test_months_are_pooled_when_data_is_thin():
    assert month_groups(np.tile(np.arange(1, 13), 25), 20)[0] == "per_month"
    assert month_groups(np.tile(np.arange(1, 13), 10), 20)[0] == "month_bins"
    assert month_groups(np.tile(np.arange(1, 13), 2), 20)[0] == "all_months"
    y = np.random.default_rng(1).lognormal(11, 0.3, 120)
    c = fit_calibration(y, np.full(120, np.median(y)), np.tile(np.arange(1, 13), 10))
    assert c["grouping"] == "month_bins" and set(c["by_month"]) == {str(m) for m in range(1, 13)}
    assert c["by_month"]["1"] == c["by_month"]["3"] and c["by_month"]["1"]["n"] == 30


def test_calibration_hits_target_on_exchangeable_scores():
    rng = np.random.default_rng(2)
    p50 = rng.uniform(5e4, 5e5, 24000)
    y = p50 * rng.lognormal(0, 0.3, 24000)
    k = np.tile(np.arange(1, 13), 2000)
    c = fit_calibration(y[:12000], p50[:12000], k[:12000])
    lo = np.array([c["by_month"][str(m)]["r10"] for m in k[12000:]])
    hi = np.array([c["by_month"][str(m)]["r90"] for m in k[12000:]])
    cov = ((y[12000:] >= p50[12000:] * lo) & (y[12000:] <= p50[12000:] * hi)).mean()
    assert 0.78 <= cov <= 0.82


def test_no_shop_in_two_sets_and_only_calibration_shops_are_read(data, models, monkeypatch):
    split = json.loads((models / "split.json").read_text())
    ids = split["train"] + split["calibration"] + split["test"]
    assert len(ids) == len(set(ids)) == 150
    seen = {}
    real = cal_mod.training_table

    def spy(shops, daily):
        seen["shops"], seen["daily"] = set(shops.shop_id), set(daily.shop_id)
        return real(shops, daily)

    monkeypatch.setattr(cal_mod, "training_table", spy)
    c = calibrate(data, models)
    assert seen["shops"] == seen["daily"] == set(split["calibration"])
    assert c["n_shops"] == 30 and c["n_rows"] == 360 and c["source"] == "calibration shops only"


def test_card_updated_and_band_ordered_and_positive(data, models):
    model, card = load(models)
    c = card["calibration"]
    assert c["is_synthetic"] is True and c["target_coverage"] == 0.80 and len(c["by_month"]) == 12
    assert all(0 < v["r10"] < v["r90"] for v in c["by_month"].values())
    assert active_band(card) == c
    q = predict_quantiles(model, c, month_rows(pd.read_csv(data / "shops.csv")))
    assert (q[:, 0] > 0).all() and (q[:, 0] <= q[:, 1]).all() and (q[:, 1] <= q[:, 2]).all()


def test_band_is_resorted_even_if_ratios_are_on_the_wrong_side(data, models):
    model, _ = load(models)
    odd = {"by_month": {str(m): {"r10": 1.1, "r90": 0.9} for m in range(1, 13)}}
    q = predict_quantiles(model, odd, month_rows(pd.read_csv(data / "shops.csv").head(5)))
    assert (q[:, 0] <= q[:, 1]).all() and (q[:, 1] <= q[:, 2]).all() and (q[:, 0] > 0).all()


def test_eval_report_runs_on_test_shops_and_is_labelled(data, models):
    r = ev.evaluate(data, models)
    assert r["is_synthetic"] is True and r["split"]["overlapping_shop_ids"] == 0
    assert r["test_rows"] == 30 * 12 and r["monotone"]["total_breaks"] == 0
    assert set(r["pinball"]) == {"p10", "p50", "p90"} and 0 <= r["coverage"]["overall"] <= 1
    assert sum(v["n"] for v in r["coverage"]["by_month"].values()) == r["test_rows"]
    assert set(r["coverage"]["by_size_bucket"]) <= {"small", "medium", "large"}
    text = ev.render(r)
    assert "SYNTHETIC" in text and "peer median" in text and ("MET" in text or "MISSED" in text)


def test_peer_baseline_uses_training_medians_with_fallback():
    train_t = pd.DataFrame({"city_tier": [1, 1, 1, 2], "bucket": ["small"] * 4, "k": [1] * 4,
                            "revenue": [100.0, 200.0, 300.0, 1000.0]})
    rows = pd.DataFrame({"city_tier": [1, 2, 3], "bucket": ["small", "large", "small"], "k": [1, 1, 1]})
    p = ev.peer_quantiles(train_t, rows)[:, 1]
    assert list(p) == [200.0, 1000.0, 250.0]          # exact cell; (tier, k) fallback; (k) fallback
