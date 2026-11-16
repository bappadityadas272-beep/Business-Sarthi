"""ML2 evaluation on the held-out TEST shops (checkpoint M-04). SYNTHETIC data: this checks the code and the
calibration, not real-world accuracy.

    make eval                                         # inside the backend container; rewrites docs/EVAL_REPORT.md
    python eval/forecast_eval.py [--data DIR] [--models DIR] [--write]

Baseline (DEC-37): PEER MEDIAN = median monthly revenue of TRAINING shops in the same (city tier, size bucket,
month since opening). Size buckets are terciles of the training shops. Nothing here is used for tuning.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "eval"))

from app.ml.features import MONOTONE, TARGET, month_rows, training_table
from app.ml.train import ALPHAS, DATA_DIR, MODEL_DIR, load, pinball, predict_quantiles

REPORT = REPO / "docs" / "EVAL_REPORT.md"
NOTES = Path(__file__).with_name("forecast_notes.md")
TARGET_WAPE_GAIN, COVERAGE_BAND = 0.10, (0.75, 0.85)
BUCKETS = ["small", "medium", "large"]


def size_cuts(train_shops: pd.DataFrame) -> list[float]:
    return [float(x) for x in train_shops["size_sqft"].quantile([1 / 3, 2 / 3])]


def size_bucket(size: pd.Series, cuts: list[float]) -> pd.Series:
    return pd.cut(size, [-np.inf, *cuts, np.inf], labels=BUCKETS).astype(str)


def peer_quantiles(train: pd.DataFrame, rows: pd.DataFrame) -> np.ndarray:
    """(n, 3) peer P10/P50/P90 of training shops per (tier, bucket, k); falls back to (tier, k), then (k)."""
    out = np.full((len(rows), 3), np.nan)
    for keys in (["city_tier", "bucket", "k"], ["city_tier", "k"], ["k"]):
        g = train.groupby(keys)[TARGET].quantile(list(ALPHAS)).unstack()
        m = rows[keys].merge(g, left_on=keys, right_index=True, how="left")[list(ALPHAS)].to_numpy()
        out = np.where(np.isnan(out), m, out)
    return out


def wape(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.abs(y - p).sum() / y.sum())


def coverage(y: np.ndarray, q: np.ndarray) -> float:
    return float(((y >= q[:, 0]) & (y <= q[:, 2])).mean())


def monotone_breaks(model, band: dict, shops: pd.DataFrame, lo_hi: dict, steps: int = 8) -> dict:
    out = {}
    for feat, sign in MONOTONE.items():
        vals = np.linspace(*lo_hi[feat], steps)
        bad = n = 0
        for _, r in shops.iterrows():
            df = pd.DataFrame([{**r.to_dict(), feat: v} for v in vals])
            q = predict_quantiles(model, band, month_rows(df)).reshape(steps, -1, 3)
            d = (q[1:] - q[:-1]) * sign
            bad += int((d < -1e-6).sum())
            n += d.size
        out[feat] = {"breaks": bad, "checks": n}
    return out


def _group_order(key) -> tuple:
    return (BUCKETS.index(key), 0) if key in BUCKETS else (0, key)


def evaluate(data_dir: Path = DATA_DIR, model_dir: Path = MODEL_DIR) -> dict:
    model, card = load(model_dir)
    if not card.get("calibration"):
        raise SystemExit("model is not calibrated: run `make train` (python -m app.ml.calibrate) first")
    split = json.loads((model_dir / "split.json").read_text(encoding="utf-8"))
    sets = {k: set(split[k]) for k in ("train", "calibration", "test")}
    overlap = (sets["train"] & sets["calibration"]) | (sets["train"] & sets["test"]) | (sets["calibration"] & sets["test"])
    shops = pd.read_csv(data_dir / "shops.csv")
    table = training_table(shops, pd.read_csv(data_dir / "daily.csv"))
    tr_shops = shops[shops["shop_id"].isin(sets["train"])]
    cuts = size_cuts(tr_shops)
    table["bucket"] = size_bucket(table["size_sqft"], cuts)
    train = table[table["shop_id"].isin(sets["train"])]
    test = table[table["shop_id"].isin(sets["test"])].reset_index(drop=True)

    y = test[TARGET].to_numpy()
    q = predict_quantiles(model, card["calibration"], test)
    q_raw = predict_quantiles(model, card["band"], test)
    peer = peer_quantiles(train, test)
    w_model, w_peer = wape(y, q[:, 1]), wape(y, peer[:, 1])
    cov = coverage(y, q)
    inside = (y >= q[:, 0]) & (y <= q[:, 2])

    def by(col: str) -> dict:
        groups = sorted(test.groupby(col).indices.items(), key=lambda kv: _group_order(kv[0]))
        return {str(k): {"coverage": round(float(inside[idx].mean()), 4), "n": len(idx),
                         "wape": round(wape(y[idx], q[idx, 1]), 4), "wape_peer": round(wape(y[idx], peer[idx, 1]), 4)}
                for k, idx in groups}

    lo_hi = {f: (float(tr_shops[f].min()), float(tr_shops[f].max())) for f in MONOTONE}
    mono = monotone_breaks(model, card["calibration"], shops[shops["shop_id"].isin(sets["test"])], lo_hi)
    gain = 1 - w_model / w_peer
    width = q[:, 2] - q[:, 0]
    ordered = bool(((q[:, 0] <= q[:, 1]) & (q[:, 1] <= q[:, 2])).all())
    return {
        "is_synthetic": True, "model_version": card["version"], "data_sha256": card["data"]["sha256"],
        "model_sha256": next(iter(card["files_sha256"].values())), "generator_version": card["data"]["generator_version"],
        "split": {"sizes": {k: len(v) for k, v in sets.items()}, "by": "shop_id", "overlapping_shop_ids": len(overlap)},
        "size_bucket_cuts_sqft": [round(c, 1) for c in cuts], "test_rows": len(test),
        "calibration": {"target_coverage": card["calibration"]["target_coverage"],
                        "grouping": card["calibration"]["grouping"], "n_shops": card["calibration"]["n_shops"]},
        "wape": {"model_p50": round(w_model, 4), "peer_median": round(w_peer, 4), "relative_gain": round(gain, 4),
                 "target_gain": TARGET_WAPE_GAIN, "met": bool(gain >= TARGET_WAPE_GAIN)},
        "pinball": {f"p{round(a * 100):02d}": {"model": round(pinball(y, q[:, i], a), 1),
                                              "model_before_conformal": round(pinball(y, q_raw[:, i], a), 1),
                                              "peer": round(pinball(y, peer[:, i], a), 1)} for i, a in enumerate(ALPHAS)},
        "coverage": {"overall": round(cov, 4), "before_conformal": round(coverage(y, q_raw), 4),
                     "peer_band": round(coverage(y, peer), 4),
                     "below_p10": round(float((y < q[:, 0]).mean()), 4), "above_p90": round(float((y > q[:, 2]).mean()), 4),
                     "band": list(COVERAGE_BAND), "met": bool(COVERAGE_BAND[0] <= cov <= COVERAGE_BAND[1]),
                     "by_month": by("k"), "by_city_tier": by("city_tier"), "by_size_bucket": by("bucket")},
        "width": {"mean_inr": round(float(width.mean()), 0), "mean_share_of_p50": round(float((width / q[:, 1]).mean()), 4),
                  "before_conformal_share_of_p50": round(float(((q_raw[:, 2] - q_raw[:, 0]) / q_raw[:, 1]).mean()), 4),
                  "peer_mean_inr": round(float((peer[:, 2] - peer[:, 0]).mean()), 0)},
        "order": {"p10_le_p50_le_p90": ordered, "p10_positive": bool((q[:, 0] > 0).all())},
        "monotone": {"by_feature": mono, "total_breaks": sum(v["breaks"] for v in mono.values()),
                     "total_checks": sum(v["checks"] for v in mono.values())},
    }


def _mark(ok: bool) -> str:
    return "MET" if ok else "**MISSED**"


def _table(d: dict, label: str) -> list[str]:
    rows = [f"| {label} | Rows | Coverage P10-P90 | WAPE model | WAPE peer median |", "|---|---|---|---|---|"]
    return rows + [f"| {k} | {v['n']} | {v['coverage']:.1%} | {v['wape']:.3f} | {v['wape_peer']:.3f} |" for k, v in d.items()]


def render(r: dict) -> str:
    w, c, p, wd, m, sz = r["wape"], r["coverage"], r["pinball"], r["width"], r["monotone"], r["split"]["sizes"]
    order_ok = r["order"]["p10_le_p50_le_p90"] and r["order"]["p10_positive"]
    lines = [
        "# EVAL_REPORT: model evaluation", "",
        "> Generated by `make eval` (`eval/forecast_eval.py --write`). Do not edit by hand; hand-written notes live in `eval/forecast_notes.md`.",
        "> **All data is SYNTHETIC (`is_synthetic: true`).** These numbers show that the code and the calibration behave as designed.",
        "> They are **not** evidence of real-world accuracy. Targets are our own prototype targets (ML_PLAN section 8).", "",
        "## ML2 set-up forecast (M-04)", "",
        (f"- Model `{r['model_version']}`, generator `{r['generator_version']}`, model SHA-256 `{r['model_sha256'][:12]}`, "
        f"data SHA-256 `{r['data_sha256'][:12]}`."),
        (f"- Split by shop: {sz['train']} train / {sz['calibration']} calibration / {sz['test']} test; shop IDs in more than "
        f"one set: **{r['split']['overlapping_shop_ids']}**. Test shops are read only by this script."),
        (f"- Calibration: split conformal on actual / P50, {r['calibration']['grouping'].replace('_', ' ')}, on "
        f"{r['calibration']['n_shops']} calibration shops, target central coverage {r['calibration']['target_coverage']:.0%}."),
        ("- Baseline: peer median of training shops per (city tier, size bucket, month since opening); size cuts at "
        f"{r['size_bucket_cuts_sqft'][0]} and {r['size_bucket_cuts_sqft'][1]} sq ft (training terciles)."),
        f"- Everything below is measured on the {sz['test']} test shops ({r['test_rows']} shop-months).", "",
        "### Targets", "",
        "| Target | Result | Status |", "|---|---|---|",
        (f"| WAPE at least {w['target_gain']:.0%} lower than the peer-median baseline | model {w['model_p50']:.3f} vs peer "
        f"{w['peer_median']:.3f}: {w['relative_gain']:+.1%} | {_mark(w['met'])} |"),
        f"| P10 to P90 coverage within {c['band'][0]:.0%} to {c['band'][1]:.0%} | {c['overall']:.1%} | {_mark(c['met'])} |",
        f"| Monotone rules hold | {m['total_breaks']} breaks in {m['total_checks']:,} checks | {_mark(m['total_breaks'] == 0)} |",
        f"| P10 <= P50 <= P90 and P10 > 0 | {order_ok} | {_mark(order_ok)} |", "",
        "### Pinball loss (INR per shop-month, lower is better)", "",
        "| Quantile | Model (calibrated) | Model before conformal | Peer quantile baseline |", "|---|---|---|---|",
        *[f"| {k.upper()} | {v['model']:,.0f} | {v['model_before_conformal']:,.0f} | {v['peer']:,.0f} |" for k, v in p.items()], "",
        "### Coverage and interval width", "",
        (f"- Coverage: **{c['overall']:.1%}** after conformal ({c['before_conformal']:.1%} before); {c['below_p10']:.1%} of "
        f"months fell below P10 and {c['above_p90']:.1%} above P90."),
        (f"- Mean width P90 - P10: INR {wd['mean_inr']:,.0f} per month, {wd['mean_share_of_p50']:.0%} of P50 "
        f"({wd['before_conformal_share_of_p50']:.0%} before conformal). Peer P10-P90 band: INR {wd['peer_mean_inr']:,.0f} "
        f"wide with {c['peer_band']:.1%} coverage."),
        ("- Breakdown groups hold fewer shops than the whole test set, and a shop's 12 months move together, so a group's "
        "coverage can sit several points from the overall figure by chance."), "",
        *_table(c["by_month"], "Month since opening"), "", *_table(c["by_city_tier"], "City tier"), "",
        *_table(c["by_size_bucket"], "Size bucket"), "",
        "### Monotone-rules check", "",
        ("Each test shop's profile is varied over 8 values across the training range of one feature; P10, P50 and P90 "
        "must never move the wrong way."), "",
        "| Feature | Breaks | Checks |", "|---|---|---|",
        *[f"| {f} | {v['breaks']} | {v['checks']:,} |" for f, v in m["by_feature"].items()], "",
    ]
    if NOTES.is_file():
        lines += ["### Notes and honest reading", "", NOTES.read_text(encoding="utf-8").strip(), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--models", type=Path, default=MODEL_DIR)
    ap.add_argument("--write", action="store_true", help="write docs/EVAL_REPORT.md")
    ap.add_argument("--json", action="store_true", help="print the raw result as JSON")
    a = ap.parse_args(argv)
    r = evaluate(a.data, a.models)
    text = render(r)
    print(json.dumps(r, indent=2) if a.json else text)
    if a.write:
        from parts import merge  # keep the parts written by the other eval scripts
        REPORT.write_text(merge(text) + "\n", encoding="utf-8", newline="\n")
        print(f"\nwrote {REPORT}")


if __name__ == "__main__":
    main()
