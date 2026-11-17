"""Chat tools (C-04). Code computes every number here; the LLM only gets these outputs to explain (DEC-06).

Each tool returns plain JSON (no dates or Decimals left inside):
    {"tool", "shop_id", "as_of", "source": {"id", "label"}, "is_estimate", "note", "data", "facts": [...]}
`facts` is the flat list the guard (C-06) checks numbers against: {"key", "value", "unit", "period"} with
unit in INR | percent | ratio | days | count | units | date | label. `note` is a machine key (for example
`no_review_yet`, `no_verified_source`) or None.

Ownership: `run(db, user_id, shop_id, name, **args)` loads the shop only if it belongs to `user_id` and the owner's
shop-data consent is active (AGENTS rule 5). Anything else raises ToolAccessDenied with the same message, so a caller
cannot tell "not yours" from "does not exist".
"""
from calendar import monthrange
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, Forecast, Loan, Review, Shop, StockItem
from app.rules import get_rules
from app.services import clock, consent
from app.services import loans as loan_dates
from app.services import review as review_service
from app.services import stock as stock_service

Period = Literal["this_month", "last_month", "last_30_days", "last_90_days"]
PERIODS: tuple[str, ...] = ("this_month", "last_month", "last_30_days", "last_90_days")
MAX_ITEMS = 5                       # items listed per stock list, to keep the prompt short

SOURCES = {
    "forecast": "Your Business Sarthi forecast (an estimate, P10 to P90 range)",
    "review": "Your latest 3-month review",
    "stock": "Your stock records",
    "alerts": "Your Business Sarthi alerts",
    "daily_logs": "Your daily sales, purchase and expense logs",
    "loans": "Your loan details",
    "schemes_kb": "Business Sarthi scheme knowledge base",
}

# Units of alert params (ml/alerts.py). A param not listed here is not passed on as a fact.
ALERT_UNITS = {
    "ratio": "ratio", "drop_percent": "percent", "short_avg": "INR", "base_avg": "INR", "robust_z": "ratio",
    "short_window_days": "days", "long_window_days": "days", "short_days_logged": "days",
    "base_days_logged": "days", "count": "count", "value": "INR", "no_sale_days": "days", "emi": "INR",
    "days_to_due": "days", "cash_today": "INR", "projected_cash": "INR", "avg_daily_net_flow": "INR",
    "shortfall": "INR", "days_without_log": "days", "due_date": "date", "last_log_day": "date",
}


class ToolAccessDenied(Exception):
    """Unknown shop, another owner's shop, or no active consent. One message for all three."""

    def __init__(self):
        super().__init__("shop_not_found")


class UnknownTool(Exception):
    pass


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _fact(key: str, value, unit: str, period: str | None = None, **extra) -> dict:
    return {"key": key, "value": value, "unit": unit, "period": period, **extra}


def _out(tool: str, shop: Shop, today: date, source: str, data, facts: list[dict], *,
         is_estimate: bool = False, note: str | None = None) -> dict:
    return {"tool": tool, "shop_id": shop.id, "as_of": today.isoformat(),
            "source": {"id": source, "label": SOURCES[source]}, "is_estimate": is_estimate, "note": note,
            "data": data, "facts": [f for f in facts if f["value"] is not None]}


def load_shop(db: Session, user_id: int, shop_id: int) -> Shop:
    shop = db.get(Shop, shop_id)
    if shop is None or shop.user_id != user_id or consent.active(db, user_id, consent.SHOP_DATA) is None:
        raise ToolAccessDenied()
    return shop


# ---------------------------------------------------------------- tools

def get_forecast(db: Session, shop: Shop, today: date) -> dict:
    """The newest forecast (a re-forecast if there is one, else the setup forecast). Monthly sales in INR."""
    row = db.scalars(select(Forecast).where(Forecast.shop_id == shop.id).order_by(Forecast.id.desc())).first()
    if row is None:
        return _out("get_forecast", shop, today, "forecast", None, [], is_estimate=True, note="no_forecast")
    months = [{k: m[k] for k in ("k", "start", "end", "p10", "p50", "p90")} for m in row.horizon_months]
    facts = []
    for m in months:
        period = f"{m['start']}..{m['end']}"
        facts += [_fact(f"month_{m['k']}.sales_{q}", round(float(m[q]), 2), "INR", period, month=m["k"])
                  for q in ("p10", "p50", "p90")]
    current = next((m for m in months if m["start"] <= today.isoformat() <= m["end"]), None)
    data = {"kind": row.kind, "made_on": _iso(row.made_on), "months": months,
            "current_month": current["k"] if current else None}
    return _out("get_forecast", shop, today, "forecast", data, facts, is_estimate=True)


