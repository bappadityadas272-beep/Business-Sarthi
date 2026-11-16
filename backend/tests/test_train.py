"""M-03: model file + model_card.json written; training is reproducible; band never crosses; monotone rules hold."""
import hashlib
import importlib.util
import json

import numpy as np
import pandas as pd
import pytest

from app.config import REPO_ROOT
from app.ml.features import FEATURES, MONOTONE, month_rows
from app.ml.train import LEAF_GRID, MODEL_FILE, load, predict_quantiles, split_shops, train

_spec = importlib.util.spec_from_file_location("synthetic_generate", REPO_ROOT / "data/synthetic/generate.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("syn")
    gen.main(["--out", str(d), "--n-shops", "40"])
    return d


@pytest.fixture(scope="module")
def trained(data, tmp_path_factory):
    out = tmp_path_factory.mktemp("models")
    train(data, out, seed=42)
    return out


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_files_and_card_written(trained):
    assert (trained / MODEL_FILE).is_file()
    card = json.loads((trained / "model_card.json").read_text())
    assert card["is_synthetic"] is True and "synthetic" in card["notice"]
    assert card["features"] == FEATURES and not any(f.startswith("latent_") for f in FEATURES)
    assert card["data"]["shops"] == {"train": 24, "calibration": 8, "test": 8}
    assert card["leaf_cv"]["chosen"] in LEAF_GRID and card["leaf_cv"]["on"] == "train shops only"
    assert 0 < card["band"]["r10"] < 1 < card["band"]["r90"]
    assert {"pinball_p10", "pinball_p50", "pinball_p90", "wape_p50"} <= set(card["metrics_calibration_set_before_conformal"])


def test_training_is_reproducible(data, trained, tmp_path):
    train(data, tmp_path, seed=42)
    assert _sha(trained / MODEL_FILE) == _sha(tmp_path / MODEL_FILE)
    assert (trained / "split.json").read_text() == (tmp_path / "split.json").read_text()
    a, b = (json.loads((d / "model_card.json").read_text()) for d in (trained, tmp_path))
    assert a["band"] == b["band"] and a["leaf_cv"] == b["leaf_cv"]


def test_split_is_by_shop_and_disjoint():
    s = split_shops([f"S{i:04d}" for i in range(1, 201)], 42)
    assert [len(s[k]) for k in ("train", "calibration", "test")] == [120, 40, 40]
    assert set(s["train"]).isdisjoint(s["calibration"]) and set(s["train"]).isdisjoint(s["test"])
    assert set(s["calibration"]).isdisjoint(s["test"])


def test_band_never_crosses(data, trained):
    model, card = load(trained)
    q = predict_quantiles(model, card["band"], month_rows(pd.read_csv(data / "shops.csv")))
    assert (q[:, 0] <= q[:, 1]).all() and (q[:, 1] <= q[:, 2]).all() and (q >= 0).all()


def test_monotone_rules_hold_for_all_three_lines(data, trained):
    model, card = load(trained)
    shops = pd.read_csv(data / "shops.csv").head(15)
    for feat, sign in MONOTONE.items():
        vals = np.linspace(shops[feat].min(), shops[feat].max() * 1.5, 8)
        for _, r in shops.iterrows():
            df = pd.DataFrame([{**r.to_dict(), feat: v} for v in vals])
            q = predict_quantiles(model, card["band"], month_rows(df)).reshape(len(df), -1, 3)
            assert ((q[1:] - q[:-1]) * sign >= -1e-6).all(), feat
