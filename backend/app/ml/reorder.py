"""Stock advice (M-07, ML_PLAN section 6). Pure functions: no HTTP and no database.

    demand         = exponentially weighted mean of daily unit sales (half-life in data/rules/stock.yaml);
                     a new item uses the average of the shop's other items in the same category
    reorder point  = mean x lead_time + z x std x sqrt(lead_time)
    reorder qty    = cover_days x mean - on hand (never below zero)
    dead stock     = on hand > 0 and no sale for `dead_no_sale_days`
    overstock      = on hand above `overstock_cover_days` of demand
    ABC            = top `abc_a_share` of items by revenue are A, the next `abc_b_share` are B, the rest C

Days with no sale move count as ZERO sales for that item (unlike the daily sales log, where a missing day is missing).
Days on which the item ended at zero are left out of the demand estimate (`ignore_empty_shelf_days`, DEC-59): what was
sold on such a day is less than what could have been sold. On-order stock is not known to the app, so the reorder
list repeats an item until its purchase is recorded.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

from app.rules import Stock

ABC_ORDER = {"A": 0, "B": 1, "C": 2}


def ewm_mean(x, halflife: float) -> float:
    """Exponentially weighted mean; the newest value has weight 1, a value `halflife` days older has weight 0.5."""
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return 0.0
    w = 0.5 ** (np.arange(x.size - 1, -1, -1) / halflife)
    return float((w * x).sum() / w.sum())


def demand_stats(units, rule: Stock) -> tuple[float, float]:
    """(mean, std) of daily demand from daily unit sales, oldest first."""
    x = np.asarray(units, dtype=float)
    tail = x[-rule.std_window_days:]
    return ewm_mean(x, rule.demand_halflife_days), float(tail.std(ddof=1)) if tail.size > 1 else 0.0


def reorder_point(mean: float, std: float, rule: Stock, lead_time_days: float | None = None) -> float:
    lead = rule.lead_time_days if lead_time_days is None else lead_time_days
    return mean * lead + rule.z * std * math.sqrt(lead)


def reorder_quantity(mean: float, on_hand: float, rule: Stock) -> float:
    return max(0.0, rule.cover_days * mean - on_hand)


def abc_tags(revenue: dict[int, float], rule: Stock) -> dict[int, str]:
    """A = top `abc_a_share` of items by revenue (rounded up), B = the next `abc_b_share`, C = the rest.
    An item with no revenue is always C. Ties go to the lower item id."""
    ranked = sorted(revenue, key=lambda i: (-revenue[i], i))
    n = len(ranked)
    n_a = math.ceil(rule.abc_a_share * n - 1e-9)
    n_ab = math.ceil((rule.abc_a_share + rule.abc_b_share) * n - 1e-9)
    out = {}
    for pos, i in enumerate(ranked):
        out[i] = "C" if revenue[i] <= 0 or pos >= n_ab else ("A" if pos < n_a else "B")
    return out


def advise(items: list[dict], moves: list[dict], today: date, rule: Stock) -> dict:
    """`items`: id, name, category, unit, cost, price. `moves`: item_id, day, qty (signed), kind.
    Demand uses finished days only (up to yesterday); on-hand includes every move up to `today`."""
    yesterday = today - timedelta(days=1)
    by_item: dict[int, list[dict]] = defaultdict(list)
    for m in moves:
        if m["day"] <= today:
            by_item[m["item_id"]].append(m)

    rows, own = [], {}
    for it in items:
        mv = by_item.get(it["id"], [])
        on_hand = float(sum(m["qty"] for m in mv))
        first = min((m["day"] for m in mv), default=None)
        history_days = (today - first).days if first else 0
        sale_days = [m["day"] for m in mv if m["kind"] == "sale"]
        last_sale = max(sale_days, default=None)
        n = (yesterday - first).days + 1 if first and first <= yesterday else 0
        sold, delta = np.zeros(n), np.zeros(n)
        for m in mv:
            i = (m["day"] - first).days
            if i < n:
                delta[i] += m["qty"]
                if m["kind"] == "sale":
                    sold[i] += -m["qty"]
        end_of_day = np.cumsum(delta)
        idle_since = last_sale or first
        idle_days = (today - idle_since).days if idle_since else None
        active = last_sale is not None and (today - last_sale).days < rule.dead_no_sale_days
        # an item counts only while it is active (sold within `dead_no_sale_days` of today): see DEC-58
        out_mask = (end_of_day[-rule.stockout_window_days:] <= 1e-9) if active else np.zeros(0, dtype=bool)
        out_days = int(out_mask.sum())
        if history_days >= rule.new_item_below_days:
            counted = sold[end_of_day > 1e-9] if rule.ignore_empty_shelf_days else sold
            own[it["id"]] = demand_stats(counted if counted.size else sold, rule)
        rows.append({"it": it, "on_hand": on_hand, "history_days": history_days, "idle_days": idle_days,
                     "last_sale": last_sale, "stockout_days": out_days, "out_mask": out_mask,
                     "revenue": float(sold[-rule.abc_window_days:].sum()) * it["price"]})

    by_cat: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        if r["it"]["id"] in own:
            by_cat[r["it"]["category"]].append(own[r["it"]["id"]])
    tags = abc_tags({r["it"]["id"]: r["revenue"] for r in rows}, rule)

    out = []
    for r in rows:
        it, on_hand = r["it"], r["on_hand"]
        if it["id"] in own:
            (mean, std), source = own[it["id"]], "own_sales"
        elif by_cat[it["category"]]:
            peers = by_cat[it["category"]]
            mean, std = float(np.mean([p[0] for p in peers])), float(np.mean([p[1] for p in peers]))
            source = "category_average"
        else:
            mean = std = None
            source = "none"
        rop = reorder_point(mean, std, rule) if mean is not None else None
        qty = reorder_quantity(mean, on_hand, rule) if mean is not None else None
        dead = on_hand > 0 and r["idle_days"] is not None and r["idle_days"] >= rule.dead_no_sale_days
        over = (not dead) and mean is not None and mean > 0 and on_hand > rule.overstock_cover_days * mean
        out.append({
            "item_id": it["id"], "name": it["name"], "category": it["category"], "unit": it["unit"],
            "abc": tags[it["id"]], "on_hand": round(on_hand, 3), "stock_value": round(on_hand * it["cost"], 2),
            "demand_source": source, "history_days": r["history_days"],
            "mean_daily_demand": None if mean is None else round(mean, 3),
            "std_daily_demand": None if std is None else round(std, 3),
            "reorder_point": None if rop is None else round(rop, 3),
            "reorder_now": bool(rop is not None and not dead and on_hand <= rop and qty > 0),
            "reorder_qty": None if qty is None else round(qty, 3),
            "cover_days": round(on_hand / mean, 1) if mean else None,
            "days_since_last_sale": (today - r["last_sale"]).days if r["last_sale"] else None,
            "dead_stock": bool(dead), "overstock": bool(over), "stockout_days": r["stockout_days"]})

    width = max((len(r["out_mask"]) for r in rows), default=0)
    any_out = np.zeros(width, dtype=bool)
    for r in rows:
        if len(r["out_mask"]):
            any_out[width - len(r["out_mask"]):] |= r["out_mask"]
    reorder = sorted((o for o in out if o["reorder_now"]),
                     key=lambda o: (ABC_ORDER[o["abc"]], o["cover_days"] if o["cover_days"] is not None else 0.0, o["item_id"]))
    return {"as_of": today, "items": out, "reorder_list": [o["item_id"] for o in reorder],
            "dead_stock_value": round(sum(o["stock_value"] for o in out if o["dead_stock"]), 2),
            "overstock_value": round(sum(o["stock_value"] for o in out if o["overstock"]), 2),
            "stockout_days": int(any_out.sum()), "window_days": rule.stockout_window_days}