def get_latest_review(db: Session, shop: Shop, today: date) -> dict:
    row = db.scalars(select(Review).where(Review.shop_id == shop.id)
                     .order_by(Review.period_end.desc(), Review.id.desc())).first()
    if row is None:
        return _out("get_latest_review", shop, today, "review", None, [], is_estimate=True, note="no_review_yet")
    ind, period = row.indicators, f"{_iso(row.period_start)}..{_iso(row.period_end)}"
    units = {"operating_profit_per_month": "INR", "sales": "INR", "purchases": "INR", "expenses": "INR",
             "cash": "INR", "monthly_emi": "INR", "net_cash_flow_per_day": "INR", "dead_stock_value": "INR",
             "revenue_vs_p50": "ratio", "gross_margin": "ratio", "dscr": "ratio", "growth_rate": "ratio",
             "data_completeness": "ratio", "cash_runway_days": "days", "stockout_days": "days",
             "days_logged": "days", "days_expected": "days"}
    facts = [_fact("decision", row.decision, "label", period), _fact("confidence", row.confidence, "label", period)]
    facts += [_fact(k, ind.get(k), u, period) for k, u in units.items()]
    data = {"period_start": _iso(row.period_start), "period_end": _iso(row.period_end), "decision": row.decision,
            "confidence": row.confidence, "reviewed_on": _iso(row.created_on),
            "reasons": [{"message_key": r["message_key"], "indicator": r["indicator"], "value": r["value"],
                         "threshold": r["threshold"], "holds": r["holds"]} for r in row.reasons],
            "actions": [a["message_key"] for a in row.actions]}
    return _out("get_latest_review", shop, today, "review", data, facts, is_estimate=True)


def get_stock_advice(db: Session, shop: Shop, today: date) -> dict:
    if db.scalars(select(StockItem.id).where(StockItem.shop_id == shop.id)).first() is None:
        return _out("get_stock_advice", shop, today, "stock", None, [], note="no_stock_records")
    adv = stock_service.advice(db, shop.id, today, get_rules().stock)
    window = f"last_{adv['window_days']}_days"
    reorder = [i for i in adv["items"] if i["reorder_now"]][:MAX_ITEMS]
    dead = sorted((i for i in adv["items"] if i["dead_stock"]), key=lambda i: -i["stock_value"])[:MAX_ITEMS]
    facts = [_fact("reorder_count", len(adv["reorder_list"]), "count"),
             _fact("dead_stock_value", adv["dead_stock_value"], "INR"),
             _fact("overstock_value", adv["overstock_value"], "INR"),
             _fact("stockout_days", adv["stockout_days"], "days", window)]
    for i in reorder:
        facts += [_fact(f"reorder.{i['name']}.on_hand", i["on_hand"], "units", item=i["name"], item_unit=i["unit"]),
                  _fact(f"reorder.{i['name']}.reorder_qty", i["reorder_qty"], "units", item=i["name"],
                        item_unit=i["unit"]),
                  _fact(f"reorder.{i['name']}.cover_days", i["cover_days"], "days", item=i["name"])]
    for i in dead:
        facts += [_fact(f"dead.{i['name']}.stock_value", i["stock_value"], "INR", item=i["name"]),
                  _fact(f"dead.{i['name']}.days_since_last_sale", i["days_since_last_sale"], "days", item=i["name"])]
    data = {"reorder": [{"name": i["name"], "unit": i["unit"], "on_hand": i["on_hand"],
                         "reorder_qty": i["reorder_qty"], "cover_days": i["cover_days"]} for i in reorder],
            "dead_stock": [{"name": i["name"], "stock_value": i["stock_value"],
                            "days_since_last_sale": i["days_since_last_sale"]} for i in dead],
            "dead_stock_value": adv["dead_stock_value"], "overstock_value": adv["overstock_value"],
            "stockout_days": adv["stockout_days"], "window_days": adv["window_days"]}
    return _out("get_stock_advice", shop, today, "stock", data, facts)


