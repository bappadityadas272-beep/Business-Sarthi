"""ML5 review engine (ML_PLAN section 7): indicators from the last 90 days, then the decision table.

Pure functions: plain values in, a dict out. Nothing here reads the database or the clock, and no LLM is involved.
The decision table and every threshold live in data/rules/review_rules.yaml; actions in data/rules/actions.yaml.

Definitions (DEC-64 to DEC-66):
- Period: the `window_days` (90) days ending on `period_end` (the last FINISHED day). Days before the launch date are
  not expected. Three 30-day blocks are counted back from `period_end`; block 3 is the most recent.
- A day without a log is missing, not zero. Sales and purchases are scaled up for unlogged days
  (x expected days / logged days); expenses are taken as logged, because rent and wages are entered once a month.
- operating profit per month = [(sales - purchases) x expected / logged - expenses] x 30 / expected.
  Only logged costs count (DEC-64): if the owner logs no expenses, the profit is overstated and a note says so.
- dscr = operating profit per month / total monthly EMI. No loan: dscr is null; a condition marked
  `pass_when_no_loan` then counts as satisfied (DEC-64). "for 2 months" = the 2 most recent blocks both satisfy it.
- revenue_vs_p50 = logged sales / forecast P50 of the SAME logged days (so missing days do not look like poor sales).
- cash_runway_days = cash / average daily net outflow, only when the net flow of the period is negative; else null.
  Net flow per day = operating profit per day - monthly EMI / 30. Cash unknown: null and the rule is skipped.
- growth_rate = least-squares slope of the blocks' average daily sales, divided by their mean (share per month).
- Indicators are rounded first (4 decimals; runway 1 decimal) and the rules are applied to the rounded values, so what
  the owner sees is exactly what was judged.
- An unknown indicator never satisfies a condition (apart from `pass_when_no_loan`).
- confidence is never above `medium`: the thresholds are untested assumptions.
"""
from datetime import date, timedelta

import numpy as np

from app.rules import Actions, Condition, ReviewRules

BLOCK_DAYS = 30
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b}


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(float(x), nd)


def _sums(logs: dict, first: date, last: date) -> tuple[int, float, float, float]:
    """(logged days, sales, purchases, expenses) between two dates, both included."""
    rows = [v for d, v in logs.items() if first <= d <= last]
    return (len(rows), sum(r["sales"] for r in rows), sum(r["purchases"] for r in rows),
            sum(r["expenses"] for r in rows))


def _profit_per_day(n_log: int, n_exp: int, s: float, p: float, e: float) -> float | None:
    if n_log == 0 or n_exp == 0:
        return None
    return ((s - p) * n_exp / n_log - e) / n_exp


def _p50_by_day(months: list[dict] | None) -> dict[date, float]:
    out = {}
    for m in months or []:
        n = (m["end"] - m["start"]).days + 1
        for k in range(n):
            out[m["start"] + timedelta(days=k)] = m["p50"] / n
    return out


