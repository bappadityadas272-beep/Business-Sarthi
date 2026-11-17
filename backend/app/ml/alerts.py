"""ML6 alert engine (ML_PLAN section 7). Rules plus a robust z-score; thresholds live in data/rules/alert_rules.yaml.

Pure functions: plain values in, a list of alert dicts out. Nothing here reads the database or the clock.
An alert is {"kind", "severity", "message_key", "params"}. `params` holds the numbers and names the frontend puts into
the localised message; no text with numbers is produced here (and never by the LLM).

Definitions (DEC-61 to DEC-63):
- All rules look at FINISHED days only: the last day used is yesterday. Today's log may still be incomplete.
- Sales dip: `short` = the last 7 days, `base` = the 28 days before them. Days without a log are missing, not zero.
  ratio = mean(short) / mean(base); robust z = (median(short) - median(base)) / (1.4826 x MAD(base)).
  The alert needs BOTH ratio < 0.70 and z < -2. It is skipped when too few days are logged (see MIN_SHORT, MIN_BASE).
- Low stock and dead stock come from the ML4 stock advice (`reorder.advise`), one alert per kind listing the items.
- EMI due: an instalment is due within 5 days and projected cash on the due day is below the EMI. Projected cash =
  cash today + days to the due date x average daily net cash flow of the last 28 logged days. If cash is unknown
  (the owner never entered an opening figure) there is NO EMI alert (DEC-62).
- Data gap: no daily log for the last 3 finished days or more.
"""
from datetime import date, timedelta

import numpy as np

from app.rules import AlertRuleSet

MIN_SHORT = 4          # logged days needed in the short window (of 7); assumption, DEC-63
MIN_BASE = 14          # logged days needed in the base window (of 28); assumption, DEC-63
MAX_ITEMS = 5          # items listed in a stock alert; the count says how many there are in all
MAD_TO_SIGMA = 1.4826  # makes the MAD comparable to a standard deviation for normal data
CASH_FLOW_DAYS = 28    # days of net cash flow averaged for the EMI projection; assumption, DEC-63


def _alert(kind: str, rule, params: dict) -> dict:
    return {"kind": kind, "severity": rule.severity, "message_key": rule.message_key, "params": params}


def robust_z(short: np.ndarray, base: np.ndarray) -> float:
    """(median(short) - median(base)) / (1.4826 x MAD(base)). With no spread in the base: -inf, 0 or +inf."""
    diff = float(np.median(short) - np.median(base))
    mad = float(np.median(np.abs(base - np.median(base))))
    if mad <= 0:
        return 0.0 if diff == 0 else float(np.sign(diff)) * float("inf")
    return diff / (MAD_TO_SIGMA * mad)


def dip_stats(short, base) -> dict | None:
    """Ratio and robust z for one day. `short` and `base` are daily sales with NaN for days without a log.
    None when too few days are logged or the base average is not positive."""
    s, b = np.asarray(short, dtype=float), np.asarray(base, dtype=float)
    s, b = s[~np.isnan(s)], b[~np.isnan(b)]
    if s.size < MIN_SHORT or b.size < MIN_BASE or b.mean() <= 0:
        return None
    return {"ratio": float(s.mean() / b.mean()), "z": robust_z(s, b), "short_avg": float(s.mean()),
            "base_avg": float(b.mean()), "short_days_logged": int(s.size), "base_days_logged": int(b.size)}


def is_dip(stats: dict | None, rule) -> bool:
    return stats is not None and stats["ratio"] < rule.ratio_below and stats["z"] < rule.robust_z_below


def sales_dip(sales_by_day: dict[date, float], today: date, rules: AlertRuleSet) -> dict | None:
    """`sales_by_day`: total shop sales per logged day. Days not in the dict are missing."""
    rule = rules.sales_dip
    n_s, n_b = rule.short_window_days, rule.long_window_days
    days = [today - timedelta(days=k) for k in range(n_s + n_b, 0, -1)]            # oldest first, ends yesterday
    x = np.array([sales_by_day.get(d, np.nan) for d in days], dtype=float)
    st = dip_stats(x[n_b:], x[:n_b])
    if st is None or not is_dip(st, rule):
        return None
    z = st["z"] if np.isfinite(st["z"]) else None                                 # None: the base had no spread at all
    return _alert("sales_dip", rule, {
        "ratio": round(st["ratio"], 4), "drop_percent": round(100 * (1 - st["ratio"]), 1),
        "short_avg": round(st["short_avg"], 2), "base_avg": round(st["base_avg"], 2),
        "robust_z": None if z is None else round(z, 2), "short_window_days": n_s, "long_window_days": n_b,
        "short_days_logged": st["short_days_logged"], "base_days_logged": st["base_days_logged"]})


