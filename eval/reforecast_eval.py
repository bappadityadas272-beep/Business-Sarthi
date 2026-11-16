"""ML3 re-forecast backtest (checkpoint M-06). SYNTHETIC data: this checks the method and the code, not
real-world accuracy.

    make eval-reforecast                              # inside the backend container; updates docs/EVAL_REPORT.md
    python eval/reforecast_eval.py [--data DIR] [--models DIR] [--write] [--jobs N] [--reuse]

The model fits take most of the time. They are saved to <data>/reforecast_cases.joblib (generated, not in git);
`--reuse` scores that file again without refitting. Use it only if app/ml/reforecast.py and the data are unchanged.

Rolling origin: for each shop the forecast is made at the end of month 1, 2 and 3 (about 30, 60 and 90 days of
history) and scored on the NEXT 3 full months. Only days up to the origin are handed to the model.

Tuning uses TRAINING shops only. Their prior is an out-of-fold ML2 forecast (5 shop-grouped folds), so the prior
is as honest for them as it is for unseen shops. `k` is the value with the lowest blend WAPE there; the band
multiplier is the one whose coverage is closest to 80% there. TEST shops are only scored.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.model_selection import GroupKFold

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "eval"))

from parts import refresh_report, write_part

from app.ml.features import FEATURES, TARGET, month_rows, training_table
from app.ml.reforecast import NotEnoughData, combine, month_windows, prepare
from app.ml.train import DATA_DIR, MODEL_DIR, active_band, fit_p50, load, predict_quantiles
from app.rules import get_rules

K_GRID = (5, 10, 15, 30, 60, 120, 240)
SCALE_GRID = tuple(round(0.5 + 0.1 * i, 1) for i in range(46))       # 0.5 .. 5.0
HISTORY = (1, 2, 3)                # months of history at the origin
AHEAD = 3                          # months scored after the origin
GAPS = (0.0, 0.1, 0.3, 0.5)        # share of history days removed at random
TRAIN_SAMPLE = 300                 # training shops used for tuning (seeded sample, for run time)
COVERAGE_TARGET = 0.80
SEED = 42


def load_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.Series]]:
    shops = pd.read_csv(data_dir / "shops.csv")
    daily = pd.read_csv(data_dir / "daily.csv", usecols=["shop_id", "day", "sales"])
    tot = daily.groupby(["shop_id", "day"], as_index=False)["sales"].sum()
    tot["day"] = pd.to_datetime(tot["day"])
    series = {sid: g.set_index("day")["sales"] for sid, g in tot.groupby("shop_id")}
    return shops, daily, series


def as_prior(q: np.ndarray, launch) -> list[dict]:
    return [{"k": i + 1, "start": w[0], "end": w[1], "p10": float(q[i, 0]), "p50": float(q[i, 1]), "p90": float(q[i, 2])}
            for i, w in enumerate(month_windows(launch))]


def out_of_fold_priors(shops: pd.DataFrame, daily: pd.DataFrame, ids: list[str], leaf: int, band: dict) -> dict:
    """ML2 P10/P50/P90 for every training shop from a model that did not see that shop."""
    sh = shops[shops["shop_id"].isin(ids)].reset_index(drop=True)
    table = training_table(sh, daily)
    out = {}
    for tr, va in GroupKFold(n_splits=5).split(table[FEATURES], table[TARGET], table["shop_id"]):
        model = fit_p50(table.iloc[tr][FEATURES], table.iloc[tr][TARGET], leaf, SEED)
        held = sh[sh["shop_id"].isin(table.iloc[va]["shop_id"].unique())]
        rows = month_rows(held)
        q = predict_quantiles(model, band, rows)
        for sid in held["shop_id"]:
            out[sid] = q[(rows["shop_id"] == sid).to_numpy()]
    return out


def one_case(sid: str, series: pd.Series, launch, prior: list[dict], n: int, gap: float, rule) -> dict | None:
    """One (shop, origin, gap) case: prepared re-forecast pieces plus the actuals of the scored months."""
    win = month_windows(launch)
    origin = win[n - 1][1]
    history = series[(series.index >= pd.Timestamp(launch)) & (series.index <= pd.Timestamp(origin))]
    if gap > 0:
        rng = np.random.default_rng([SEED, int(sid[1:]) if sid[1:].isdigit() else 0, n, int(gap * 100)])
        history = history[rng.random(len(history)) >= gap]
    scored = win[n:n + AHEAD]
    actual = [float(series[(series.index >= pd.Timestamp(a)) & (series.index <= pd.Timestamp(b))].sum()) for a, b in scored]
    n_days = [(pd.Timestamp(b) - pd.Timestamp(a)).days + 1 for a, b in scored]
    try:
        ctx = prepare(history, origin, prior, rule, start=launch)       # `history` holds nothing after the origin
    except NotEnoughData:
        return None
    ctx["parts"] = ctx["parts"][:AHEAD]
    naive = [float(history.iloc[-7:].mean()) * d for d in n_days]       # last logged week, repeated
    return {"shop_id": sid, "n": n, "gap": gap, "ctx": ctx, "actual": actual, "naive": naive,
            "prior": [[m["p10"], m["p50"], m["p90"]] for m in prior[n:n + AHEAD]]}


def run_cases(ids, series, shops, priors, rule, gaps, jobs) -> list[dict]:
    launch = dict(zip(shops["shop_id"], pd.to_datetime(shops["launch_date"]).dt.date, strict=True))
    tasks = [delayed(one_case)(sid, series[sid], launch[sid], as_prior(priors[sid], launch[sid]), n, gap, rule)
             for sid in ids for n in HISTORY for gap in gaps]
    return [c for c in Parallel(n_jobs=jobs)(tasks) if c is not None]


def wape(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.abs(y - p).sum() / y.sum())


def score(cases: list[dict], rule, k: float, scale: float) -> dict:
    y, prior, own, naive, blend = [], [], [], [], []
    for c in cases:
        months = combine(c["ctx"], rule, k=k, interval_scale=scale)["months"]
        y += c["actual"]
        naive += c["naive"]
        prior += c["prior"]
        own += [m["own_p50"] for m in months]
        blend += [[m["p10"], m["p50"], m["p90"]] for m in months]
    y, prior, blend = np.array(y), np.array(prior), np.array(blend)
    assert (blend[:, 0] <= blend[:, 1]).all() and (blend[:, 1] <= blend[:, 2]).all(), "P10 <= P50 <= P90 broken"
    return {"shop_months": len(y), "wape_blend": wape(y, blend[:, 1]), "wape_prior": wape(y, prior[:, 1]),
            "wape_ets": wape(y, own), "wape_naive": wape(y, naive),
            "coverage_blend": float(((y >= blend[:, 0]) & (y <= blend[:, 2])).mean()),
            "coverage_prior": float(((y >= prior[:, 0]) & (y <= prior[:, 2])).mean()),
            "width_blend": float(((blend[:, 2] - blend[:, 0]) / blend[:, 1]).mean()),
            "width_prior": float(((prior[:, 2] - prior[:, 0]) / prior[:, 1]).mean())}


def pick(cases: list[dict], n: int | None = None, gap: float = 0.0) -> list[dict]:
    return [c for c in cases if c["gap"] == gap and (n is None or c["n"] == n)]


def build_cases(data_dir: Path, model_dir: Path, jobs: int) -> dict:
    rule = get_rules().blend
    shops, daily, series = load_data(data_dir)
    model, card = load(model_dir)
    split = json.loads((model_dir / "split.json").read_text(encoding="utf-8"))
    band = active_band(card)
    rng = np.random.default_rng(SEED)
    train_ids = sorted(rng.choice(split["train"], size=min(TRAIN_SAMPLE, len(split["train"])), replace=False).tolist())
    oof = out_of_fold_priors(shops, daily, split["train"], int(model.get_params()["min_child_samples"]), band)
    train_cases = run_cases(train_ids, series, shops, oof, rule, (0.0,), jobs)
    test_ids = sorted(split["test"])
    rows = month_rows(shops[shops["shop_id"].isin(test_ids)].reset_index(drop=True))
    q = predict_quantiles(model, band, rows)
    priors = {sid: q[(rows["shop_id"] == sid).to_numpy()] for sid in test_ids}
    test_cases = run_cases(test_ids, series, shops, priors, rule, GAPS, jobs)
    return {"train": train_cases, "test": test_cases, "n_train": len(train_ids), "n_test": len(test_ids)}


def evaluate(data_dir: Path = DATA_DIR, model_dir: Path = MODEL_DIR, jobs: int = -1, reuse: bool = False) -> dict:
    rule = get_rules().blend
    cache = data_dir / "reforecast_cases.joblib"
    if reuse and cache.is_file():
        cases = joblib.load(cache)
    else:
        cases = build_cases(data_dir, model_dir, jobs)
        joblib.dump(cases, cache, compress=3)
    train, test = pick(cases["train"]), cases["test"]

    # ---- tuning, TRAINING shops only: k by lowest WAPE, then for every k the band multiplier nearest 80% coverage ----
    k_cv = {k: score(train, rule, k, 1.0)["wape_blend"] for k in K_GRID}
    k_best = min(k_cv, key=k_cv.get)
    scale_for, scale_cov = {}, {}
    for k in K_GRID:
        cov = {s: score(train, rule, k, s)["coverage_blend"] for s in SCALE_GRID}
        scale_for[k] = min(cov, key=lambda s: (abs(cov[s] - COVERAGE_TARGET), s))
        scale_cov[k] = cov[scale_for[k]]

    # ---- scoring, TEST shops ----
    by_history = {n: score(pick(test, n), rule, rule.k, rule.interval_scale) for n in HISTORY}
    per_k = {k: {n: score(pick(test, n), rule, k, scale_for[k]) for n in HISTORY} for k in K_GRID}
    gaps = {g: {n: score(pick(test, n, g), rule, rule.k, rule.interval_scale) for n in HISTORY} for g in GAPS}
    models = pd.Series([c["ctx"]["own_model"] for c in pick(test)]).value_counts().to_dict()
    rescale = np.array([c["ctx"]["rescale"] for c in pick(test)])
    return {"is_synthetic": True, "rule": {"k": rule.k, "interval_scale": rule.interval_scale},
            "shops": {"train_tuning": cases["n_train"], "test": cases["n_test"]},
            "tuning": {"k_cv_wape": k_cv, "k_best": k_best, "scale_for_k": scale_for, "scale_train_coverage": scale_cov},
            "test": {"by_history": by_history, "per_k": per_k, "gaps": gaps, "own_models": models,
                     "rescale_at_min": float((rescale <= rule.error_rescale_min).mean()),
                     "rescale_at_max": float((rescale >= rule.error_rescale_max).mean())},
            "targets": {f"blend_beats_prior_at_{n}_months": by_history[n]["wape_blend"] < by_history[n]["wape_prior"]
                        for n in (2, 3)}}


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render(r: dict) -> str:
    t, tu = r["test"], r["tuning"]
    ok = all(r["targets"].values())
    lines = [
        "## ML3 re-forecast (M-06)", "",
        ("**All data here is SYNTHETIC (`is_synthetic=true`).** This backtest checks the method and the code. It says "
        "nothing about accuracy on real shops."), "",
        (f"- Rolling origin: forecast made at the end of month 1, 2 and 3 (about 30, 60 and 90 days of history), scored on "
        f"the next {AHEAD} full months. Only days up to the origin are given to the model."),
        (f"- Shops: {r['shops']['test']} held-out TEST shops for scoring; {r['shops']['train_tuning']} TRAINING shops "
        "(seeded sample) for tuning, with out-of-fold ML2 priors."),
        (f"- Settings scored (from `data/rules/blend.yaml`): k = {r['rule']['k']:g}, band multiplier = "
        f"{r['rule']['interval_scale']:g}."), "",
        "### Target", "",
        (f"Blend WAPE lower than prior-only after 2 months of history: **{'MET' if ok else 'NOT MET'}** "
        f"(2 months: {'yes' if r['targets']['blend_beats_prior_at_2_months'] else 'no'}; "
        f"3 months: {'yes' if r['targets']['blend_beats_prior_at_3_months'] else 'no'})."), "",
        "### WAPE and coverage on TEST shops (no gaps)", "",
        "| History | Shop-months | Blend WAPE | Prior only | ETS only | Last-week naive | Blend P10-P90 coverage | Prior coverage | Blend width | Prior width |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for n, s in t["by_history"].items():
        lines.append(f"| {n} month(s) | {s['shop_months']} | {_pct(s['wape_blend'])} | {_pct(s['wape_prior'])} | "
                     f"{_pct(s['wape_ets'])} | {_pct(s['wape_naive'])} | {_pct(s['coverage_blend'])} | "
                     f"{_pct(s['coverage_prior'])} | {_pct(s['width_blend'])} | {_pct(s['width_prior'])} |")
    lines += ["", "Width = (P90 - P10) / P50, averaged. Own models fitted: "
              + ", ".join(f"{k} x {v}" for k, v in t["own_models"].items()) + ".", "",
              (f"Band rescale by the observed error: at its lower limit for {_pct(t['rescale_at_min'])} of the test cases, "
              f"at its upper limit for {_pct(t['rescale_at_max'])}."), "",
              "### Choice of k (TRAINING shops only) and sensitivity", "",
              (f"On training shops (all three origins pooled) the lowest blend WAPE is at **k = {tu['k_best']}**. For every k "
              "the band multiplier is the one whose TRAINING coverage is closest to 80%. The TEST columns only show how "
              "each setting behaves; nothing was chosen on test shops."), "",
              "| k | Training WAPE | Band multiplier (training) | Test WAPE, 1 month | 2 months | 3 months | Test coverage, 1 month | 2 months | 3 months | Test width, 2 months |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for k, d in t["per_k"].items():
        mark = " (lowest training WAPE)" if k == tu["k_best"] else ""
        mark += " (in blend.yaml)" if k == r["rule"]["k"] else ""
        lines.append(f"| {k}{mark} | {_pct(tu['k_cv_wape'][k])} | {tu['scale_for_k'][k]:g} | "
                     + " | ".join(_pct(d[n]["wape_blend"]) for n in HISTORY) + " | "
                     + " | ".join(_pct(d[n]["coverage_blend"]) for n in HISTORY) + f" | {_pct(d[2]['width_blend'])} |")
    lines += ["", "### Missing days (TEST shops, days removed at random from the history)", "",
              "| Days missing | Blend WAPE, 1 month | 2 months | 3 months | Blend coverage, 2 months | Prior-only WAPE, 2 months |",
              "|---|---|---|---|---|---|"]
    for g, d in t["gaps"].items():
        lines.append(f"| {round(100 * g)}% | " + " | ".join(_pct(d[n]["wape_blend"]) for n in HISTORY)
                     + f" | {_pct(d[2]['coverage_blend'])} | {_pct(d[2]['wape_prior'])} |")
    lines += ["", ("Missing days are skipped by the model (never counted as zero sales). Above 30% missing the service "
              "returns confidence `low` with the reason."), ""]
    notes = Path(__file__).with_name("reforecast_notes.md")
    if notes.is_file():
        lines += ["### Notes and honest reading", "", notes.read_text(encoding="utf-8").strip(), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--models", type=Path, default=MODEL_DIR)
    ap.add_argument("--jobs", type=int, default=-1)
    ap.add_argument("--reuse", action="store_true", help="score the saved fits again instead of refitting")
    ap.add_argument("--write", action="store_true", help="write eval/report_parts/ml3_reforecast.md and refresh docs/EVAL_REPORT.md")
    args = ap.parse_args(argv)
    r = evaluate(args.data, args.models, args.jobs, args.reuse)
    text = render(r)
    print(text)
    if args.write:
        write_part("ml3_reforecast", text)
        refresh_report()
        print("\nwrote the ML3 part and refreshed docs/EVAL_REPORT.md")


if __name__ == "__main__":
    main()
