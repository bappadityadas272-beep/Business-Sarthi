"""Split conformal calibration of the ML2 band (checkpoint M-04, DEC-38).

    python -m app.ml.calibrate [--data DIR] [--models DIR]        # `make train` runs this after training

Uses ONLY the calibration shops in split.json. Score = actual / P50 (so the correction scales with shop size).
For each forecast month k the band becomes P10 = P50 x r10(k), P90 = P50 x r90(k), where r10/r90 are the
finite-sample-corrected alpha/2 and 1 - alpha/2 quantiles of the scores. If a month has too few calibration
rows, months are pooled into bins (1-3, 4-6, 7-12), then into one group. Result goes into model_card.json.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from app.ml.features import HORIZON, TARGET, training_table
from app.ml.train import DATA_DIR, MODEL_DIR, load, predict_quantiles

TARGET_COVERAGE = 0.80          # central P10-P90 coverage aimed for (DEC-38); acceptance band is 75% to 85%
MIN_ROWS = 20                   # fewest calibration rows per group; below this, months are pooled
MONTH_BINS = ((1, 3), (4, 6), (7, 12))


def conformal_bounds(scores: np.ndarray, alpha: float) -> tuple[float, float]:
    """Lower and upper score bounds for central coverage 1 - alpha, with the finite-sample correction:
    upper = the ceil((n+1)(1-alpha/2))-th smallest score, lower = the floor((n+1)(alpha/2))-th smallest."""
    s = np.sort(np.asarray(scores, dtype=float))
    n = len(s)
    hi = min(n, math.ceil((n + 1) * (1 - alpha / 2)))
    lo = max(1, math.floor((n + 1) * (alpha / 2)))
    return float(s[lo - 1]), float(s[hi - 1])


def month_groups(k: np.ndarray, min_rows: int = MIN_ROWS) -> tuple[str, list[tuple[int, int]]]:
    """Finest grouping of months 1..12 in which every group has at least `min_rows` rows."""
    options = (("per_month", [(m, m) for m in range(1, HORIZON + 1)]), ("month_bins", list(MONTH_BINS)),
               ("all_months", [(1, HORIZON)]))
    for name, groups in options:
        if all(((k >= a) & (k <= b)).sum() >= min_rows for a, b in groups):
            return name, groups
    return options[-1]


def fit_calibration(y: np.ndarray, p50: np.ndarray, k: np.ndarray, target: float = TARGET_COVERAGE,
                    min_rows: int = MIN_ROWS) -> dict:
    alpha = 1 - target
    scores = y / np.maximum(p50, 1.0)
    grouping, groups = month_groups(k, min_rows)
    by_month = {}
    for a, b in groups:
        sel = (k >= a) & (k <= b)
        lo, hi = conformal_bounds(scores[sel], alpha)
        for m in range(a, b + 1):
            by_month[str(m)] = {"r10": round(lo, 6), "r90": round(hi, 6), "n": int(sel.sum())}
    return {"method": "split conformal on actual / P50, finite-sample corrected", "target_coverage": target,
            "alpha": round(alpha, 4), "grouping": grouping, "by_month": by_month}


def calibrate(data_dir: Path = DATA_DIR, model_dir: Path = MODEL_DIR) -> dict:
    model, card = load(model_dir)
    split = json.loads((model_dir / "split.json").read_text(encoding="utf-8"))
    cal_ids = set(split["calibration"])
    assert cal_ids.isdisjoint(split["train"]) and cal_ids.isdisjoint(split["test"])
    shops = pd.read_csv(data_dir / "shops.csv")
    shops = shops[shops["shop_id"].isin(cal_ids)]              # nothing outside the calibration shops is read
    daily = pd.read_csv(data_dir / "daily.csv")
    table = training_table(shops, daily[daily["shop_id"].isin(cal_ids)])
    y, k = table[TARGET].to_numpy(), table["k"].to_numpy()
    p50 = predict_quantiles(model, card["band"], table)[:, 1]
    cal = fit_calibration(y, p50, k)
    q = predict_quantiles(model, cal, table)
    cal.update({"source": "calibration shops only", "n_shops": len(cal_ids), "n_rows": len(table),
                "coverage_on_calibration_set": round(float(((y >= q[:, 0]) & (y <= q[:, 2])).mean()), 4),
                "is_synthetic": True})
    card["calibration"] = cal
    (model_dir / "model_card.json").write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    return cal


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--models", type=Path, default=MODEL_DIR)
    a = ap.parse_args(argv)
    cal = calibrate(a.data, a.models)
    print(f"[SYNTHETIC] ML2 calibrated on {cal['n_shops']} shops ({cal['n_rows']} rows), grouping {cal['grouping']}, "
          f"target {cal['target_coverage']:.0%}, coverage on calibration set {cal['coverage_on_calibration_set']:.1%}")
    for m, v in cal["by_month"].items():
        print(f"  month {int(m):2d}  r10 {v['r10']:.3f}  r90 {v['r90']:.3f}  n {v['n']}")


if __name__ == "__main__":
    main()
