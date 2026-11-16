"""ML6 evaluation: the sales-dip alert on synthetic shops with injected dips (M-09, ML_PLAN section 8).

Run from backend/:  python ../eval/alert_eval.py [--write]

What is measured (definitions chosen by the human, DEC-61):
- Shops: the TEST shops of the ML2 split. No threshold was tuned on any shop; the numbers in alert_rules.yaml are the
  initial assumptions of ML_PLAN.
- False alarms: on test shops WITHOUT a dip in the generator, every alert is false. One alarm = one unbroken run of
  days on which the rule holds. Reported per shop per 30 days.
- Recall: one dip is injected into a copy of such a shop (all categories multiplied by 1 - depth for 14 to 30 days,
  depth 25% to 60%), several copies per shop. A dip is detected when the rule holds on at least one of its first 14
  days (the alert would be shown the next morning). The target is judged on dips of 35% or deeper; milder dips are
  reported too.
- Extra: the dips the generator itself put into some shops (30 days, 25% to 50% deep), same detection rule.
- Sensitivity: the same with 20% of the days missing at random.

The engine code is used as is (`app.ml.alerts.dip_stats` and `is_dip`), one call per shop and day.
Everything here is SYNTHETIC (is_synthetic = true); it says nothing yet about real shops.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parts import refresh_report, write_part

from app.ml.alerts import dip_stats, is_dip
from app.ml.train import DATA_DIR, MODEL_DIR
from app.rules import get_rules

SEED = 2026
COPIES = 5                     # injected dips per shop, each in its own copy of the series
DETECT_WITHIN = 14             # days
DIP_LEN = (14, 30)
DIP_DEPTH = (0.25, 0.60)
TARGET_DEPTH = 0.35
BANDS = ((0.25, 0.30), (0.30, 0.35), (0.35, 0.45), (0.45, 0.60))
MISSING_SHARE = 0.20
RECALL_TARGET, FALSE_ALARM_TARGET = 0.90, 1.0
AFTER_FESTIVAL_DAYS = 35       # an alarm starting this soon after a festival is counted as "after a festival"
NOTES = Path(__file__).with_name("alert_notes.md")


def flags(x: np.ndarray, rule, lo: int = 0, hi: int | None = None) -> np.ndarray:
    """flag[t] = the rule holds with data up to and including day t (False where there is too little history)."""
    n_s, n_b = rule.short_window_days, rule.long_window_days
    out = np.zeros(len(x), dtype=bool)
    for t in range(max(lo, n_s + n_b - 1), len(x) if hi is None else min(hi, len(x))):
        out[t] = is_dip(dip_stats(x[t - n_s + 1:t + 1], x[t - n_s - n_b + 1:t - n_s + 1]), rule)
    return out


def run_starts(f: np.ndarray) -> np.ndarray:
    return np.flatnonzero(f & ~np.concatenate(([False], f[:-1])))


def load(data_dir: Path, shop_ids: set[str]) -> dict[str, pd.Series]:
    daily = pd.read_csv(data_dir / "daily.csv", usecols=["shop_id", "day", "sales"], parse_dates=["day"])
    daily = daily[daily["shop_id"].isin(shop_ids)]
    tot = daily.groupby(["shop_id", "day"])["sales"].sum()
    out = {}
    for sid in sorted(shop_ids):
        s = tot.loc[sid].sort_index()
        out[sid] = s.reindex(pd.date_range(s.index[0], s.index[-1], freq="D"))    # a day without rows would be NaN
    return out


def festival_days() -> np.ndarray:
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "data/synthetic/config.yaml").read_text(encoding="utf-8"))
    return np.array(sorted(pd.Timestamp(d) for f in cfg["festivals"].values() if isinstance(f, dict) for d in f["dates"]), dtype="datetime64[D]")


def false_alarms(series: dict[str, pd.Series], rule, fest: np.ndarray, missing: dict | None = None) -> dict:
    first = rule.short_window_days + rule.long_window_days - 1
    alarms = days = alert_days = after_fest = shops_with = 0
    for sid, s in series.items():
        x = s.to_numpy(dtype=float).copy()
        if missing is not None:
            x[missing[sid]] = np.nan
        f = flags(x, rule)
        starts = run_starts(f)
        alarms += len(starts)
        shops_with += bool(len(starts))
        alert_days += int(f.sum())
        days += len(x) - first
        for t in starts:
            gap = (s.index[t].to_datetime64().astype("datetime64[D]") - fest).astype(int)
            after_fest += bool(((gap >= 0) & (gap <= AFTER_FESTIVAL_DAYS)).any())
    return {"shops": len(series), "alarms": alarms, "per_shop_month": 30 * alarms / days, "alert_day_share": alert_days / days,
            "after_festival": after_fest, "shops_with_alarm": shops_with, "shop_months": days / 30}


def inject(series: dict[str, pd.Series], rule, rng: np.random.Generator, missing: dict | None = None) -> pd.DataFrame:
    first = rule.short_window_days + rule.long_window_days
    rows = []
    for sid, s in series.items():
        base = s.to_numpy(dtype=float)
        for _ in range(COPIES):
            length = int(rng.integers(DIP_LEN[0], DIP_LEN[1] + 1))
            start = int(rng.integers(first + 25, len(base) - length))             # 60 days of history before the dip
            depth = float(rng.uniform(*DIP_DEPTH))
            x = base.copy()
            x[start:start + length] *= 1 - depth
            if missing is not None:
                x[missing[sid]] = np.nan
                clean = base.copy()
                clean[missing[sid]] = np.nan
            else:
                clean = base
            window = slice(start, start + DETECT_WITHIN)
            f = flags(x, rule, start, start + DETECT_WITHIN)[window]
            already = bool(flags(clean, rule, start, start + DETECT_WITHIN)[window].any())
            rows.append({"shop_id": sid, "depth": depth, "length": length, "detected": bool(f.any()),
                         "delay": int(np.argmax(f)) + 1 if f.any() else np.nan, "already": already})
    return pd.DataFrame(rows)


def native(series: dict[str, pd.Series], shops: pd.DataFrame, rule) -> pd.DataFrame:
    rows = []
    for sid, s in series.items():
        start = int((pd.Timestamp(shops.loc[sid, "latent_shock_start"]) - s.index[0]).days)
        if start < rule.short_window_days + rule.long_window_days or start + DETECT_WITHIN > len(s):
            continue
        f = flags(s.to_numpy(dtype=float), rule, start, start + DETECT_WITHIN)[start:start + DETECT_WITHIN]
        rows.append({"shop_id": sid, "depth": 1 - float(shops.loc[sid, "latent_shock_mult"]), "detected": bool(f.any()),
                     "delay": int(np.argmax(f)) + 1 if f.any() else np.nan, "already": False})
    return pd.DataFrame(rows)


def recall(df: pd.DataFrame, lo: float, hi: float = 1.0) -> dict:
    d = df[(df["depth"] >= lo) & (df["depth"] < hi) & ~df["already"]]
    return {"n": len(d), "recall": float(d["detected"].mean()) if len(d) else float("nan"),
            "delay": float(d["delay"].median()) if d["detected"].any() else float("nan")}


def band_rows(df: pd.DataFrame) -> list[str]:
    out = ["| Dip depth | Dips | Detected within 14 days | Median days until the alert |", "|---|---|---|---|"]
    for lo, hi in BANDS:
        r = recall(df, lo, hi + (1e-9 if hi == BANDS[-1][1] else 0))
        if r["n"]:
            out.append(f"| {lo:.0%} to {hi:.0%} | {r['n']} | {r['recall']:.1%} | {r['delay']:.0f} |")
    r = recall(df, TARGET_DEPTH)
    out.append(f"| **{TARGET_DEPTH:.0%} or deeper (target)** | {r['n']} | **{r['recall']:.1%}** | {r['delay']:.0f} |")
    return out


def build_report(fa: dict, inj: pd.DataFrame, nat: pd.DataFrame, fa_m: dict, inj_m: pd.DataFrame, rule) -> tuple[str, bool]:
    r = recall(inj, TARGET_DEPTH)
    met = r["recall"] >= RECALL_TARGET and fa["per_shop_month"] < FALSE_ALARM_TARGET
    rm = recall(inj_m, TARGET_DEPTH)
    lines = [
        "## ML6 alerts: sales dip (synthetic data)", "",
        "**All shops here are synthetic (`is_synthetic = true`). Nothing below is evidence about real shops.**", "",
        (f"Rule under test (`data/rules/alert_rules.yaml`, initial assumptions, not tuned): the average of the last "
        f"{rule.short_window_days} finished days is below {rule.ratio_below:.0%} of the average of the {rule.long_window_days} "
        f"days before them, **and** the robust z-score is below {rule.robust_z_below:g}. Robust z = (median of the last "
        f"{rule.short_window_days} days - median of the base days) / (1.4826 x MAD of the base days)."), "",
        "### Target", "",
        (f"Recall at least {RECALL_TARGET:.0%} on injected dips of {TARGET_DEPTH:.0%} or deeper, detected within "
        f"{DETECT_WITHIN} days, and fewer than {FALSE_ALARM_TARGET:g} false alarm per shop per month (ML_PLAN section 8; "
        f"which dips count and the 14 days were chosen by the human, DEC-61). **{'MET' if met else 'NOT MET'}** on synthetic "
        f"shops: recall {r['recall']:.1%} ({r['n']} dips), {fa['per_shop_month']:.3f} false alarms per shop per month."), "",
        "### False alarms (test shops with no dip in the generator)", "",
        ("| Shops | Shop-months scored | False alarms | Per shop per month | Shops with at least one | Days under a false alert | "
        f"Alarms starting within {AFTER_FESTIVAL_DAYS} days after a festival |"),
        "|---|---|---|---|---|---|---|",
        (f"| {fa['shops']} | {fa['shop_months']:.0f} | {fa['alarms']} | {fa['per_shop_month']:.3f} | {fa['shops_with_alarm']} | "
        f"{fa['alert_day_share']:.2%} | {fa['after_festival']} of {fa['alarms']} |"), "",
        "One alarm is one unbroken run of days on which the rule holds.", "",
        f"### Recall on injected dips ({COPIES} dips per shop, one per copy)", "",
        *band_rows(inj), "",
        (f"Dips last {DIP_LEN[0]} to {DIP_LEN[1]} days and are {DIP_DEPTH[0]:.0%} to {DIP_DEPTH[1]:.0%} deep, both drawn "
        f"evenly at random (seed {SEED}). A dip of exactly {1 - rule.ratio_below:.0%} sits on the threshold, so the two "
        "mildest rows are outside what the rule is built to catch. "
        f"{int(inj['already'].sum())} dips were left out because the unchanged series already alerted in the same window."), "",
    ]
    if len(nat):
        lines += ["### The generator's own dips (30 days long, test shops that have one)", "", *band_rows(nat)[:-1], "",
                  (f"{len(nat)} shops. These dips were not placed by this script."
                  " About half are milder than 35%; the sample is small."), ""]
    lines += [
        f"### Sensitivity: {MISSING_SHARE:.0%} of days not logged (at random)", "",
        "| Case | Recall, dips of 35% or deeper | False alarms per shop per month |", "|---|---|---|",
        f"| every day logged | {r['recall']:.1%} | {fa['per_shop_month']:.3f} |",
        f"| {MISSING_SHARE:.0%} of days missing | {rm['recall']:.1%} | {fa_m['per_shop_month']:.3f} |", "",
        "### What was not evaluated", "",
        ("Low stock, dead stock, EMI due and data gap are exact rules with no statistics; they are covered by hand-"
        "calculated unit tests (`backend/tests/test_alerts.py`), not by this simulation."), "",
    ]
    if NOTES.is_file():
        lines += ["### Notes and honest reading", "", NOTES.read_text(encoding="utf-8").strip(), ""]
    return "\n".join(lines), met


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write the report part and refresh docs/EVAL_REPORT.md")
    args = ap.parse_args()
    rule = get_rules().alerts.rules.sales_dip
    test_ids = set(json.loads((MODEL_DIR / "split.json").read_text())["test"])
    shops = pd.read_csv(DATA_DIR / "shops.csv").set_index("shop_id")
    assert bool(shops["is_synthetic"].all())
    shocked = {s for s in test_ids if bool(shops.loc[s, "latent_shock"])}
    series = load(DATA_DIR, test_ids)
    clean = {s: v for s, v in series.items() if s not in shocked}
    rng = np.random.default_rng(SEED)
    missing = {s: rng.random(len(v)) < MISSING_SHARE for s, v in clean.items()}
    fest = festival_days()
    fa = false_alarms(clean, rule, fest)
    inj = inject(clean, rule, np.random.default_rng(SEED + 1))
    nat = native({s: series[s] for s in sorted(shocked)}, shops, rule)
    fa_m = false_alarms(clean, rule, fest, missing)
    inj_m = inject(clean, rule, np.random.default_rng(SEED + 1), missing)
    text, met = build_report(fa, inj, nat, fa_m, inj_m, rule)
    print(text)
    print(f"\ntarget met: {met}")
    if args.write:
        write_part("ml6_alerts", text)
        refresh_report()
        print("wrote the ML6 part and refreshed docs/EVAL_REPORT.md")


if __name__ == "__main__":
    main()