def get_alerts(db: Session, shop: Shop, today: date) -> dict:
    """Open alerts (not resolved by the owner), most severe first. Numbers come from the stored params."""
    order = {"critical": 0, "warn": 1, "info": 2}
    rows = sorted(db.scalars(select(Alert).where(Alert.shop_id == shop.id, Alert.resolved.is_(False))),
                  key=lambda a: (order.get(a.severity, 9), a.id))
    alerts, facts = [], []
    for a in rows:
        alerts.append({"id": a.id, "kind": a.kind, "severity": a.severity, "message_key": a.message_key,
                       "raised_on": _iso(a.raised_on), "still_active": a.cleared_on is None,
                       "cleared_on": _iso(a.cleared_on)})
        params = a.params or {}
        for k, v in params.items():
            if k in ALERT_UNITS and isinstance(v, int | float | str) and not isinstance(v, bool):
                facts.append(_fact(f"alert.{a.kind}.{k}", v, ALERT_UNITS[k], alert_id=a.id))
        items = params.get("items")
        for it in items if isinstance(items, list) else []:
            name = it.get("name") if isinstance(it, dict) else it
            if isinstance(name, str) and name:
                facts.append(_fact(f"alert.{a.kind}.item", name, "label", alert_id=a.id))
    facts.insert(0, _fact("open_alert_count", len(alerts), "count"))
    return _out("get_alerts", shop, today, "alerts", {"alerts": alerts}, facts)


def period_bounds(period: str, today: date) -> tuple[date, date]:
    """Inclusive (first, last) day. Every period ends yesterday at the latest: today is not logged yet (DEC-77)."""
    yesterday = today - timedelta(days=1)
    if period == "this_month":
        return today.replace(day=1), yesterday
    if period == "last_month":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if period == "last_30_days":
        return today - timedelta(days=30), yesterday
    if period == "last_90_days":
        return today - timedelta(days=90), yesterday
    raise ValueError(f"unknown period {period!r}")


def get_profit_summary(db: Session, shop: Shop, today: date, period: str = "this_month") -> dict:
    """Logged sales - purchases - expenses in the period (operating profit). EMI is shown next to it, not subtracted
    (DEC-77). Only logged days count; nothing is extrapolated."""
    first, last = period_bounds(period, today)
    label = f"{_iso(first)}..{_iso(last)}"
    if last < first:                                         # the 1st of the month: nothing logged yet
        return _out("get_profit_summary", shop, today, "daily_logs",
                    {"period": period, "start": _iso(first), "end": _iso(last), "days_logged": 0}, [],
                    note="period_empty")
    logs = {d: v for d, v in review_service.daily_logs(db, shop.id, last).items() if d >= first}
    s, p, e = (round(sum(v[k] for v in logs.values()), 2) for k in ("sales", "purchases", "expenses"))
    days_in = (last - first).days + 1
    loans = list(db.scalars(select(Loan).where(Loan.shop_id == shop.id)))
    monthly_emi = round(sum(ln.emi for ln in loans), 2) if loans else None
    emi_in_period = round(sum(ln.emi * sum(first <= d <= last for d in loan_dates.schedule(
        ln.start_date, ln.due_day, ln.tenure_months)) for ln in loans if ln.start_date and ln.tenure_months), 2)
    note = None if logs else "no_logs_in_period"
    facts = [_fact("sales", s, "INR", label), _fact("purchases", p, "INR", label),
             _fact("expenses", e, "INR", label), _fact("operating_profit", round(s - p - e, 2), "INR", label),
             _fact("gross_margin", round((s - p) / s, 4) if s > 0 else None, "ratio", label),
             _fact("days_logged", len(logs), "days", label), _fact("days_in_period", days_in, "days", label)]
    if loans:
        facts += [_fact("monthly_emi", monthly_emi, "INR"), _fact("emi_due_in_period", emi_in_period, "INR", label)]
    data = {"period": period, "start": _iso(first), "end": _iso(last), "sales": s, "purchases": p, "expenses": e,
            "operating_profit": round(s - p - e, 2), "days_logged": len(logs), "days_in_period": days_in,
            "monthly_emi": monthly_emi, "emi_due_in_period": emi_in_period if loans else None,
            "emi_subtracted": False, "month_days": monthrange(first.year, first.month)[1]}
    return _out("get_profit_summary", shop, today, "daily_logs", data, facts, note=note)


def match_schemes(db: Session, shop: Shop, today: date, profile: dict | None = None) -> dict:
    """No verified scheme knowledge base exists yet (D-03 not built, DEC-74): never return a scheme without a
    source URL and a last_verified date (AGENTS rule 3)."""
    return _out("match_schemes", shop, today, "schemes_kb", {"schemes": [], "profile": profile or {}}, [],
                note="no_verified_source")


TOOLS = {
    "get_forecast": get_forecast, "get_latest_review": get_latest_review, "get_stock_advice": get_stock_advice,
    "get_alerts": get_alerts, "get_profit_summary": get_profit_summary, "match_schemes": match_schemes,
}


def run(db: Session, user_id: int, shop_id: int, name: str, today: date | None = None, **args) -> dict:
    if name not in TOOLS:
        raise UnknownTool(name)
    shop = load_shop(db, user_id, shop_id)
    return TOOLS[name](db, shop, today or clock.today(), **args)
