"""Train ML2, the set-up forecast (checkpoint M-03), on SYNTHETIC shops only.

    make train                                  # inside the backend container (DEC-31)
    python -m app.ml.train [--data DIR] [--out DIR] [--seed N]

Model (DEC-35): one LightGBM model with Huber loss and monotone constraints gives P50; the band is
P10 = P50 x r10, P90 = P50 x r90, with r10/r90 the 10th/90th percentile of actual/predicted over out-of-fold
predictions on the training shops. Monotone rules therefore hold for all three lines by construction
(LightGBM rejects monotone constraints with its quantile and L1 objectives). M-04 re-sets r10/r90 on the
calibration shops (split conformal). Leaf size is picked by shop-grouped CV on training shops only (DEC-36).

Writes <out>/ml2_p50.joblib, split.json and model_card.json. Same data + same seed => identical files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from app.config import BACKEND_DIR, REPO_ROOT
from app.ml.features import FEATURES, HORIZON, MONOTONE, TARGET, monotone_vector, training_table

DATA_DIR = REPO_ROOT / "data" / "synthetic" / "out"
MODEL_DIR = BACKEND_DIR / "data" / "models" / "ml2"
MODEL_FILE = "ml2_p50.joblib"
ALPHAS = (0.1, 0.5, 0.9)
SPLIT = {"train": 0.6, "calibration": 0.2, "test": 0.2}       # by shop: 120 / 40 / 40 of 200 (DEC-32)
PARAMS = {                                                   # fixed (DEC-34, DEC-35) except the leaf size
    "objective": "huber", "alpha": 20000.0,                  # Huber delta in INR per month
    "n_estimators": 300, "learning_rate": 0.05, "num_leaves": 15,
    "deterministic": True, "force_row_wise": True, "n_jobs": 1, "verbose": -1,
}
LEAF_GRID = (20, 60, 120)          # min_child_samples, chosen by shop-grouped CV on TRAINING shops only (DEC-36)
CV_FOLDS = 5
MODEL_VERSION = "ml2-1.0.0"


def split_shops(shop_ids: list[str], seed: int) -> dict[str, list[str]]:
    ids = sorted(shop_ids)
    order = np.random.default_rng(seed).permutation(len(ids))
    n_tr, n_cal = round(len(ids) * SPLIT["train"]), round(len(ids) * SPLIT["calibration"])
    pick = lambda a, b: sorted(ids[i] for i in order[a:b])
    return {"train": pick(0, n_tr), "calibration": pick(n_tr, n_tr + n_cal), "test": pick(n_tr + n_cal, len(ids))}


def pinball(y: np.ndarray, q: np.ndarray, alpha: float) -> float:
    d = y - q
    return float(np.mean(np.maximum(alpha * d, (alpha - 1) * d)))


def mean_pinball(y: np.ndarray, q: np.ndarray) -> float:
    return float(np.mean([pinball(y, q[:, i], a) for i, a in enumerate(ALPHAS)]))


def fit_p50(X: pd.DataFrame, y, leaf: int, seed: int) -> lgb.LGBMRegressor:
    m = lgb.LGBMRegressor(min_child_samples=leaf, random_state=seed, monotone_constraints=monotone_vector(), **PARAMS)
    return m.fit(X, y)


def predict_quantiles(model: lgb.LGBMRegressor, ratios: dict[str, float], X: pd.DataFrame) -> np.ndarray:
    """(n, 3) array of P10, P50, P90. Positive ratios keep the monotone shape; sorting guards against r10 > 1."""
    p50 = np.maximum(model.predict(X[FEATURES]), 0.0)
    return np.sort(np.column_stack([p50 * ratios["r10"], p50, p50 * ratios["r90"]]), axis=1)


def band_ratios(y: np.ndarray, p50: np.ndarray) -> dict[str, float]:
    r = y / np.maximum(p50, 1.0)
    return {"r10": round(float(np.quantile(r, 0.1)), 6), "r90": round(float(np.quantile(r, 0.9)), 6)}


def choose_leaf(train_part: pd.DataFrame, seed: int, grid: tuple[int, ...] = LEAF_GRID) -> tuple[int, dict, dict]:
    """Out-of-fold P50 per leaf size (folds grouped by shop); lowest mean pinball of the ratio band wins.
    Returns (leaf, scores, ratios of the chosen leaf). Ties go to the smaller leaf."""
    X, y, g = train_part[FEATURES], train_part[TARGET].to_numpy(), train_part["shop_id"]
    scores, ratios = {}, {}
    for leaf in grid:
        oof = np.zeros(len(y))
        for tr, va in GroupKFold(n_splits=CV_FOLDS).split(X, y, g):
            oof[va] = np.maximum(fit_p50(X.iloc[tr], y[tr], leaf, seed).predict(X.iloc[va]), 0.0)
        ratios[leaf] = band_ratios(y, oof)
        q = np.column_stack([oof * ratios[leaf]["r10"], oof, oof * ratios[leaf]["r90"]])
        scores[leaf] = round(mean_pinball(y, q), 2)
    best = min(grid, key=lambda lf: (scores[lf], lf))
    return best, scores, ratios[best]


def load(model_dir: Path = MODEL_DIR) -> tuple[lgb.LGBMRegressor, dict]:
    card = json.loads((model_dir / "model_card.json").read_text(encoding="utf-8"))
    return joblib.load(model_dir / MODEL_FILE), card


def _sha256(*paths: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()


def train(data_dir: Path = DATA_DIR, out: Path = MODEL_DIR, seed: int = 42) -> dict:
    meta = json.loads((data_dir / "metadata.json").read_text(encoding="utf-8"))
    if meta.get("is_synthetic") is not True:
        raise ValueError("training data must be the labelled synthetic set (metadata is_synthetic=true)")
    shops = pd.read_csv(data_dir / "shops.csv")
    table = training_table(shops, pd.read_csv(data_dir / "daily.csv"))
    assert not any(c.startswith("latent_") for c in FEATURES)
    split = split_shops(shops["shop_id"].tolist(), seed)
    part = {name: table[table["shop_id"].isin(ids)].reset_index(drop=True) for name, ids in split.items()}

    leaf, cv_scores, ratios = choose_leaf(part["train"], seed)
    model = fit_p50(part["train"][FEATURES], part["train"][TARGET], leaf, seed)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / MODEL_FILE, compress=3)

    y_cal = part["calibration"][TARGET].to_numpy()
    q = predict_quantiles(model, ratios, part["calibration"])
    metrics = {f"pinball_p{round(a * 100):02d}": round(pinball(y_cal, q[:, i], a), 2) for i, a in enumerate(ALPHAS)}
    metrics["wape_p50"] = round(float(np.abs(y_cal - q[:, 1]).sum() / y_cal.sum()), 4)
    metrics["coverage_p10_p90"] = round(float(((y_cal >= q[:, 0]) & (y_cal <= q[:, 2])).mean()), 4)

    (out / "split.json").write_text(json.dumps({"seed": seed, **split}, indent=2) + "\n", encoding="utf-8")
    card = {
        "model": "ML2 set-up forecast", "version": MODEL_VERSION, "is_synthetic": True,
        "notice": "Prototype model trained on synthetic data. Forecasts are estimates, not guarantees.",
        "trained_on": date.today().isoformat(),
        "data": {"dir": "data/synthetic/out", "sha256": _sha256(data_dir / "shops.csv", data_dir / "daily.csv"),
                 "generator_version": meta.get("generator_version"), "config_sha256": meta.get("config_sha256"),
                 "rows": len(table), "shops": {k: len(v) for k, v in split.items()}},
        "target": f"{TARGET} (INR per month k, months counted from the launch day)", "horizon_months": HORIZON,
        "features": FEATURES, "monotone": MONOTONE,
        "estimator": "lightgbm.LGBMRegressor (P50)",
        "params": {**PARAMS, "min_child_samples": leaf, "random_state": seed},
        "leaf_cv": {"grid": list(LEAF_GRID), "folds": CV_FOLDS, "grouped_by": "shop_id", "on": "train shops only",
                    "mean_pinball": {str(k): v for k, v in cv_scores.items()}, "chosen": leaf},
        "band": {"method": "P10 = P50 x r10, P90 = P50 x r90; ratios from out-of-fold training predictions",
                 "source": "train_oof", **ratios},
        "files": {"p50": MODEL_FILE}, "files_sha256": {MODEL_FILE: _sha256(out / MODEL_FILE)},
        "metrics_calibration_set_before_conformal": metrics,
        "calibration": None,                                  # filled by M-04 (split conformal on the ratios)
    }
    (out / "model_card.json").write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    return card


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--out", type=Path, default=MODEL_DIR)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    card = train(a.data, a.out, a.seed)
    print(f"[SYNTHETIC] ML2 trained -> {a.out}  shops {card['data']['shops']}  rows {card['data']['rows']}")
    print(f"  leaf CV (mean pinball) {card['leaf_cv']['mean_pinball']} -> min_child_samples {card['leaf_cv']['chosen']}")
    print(f"  band ratios r10 {card['band']['r10']:.3f}  r90 {card['band']['r90']:.3f}")
    for k, v in card["metrics_calibration_set_before_conformal"].items():
        print(f"  {k:20s} {v}")


if __name__ == "__main__":
    main()