def indicators(*, period_end: date, window_days: int, min_block_logged_days: int, logs: dict[date, dict],
               forecast_months: list[dict] | None, monthly_emi: float | None, cash: float | None,
               stockout_days: int | None, dead_stock_value: float | None, launch_date: date | None) -> dict:
    """`logs`: {day: {"sales", "purchases", "expenses"}}. `monthly_emi` None = no loan. `cash` None = unknown.
    Returns the indicators plus the working figures the review shows (blocks, days, period)."""
    start = period_end - timedelta(days=window_days - 1)
    first = max(start, launch_date) if launch_date else start
    n_exp = max((period_end - first).days + 1, 0)
    n_log, s, p, e = _sums(logs, first, period_end) if n_exp else (0, 0.0, 0.0, 0.0)

    p50 = _p50_by_day(forecast_months)
    cov = [d for d in logs if first <= d <= period_end and d in p50]
    p50_sum = sum(p50[d] for d in cov)
    revenue_vs_p50 = sum(logs[d]["sales"] for d in cov) / p50_sum if p50_sum > 0 else None

    profit_day = _profit_per_day(n_log, n_exp, s, p, e)
    profit_month = None if profit_day is None else profit_day * BLOCK_DAYS
    emi = monthly_emi if monthly_emi is not None and monthly_emi > 0 else None      # None: no loan
    has_loan = emi is not None
    dscr = profit_month / emi if emi is not None and profit_month is not None else None

    blocks = []
    for k in range(window_days // BLOCK_DAYS, 0, -1):                              # oldest first
        b_last = period_end - timedelta(days=(k - 1) * BLOCK_DAYS)
        b_first = max(b_last - timedelta(days=BLOCK_DAYS - 1), first)
        bn_exp = max((b_last - b_first).days + 1, 0)
        bn, bs, bp, be = _sums(logs, b_first, b_last) if bn_exp else (0, 0.0, 0.0, 0.0)
        usable = bn >= min_block_logged_days
        b_profit = _profit_per_day(bn, bn_exp, bs, bp, be) if usable else None
        blocks.append({
            "start": b_first.isoformat() if bn_exp else None, "end": b_last.isoformat() if bn_exp else None,
            "days_expected": bn_exp, "days_logged": bn, "avg_daily_sales": _r(bs / bn, 2) if usable else None,
            "operating_profit": _r(b_profit * BLOCK_DAYS, 2) if b_profit is not None else None,
            "dscr": _r(b_profit * BLOCK_DAYS / emi) if emi is not None and b_profit is not None else None})

    net_day = None if profit_day is None else profit_day - (emi / BLOCK_DAYS if emi is not None else 0.0)
    runway = None
    if cash is not None and net_day is not None and net_day < 0:
        runway = max(cash, 0.0) / -net_day

    known = [(i, b["avg_daily_sales"]) for i, b in enumerate(blocks) if b["avg_daily_sales"] is not None]
    growth = None
    if len(known) >= 2:
        x, y = np.array([k[0] for k in known], dtype=float), np.array([k[1] for k in known], dtype=float)
        if y.mean() > 0:
            growth = float(np.polyfit(x, y, 1)[0] / y.mean())

    return {
        "revenue_vs_p50": _r(revenue_vs_p50), "gross_margin": _r((s - p) / s) if s > 0 else None, "dscr": _r(dscr),
        "cash_runway_days": _r(runway, 1), "growth_rate": _r(growth), "stockout_days": stockout_days,
        "dead_stock_value": _r(dead_stock_value, 2), "data_completeness": _r(n_log / n_exp) if n_exp else 0.0,
        # working figures (not used by the decision table directly, except dscr_by_month)
        "dscr_by_month": [b["dscr"] for b in blocks], "blocks": blocks, "has_loan": has_loan,
        "monthly_emi": _r(emi, 2) if emi is not None else None, "cash": _r(cash, 2),
        "operating_profit_per_month": _r(profit_month, 2), "net_cash_flow_per_day": _r(net_day, 2),
        "days_expected": n_exp, "days_logged": n_log, "sales": _r(s, 2), "purchases": _r(p, 2), "expenses": _r(e, 2),
        "period_start": first.isoformat() if n_exp else start.isoformat(), "period_end": period_end.isoformat()}


def holds(cond: Condition, ind: dict) -> bool:
    """Does the condition hold? Unknown values never do, except `pass_when_no_loan` on a shop without a loan."""
    if cond.pass_when_no_loan and not ind["has_loan"]:
        return True
    if cond.for_months:
        recent = ind[f"{cond.indicator}_by_month"][-cond.for_months:]
        return len(recent) == cond.for_months and all(v is not None and OPS[cond.op](v, cond.value) for v in recent)
    v = ind[cond.indicator]
    return v is not None and OPS[cond.op](v, cond.value)


def _reason(cond: Condition, ind: dict, decision: str, ok: bool) -> dict:
    """One reason: which indicator, its value, the threshold and whether the condition held. Keys, not sentences."""
    out = {"indicator": cond.indicator, "value": ind[cond.indicator], "op": cond.op, "threshold": cond.value,
           "holds": ok, "message_key": f"reason.{decision}.{cond.indicator}"}
    if cond.for_months:
        out["for_months"] = cond.for_months
        out["values_by_month"] = ind[f"{cond.indicator}_by_month"][-cond.for_months:]
    return out


def decide(ind: dict, rule: ReviewRules) -> tuple[str, list[dict]]:
    """First matching decision wins. Reasons: for pivot and grow the conditions that triggered it; for hold the grow
    conditions that failed (data completeness first, because it explains the others). At most 3."""
    for d in rule.decisions:
        results = [(c, holds(c, ind)) for c in d.conditions]
        if d.match == "any" and any(ok for _, ok in results):
            return d.decision, [_reason(c, ind, d.decision, True) for c, ok in results if ok][:3]
        if d.match == "all" and all(ok for _, ok in results):
            applicable = [c for c, _ in results if not (c.pass_when_no_loan and not ind["has_loan"])]
            return d.decision, [_reason(c, ind, d.decision, True) for c in applicable][:3]
        if d.match == "always":
            grow = next(g for g in rule.decisions if g.decision == "grow")
            failed = [c for c in grow.conditions if not holds(c, ind)]
            failed.sort(key=lambda c: c.indicator != "data_completeness")          # stable: completeness first
            return d.decision, [_reason(c, ind, d.decision, False) for c in failed][:3]
    raise AssertionError("review_rules.yaml has no fallback decision")              # the loader forbids this


def pick_actions(decision: str, ind: dict, actions: Actions, max_actions: int) -> list[dict]:
    """Actions for this decision whose trigger holds, by priority then file order."""
    hit = [(a.priority, i, a) for i, a in enumerate(actions.actions) if decision in a.decisions and holds(a.trigger, ind)]
    return [{"id": a.id, "message_key": a.message_key} for _, _, a in sorted(hit, key=lambda t: t[:2])][:max_actions]


def review(*, period_end: date, rule: ReviewRules, actions: Actions, logs: dict[date, dict],
           forecast_months: list[dict] | None, monthly_emi: float | None, cash: float | None,
           stockout_days: int | None = None, dead_stock_value: float | None = None,
           launch_date: date | None = None) -> dict:
    ind = indicators(period_end=period_end, window_days=rule.window_days,
                     min_block_logged_days=rule.min_block_logged_days, logs=logs, forecast_months=forecast_months,
                     monthly_emi=monthly_emi, cash=cash, stockout_days=stockout_days,
                     dead_stock_value=dead_stock_value, launch_date=launch_date)
    decision, reasons = decide(ind, rule)

    notes = []
    if not ind["has_loan"]:
        notes.append("no_loan_dscr_not_applicable")
    if cash is None:
        notes.append("cash_unknown_runway_rule_skipped")
    elif cash <= 0 and ind["cash_runway_days"] is None:
        notes.append("cash_negative_check_opening_cash")
    if ind["days_logged"] and ind["expenses"] == 0:
        notes.append("no_expenses_logged_profit_overstated")

    low = []
    if ind["data_completeness"] < rule.min_completeness_for_medium_confidence:
        low.append("low_data_completeness")
    if ind["revenue_vs_p50"] is None:
        low.append("no_forecast_to_compare")
    if ind["has_loan"] and ind["dscr"] is None:
        low.append("dscr_unknown")
    return {"period_start": date.fromisoformat(ind["period_start"]), "period_end": period_end, "decision": decision,
            "indicators": ind, "reasons": reasons,
            "actions": pick_actions(decision, ind, actions, rule.max_actions),
            "confidence": "low" if low else "medium", "confidence_reasons": low,
            "data_completeness": ind["data_completeness"], "notes": notes, "is_estimate": True}