def _listed(items: list[dict]) -> list[dict]:
    return [{"item_id": i["item_id"], "name": i["name"]} for i in items[:MAX_ITEMS]]


def low_stock(advice: dict, rules: AlertRuleSet) -> dict | None:
    """Items at or under their reorder point, in the order of the ML4 reorder list (A items first)."""
    if not rules.low_stock.at_or_below_reorder_point:
        return None
    by_id = {i["item_id"]: i for i in advice["items"]}
    low = [by_id[i] for i in advice["reorder_list"]]
    if not low:
        return None
    return _alert("low_stock", rules.low_stock, {"count": len(low), "items": _listed(low)})


def dead_stock(advice: dict, rules: AlertRuleSet) -> dict | None:
    """Items on hand with no sale for `no_sale_days` (the same number as stock.yaml `dead_no_sale_days`)."""
    dead = sorted((i for i in advice["items"] if i["dead_stock"]), key=lambda i: (-i["stock_value"], i["item_id"]))
    if not dead:
        return None
    return _alert("dead_stock", rules.dead_stock, {
        "count": len(dead), "items": _listed(dead), "value": round(float(advice["dead_stock_value"]), 2),
        "no_sale_days": rules.dead_stock.no_sale_days})


def projected_cash(cash: float, net_by_day: dict[date, float], today: date, days_ahead: int) -> tuple[float, float]:
    """(projected cash, average daily net flow). Net flow = sales - purchases - expenses on logged days among the
    last CASH_FLOW_DAYS finished days; with no logged day the flow is taken as zero."""
    recent = [net_by_day[d] for k in range(1, CASH_FLOW_DAYS + 1) if (d := today - timedelta(days=k)) in net_by_day]
    flow = float(np.mean(recent)) if recent else 0.0
    return cash + days_ahead * flow, flow


def emi_due(loans: list[dict], cash: float | None, net_by_day: dict[date, float], today: date,
            rules: AlertRuleSet) -> list[dict]:
    """`loans`: [{"loan_id", "emi", "next_due_date"}] (next_due_date None = nothing due). One alert per loan.
    All instalments due within the window are added up before comparing with projected cash."""
    rule = rules.emi_due
    if cash is None:                                                               # DEC-62: no alert on a guess
        return []
    due = sorted((ln for ln in loans if ln.get("next_due_date") is not None
                  and 0 <= (ln["next_due_date"] - today).days <= rule.days_before_due),
                 key=lambda ln: (ln["next_due_date"], ln["loan_id"]))
    out, owed = [], 0.0
    for ln in due:
        days = (ln["next_due_date"] - today).days
        proj, flow = projected_cash(cash, net_by_day, today, days)
        owed += float(ln["emi"])
        if rule.projected_cash_below_emi and proj - (owed - float(ln["emi"])) >= float(ln["emi"]):
            continue
        out.append(_alert("emi_due", rule, {
            "loan_id": ln["loan_id"], "emi": round(float(ln["emi"]), 2), "due_date": ln["next_due_date"].isoformat(),
            "days_to_due": days, "cash_today": round(float(cash), 2), "projected_cash": round(proj, 2),
            "avg_daily_net_flow": round(flow, 2), "shortfall": round(owed - proj, 2)}))
    return out


def data_gap(last_log_day: date | None, launch_date: date | None, today: date, rules: AlertRuleSet) -> dict | None:
    """Finished days since the last log (or since launch when nothing was ever logged). No alert before launch."""
    if last_log_day is not None:
        missing = (today - last_log_day).days - 1
    elif launch_date is not None and launch_date < today:
        missing = (today - launch_date).days                                       # launch day itself is missing too
    else:
        return None
    if missing < rules.data_gap.no_log_days:
        return None
    return _alert("data_gap", rules.data_gap, {
        "days_without_log": missing, "last_log_day": last_log_day.isoformat() if last_log_day else None})


def evaluate(*, today: date, rules: AlertRuleSet, sales_by_day: dict[date, float], net_by_day: dict[date, float],
             advice: dict | None, loans: list[dict], cash: float | None, launch_date: date | None) -> list[dict]:
    """Every alert that holds today, most severe first. `advice` is the ML4 output (None = no stock records)."""
    logged = [d for d in sales_by_day if d < today]
    found = [sales_dip(sales_by_day, today, rules),
             low_stock(advice, rules) if advice else None,
             *emi_due(loans, cash, net_by_day, today, rules),
             dead_stock(advice, rules) if advice else None,
             data_gap(max(logged) if logged else None, launch_date, today, rules)]
    rank = {"critical": 0, "warn": 1, "info": 2}
    return sorted((a for a in found if a), key=lambda a: rank[a["severity"]])
