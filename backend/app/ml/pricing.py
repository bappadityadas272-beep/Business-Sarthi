"""ML10 pricing helper (M-11, DEC-89). Pure margin arithmetic: no HTTP, no database, no model.

Per category with items:
- margin = (revenue - cost of goods) / revenue over the items' sales in the last `window_days` (basis `sales`);
  a category with no sales in the window uses the plain mean of its items' list margins (basis `list_prices`).
- target = `target_margins[category]` from data/rules/pricing.yaml (an ASSUMPTION: midpoints of the assumed ranges).
- below target -> flagged, with the average price rise that would reach the target if costs stay the same and the
  same quantities still sell (they may not: demand may react), and each item below target with its target price
  = cost / (1 - target).
"""
from datetime import date, timedelta

from app.rules import Pricing


def item_margin(cost: float, price: float) -> float:
    return (price - cost) / price


def target_price(cost: float, target: float) -> float:
    return round(cost / (1 - target), 2)


def analyse(items: list[dict], moves: list[dict], today: date, rule: Pricing) -> list[dict]:
    """`items`: id, name, category, cost, price. `moves`: item_id, day, qty (sales negative), kind."""
    first = today - timedelta(days=rule.window_days)
    sold: dict[int, float] = {}
    for m in moves:
        if m["kind"] == "sale" and first <= m["day"] < today:
            sold[m["item_id"]] = sold.get(m["item_id"], 0.0) - m["qty"]
    out = []
    for cat, target in rule.target_margins.items():
        its = [i for i in items if i["category"] == cat and i["price"] > 0]
        if not its:
            continue
        revenue = sum(sold.get(i["id"], 0.0) * i["price"] for i in its)
        cogs = sum(sold.get(i["id"], 0.0) * i["cost"] for i in its)
        if revenue > 0:
            margin, basis = (revenue - cogs) / revenue, "sales"
            needed_rise = cogs / (1 - target) / revenue - 1
        else:
            margin, basis = sum(item_margin(i["cost"], i["price"]) for i in its) / len(its), "list_prices"
            needed_rise = sum(target_price(i["cost"], target) / i["price"] - 1 for i in its) / len(its)
        below = margin < target
        low_items = sorted(
            ({"id": i["id"], "name": i["name"], "cost": i["cost"], "price": i["price"],
              "margin": round(item_margin(i["cost"], i["price"]), 4), "target_price": target_price(i["cost"], target),
              "sold_qty": round(sold.get(i["id"], 0.0), 3)}
             for i in its if item_margin(i["cost"], i["price"]) < target),
            key=lambda x: (-x["sold_qty"], x["margin"], x["id"]))
        out.append({"category": cat, "target_margin": target, "margin": round(margin, 4), "basis": basis,
                    "revenue": round(revenue), "items": len(its), "below_target": below,
                    "gap_points": round((target - margin) * 100, 1) if below else 0.0,
                    "price_rise_pct": round(needed_rise * 100, 1) if below else 0.0,
                    "items_below_target": low_items})
    return out
