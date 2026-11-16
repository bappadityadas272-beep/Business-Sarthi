"""M-07 stock simulation on SYNTHETIC shops: the reorder rule of app/ml/reorder.py against "reorder when empty".

    make eval-stock                                   # inside the backend container; updates docs/EVAL_REPORT.md
    cd backend && python ../eval/stock_eval.py        # print only

Set-up (assumptions, see DEC-57 and DEC-58):
- The synthetic data has no items, so each category of a shop is ONE item and its daily sales in rupees are the demand.
- Both policies see only what they sold (demand lost during a stock-out is invisible) and use the same demand estimate.
  Days that ended with an empty shelf are left out of that estimate (DEC-59); the older variant is shown as a
  sensitivity.
- An order placed at the end of day t arrives before opening on day t + 1 + lead time.
- Our rule orders when on hand + on order <= reorder point; quantity = cover x mean - (on hand + on order).
- The baseline orders the same cover x mean, but only when the shelf is empty and nothing is on order.
- The demand half-life (7 or 14 days) is chosen on the CALIBRATION shops of the ML2 split; results are reported on TEST shops.
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

from joblib import Parallel, delayed
from parts import refresh_report, write_part

from app.ml.reorder import ewm_mean, reorder_point, reorder_quantity
from app.ml.train import DATA_DIR, MODEL_DIR
from app.rules import Stock, get_rules

HALFLIVES = (7.0, 14.0)
WARMUP = 28                      # days not scored: both policies start from the same opening stock
SIMILAR_STOCK = 1.10             # "similar stock" when choosing the half-life: within 10%
MAX_STOCK_RATIO = 1.25           # ML_PLAN target: average stock at most 25% above the baseline


def simulate(demand: np.ndarray, rule: Stock, policy: str, halflife: float, *, skip_empty_days: bool = False) -> dict:
    """One item, day by day. Returns per-day arrays after the warm-up."""
    lead, decay = rule.lead_time_days, 0.5 ** (1.0 / halflife)
    n = len(demand)
    on_hand = rule.cover_days * float(demand[:7].mean())           # same opening stock for both policies
    on_order, num, den = 0.0, 0.0, 0.0
    arrivals = np.zeros(n + lead + 2)
    seen: list[float] = []
    end, lost = np.zeros(n), np.zeros(n)
    for t in range(n):
        if arrivals[t]:
            on_hand += arrivals[t]
            on_order -= arrivals[t]
        sold = min(float(demand[t]), on_hand)
        on_hand -= sold
        lost[t] = demand[t] - sold
        end[t] = on_hand
        if not (skip_empty_days and on_hand <= 1e-9):               # optionally ignore days that ended empty
            num, den = num * decay + sold, den * decay + 1.0
            seen.append(sold)
        mean = num / den if den else 0.0
        tail = seen[-rule.std_window_days:]
        std = float(np.std(tail, ddof=1)) if len(tail) > 1 else 0.0
        qty = 0.0
        if policy == "rule":
            position = on_hand + on_order
            if position <= reorder_point(mean, std, rule) * (1 + 1e-9):      # tolerance for float rounding
                qty = reorder_quantity(mean, position, rule)
        elif on_hand <= 1e-9 and on_order <= 1e-9:                  # "reorder when empty"
            qty = reorder_quantity(mean, 0.0, rule)
        if qty > 0:
            arrivals[t + 1 + lead] += qty
            on_order += qty
    s = slice(WARMUP, n)
    return {"empty": end[s] <= 1e-9, "end": end[s], "lost": lost[s], "demand": np.asarray(demand[s], dtype=float)}


def self_check(rule: Stock) -> None:
    """The running mean inside `simulate` must equal `ewm_mean` of the production module."""
    x = np.random.default_rng(1).uniform(0, 50, 40)
    num = den = 0.0
    for v in x:
        num, den = num * 0.5 ** (1 / 7) + v, den * 0.5 ** (1 / 7) + 1
    assert abs(num / den - ewm_mean(x, 7.0)) < 1e-9
    flat = simulate(np.full(120, 100.0), rule, "rule", 7.0)
    assert flat["lost"].sum() < 1e-6, "with constant demand the rule must never lose a sale"


def run_shop(shop_id: str, demand: dict[str, np.ndarray], rule: Stock) -> list[dict]:
    rows = []
    for hl in HALFLIVES:
        for skip in (False, True):
            for policy in ("rule", "empty"):
                sims = {c: simulate(d, rule, policy, hl, skip_empty_days=skip) for c, d in demand.items()}
                days = len(next(iter(sims.values()))["end"])
                any_empty = np.zeros(days, dtype=bool)
                for c, s in sims.items():
                    any_empty |= s["empty"]
                    rows.append({"shop_id": shop_id, "category": c, "halflife": hl, "skip": skip, "policy": policy,
                                 "level": "item", "days": days, "empty_days": int(s["empty"].sum()),
                                 "lost": float(s["lost"].sum()), "demand": float(s["demand"].sum()),
                                 "stock": float(s["end"].mean())})
                rows.append({"shop_id": shop_id, "category": "*", "halflife": hl, "skip": skip, "policy": policy,
                             "level": "shop", "days": days, "empty_days": int(any_empty.sum()),
                             "lost": float(sum(s["lost"].sum() for s in sims.values())),
                             "demand": float(sum(s["demand"].sum() for s in sims.values())),
                             "stock": float(sum(s["end"].mean() for s in sims.values()))})
    return rows


def load_demand(data_dir: Path, shop_ids: set[str]) -> dict[str, dict[str, np.ndarray]]:
    daily = pd.read_csv(data_dir / "daily.csv", usecols=["shop_id", "day", "category", "sales"])
    daily = daily[daily["shop_id"].isin(shop_ids)]
    out: dict[str, dict[str, np.ndarray]] = {}
    for sid, g in daily.groupby("shop_id"):
        wide = g.pivot_table(index="day", columns="category", values="sales", aggfunc="sum").sort_index().fillna(0.0)
        out[str(sid)] = {str(c): wide[c].to_numpy(dtype=float) for c in wide.columns}
    return out


def summary(df: pd.DataFrame) -> dict:
    """Totals for one policy and setting."""
    item, shop = df[df["level"] == "item"], df[df["level"] == "shop"]
    return {"item_empty_per_30": 30 * item["empty_days"].sum() / item["days"].sum(),
            "shop_empty_per_30": 30 * shop["empty_days"].sum() / shop["days"].sum(),
            "lost_share": item["lost"].sum() / item["demand"].sum(),
            "cover_days": item["stock"].sum() / (item["demand"] / item["days"]).sum(),
            "stock": item["stock"].sum()}


def table(df: pd.DataFrame, skip: bool) -> dict:
    out = {}
    for hl in HALFLIVES:
        for policy in ("rule", "empty"):
            sel = df[(df["halflife"] == hl) & (df["skip"] == skip) & (df["policy"] == policy)]
            out[(hl, policy)] = summary(sel)
    return out


def choose_halflife(val: dict) -> tuple[float, str]:
    a, b = (val[(hl, "rule")] for hl in HALFLIVES)
    fewer = HALFLIVES[0] if a["item_empty_per_30"] <= b["item_empty_per_30"] else HALFLIVES[1]
    other = HALFLIVES[1] if fewer == HALFLIVES[0] else HALFLIVES[0]
    ratio = val[(fewer, "rule")]["stock"] / val[(other, "rule")]["stock"]
    if ratio <= SIMILAR_STOCK:
        return fewer, (f"{fewer:g} days has fewer stock-out days and its average stock is {ratio:.2f}x that of "
                       f"{other:g} days (within the {SIMILAR_STOCK:.2f}x limit used for 'similar stock')")
    return other, (f"{fewer:g} days has fewer stock-out days but needs {ratio:.2f}x the stock of {other:g} days, "
                   f"above the {SIMILAR_STOCK:.2f}x limit used for 'similar stock', so {other:g} days is kept")


def fmt_rows(t: dict, hls) -> list[str]:
    lines = [("| Half-life | Policy | Item stock-out days per 30 | Shop days with any item empty per 30 | "
             "Lost sales | Average cover (days) | Average stock vs baseline |"), "|---|---|---|---|---|---|---|"]
    for hl in hls:
        base = t[(hl, "empty")]
        for policy, name in (("rule", "reorder rule"), ("empty", "reorder when empty")):
            s = t[(hl, policy)]
            lines.append(f"| {hl:g} | {name} | {s['item_empty_per_30']:.2f} | {s['shop_empty_per_30']:.2f} | "
                         f"{100 * s['lost_share']:.1f}% | {s['cover_days']:.1f} | {s['stock'] / base['stock']:.2f}x |")
    return lines


def build_report(val: dict, test: dict, test_other: dict, chosen: float, why: str, n_val: int, n_test: int,
                 rule: Stock, share_better: float) -> tuple[str, bool]:
    r, b = test[(chosen, "rule")], test[(chosen, "empty")]
    ratio = r["stock"] / b["stock"]
    fewer, within = r["item_empty_per_30"] < b["item_empty_per_30"], ratio <= MAX_STOCK_RATIO
    met = fewer and within
    lines = [
        "## ML4 stock advice (M-07)", "",
        ("**All shops are SYNTHETIC (`is_synthetic = true`).** The generator has no items: each category of a shop is "
        "simulated as one item whose demand is that category's daily sales in rupees (DEC-57). Every setting in "
        "`data/rules/stock.yaml` is an assumption."), "",
        (f"- Rule: order when on hand + on order is at or below the reorder point (z = {rule.z:g}, lead time "
        f"{rule.lead_time_days} days), quantity = {rule.cover_days} days of demand minus on hand and on order."),
        f"- Baseline: order the same {rule.cover_days} days of demand, but only when the shelf is empty (DEC-58).",
        f"- Both see only their own sales, start with the same stock, and the first {WARMUP} days are not scored.",
        "- Demand estimate: " + ("days that ended with an empty shelf are left out (DEC-59)."
                                 if rule.ignore_empty_shelf_days else "every day counts, also days with an empty shelf."),
        f"- Half-life chosen on {n_val} calibration shops of the ML2 split (not test shops); results below are for {n_test} test shops.", "",
        "### Target", "",
        f"Fewer stock-out days than the baseline, with average stock at most {MAX_STOCK_RATIO:.2f}x the baseline "
        f"(ML_PLAN section 8). **{'MET' if met else 'NOT MET'}** on synthetic shops at the chosen half-life "
        f"({chosen:g} days): item stock-out days per 30 days {r['item_empty_per_30']:.2f} against "
        f"{b['item_empty_per_30']:.2f}; average stock {ratio:.2f}x the baseline"
        + ("." if within else f", **above the {MAX_STOCK_RATIO:.2f}x limit**.")
        + f" The rule had fewer stock-out days than the baseline for {100 * share_better:.0f}% of the test items.", "",
        "### Choice of the demand half-life (calibration shops)", "",
        *fmt_rows(val, HALFLIVES), "", f"Chosen: **{chosen:g} days**: {why}.", "",
        "### TEST shops", "",
        *fmt_rows(test, HALFLIVES), "",
        "### Sensitivity: the other treatment of empty-shelf days (TEST shops)", "",
        ("Here a day that ended with an empty shelf counts as a day of low sales for both policies. This was the "
         "first version of the rule; it missed the stock limit, which is why DEC-59 changed the estimate."
         if rule.ignore_empty_shelf_days else
         "Here days that ended with an empty shelf are left out of the demand estimate for both policies."), "",
        *fmt_rows(test_other, (chosen,)), "",
    ]
    return "\n".join(lines), met


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    ap.add_argument("--write", action="store_true", help="write eval/report_parts/ml4_stock.md and refresh the report")
    args = ap.parse_args()

    rule = get_rules().stock
    self_check(rule)
    meta = json.loads((args.data_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["is_synthetic"] is True
    split = json.loads((args.model_dir / "split.json").read_text(encoding="utf-8"))
    val_ids, test_ids = set(split["calibration"]), set(split["test"])
    demand = load_demand(args.data_dir, val_ids | test_ids)
    rows = Parallel(n_jobs=-1)(delayed(run_shop)(sid, d, rule) for sid, d in sorted(demand.items()))
    df = pd.DataFrame([r for shop in rows for r in shop])
    dv, dt = df[df["shop_id"].isin(val_ids)], df[df["shop_id"].isin(test_ids)]

    main_skip = rule.ignore_empty_shelf_days
    val, test, test_other = table(dv, main_skip), table(dt, main_skip), table(dt, not main_skip)
    chosen, why = choose_halflife(val)
    items = dt[(dt["level"] == "item") & (dt["halflife"] == chosen) & (dt["skip"] == main_skip)]
    wide = items.pivot_table(index=["shop_id", "category"], columns="policy", values="empty_days")
    share_better = float((wide["rule"] < wide["empty"]).mean())

    text, met = build_report(val, test, test_other, chosen, why, len(val_ids), len(test_ids), rule, share_better)
    notes = Path(__file__).with_name("stock_notes.md")
    if notes.is_file():
        text += "### Notes and honest reading\n\n" + notes.read_text(encoding="utf-8").strip() + "\n"
    print(text)
    print(f"\nchosen half-life: {chosen:g} (data/rules/stock.yaml has {rule.demand_halflife_days:g}); target met: {met}")
    if args.write:
        if chosen != rule.demand_halflife_days:
            raise SystemExit("data/rules/stock.yaml does not use the chosen half-life: update it, then run again")
        write_part("ml4_stock", text)
        refresh_report()
        print("wrote the ML4 part and refreshed docs/EVAL_REPORT.md")


if __name__ == "__main__":
    main()
