"""Alerts store (B-08): run the pure ML6 rules for one shop and keep the `alert` table in step with them.

How an alert lives (DEC-67, chosen by the human; DEC-68 details):
- One problem has one `dedupe_key` (the kind; for an EMI the kind, the loan and the due date).
- Problem found and an OPEN alert with that key exists: its numbers are refreshed. No second alert, no notification.
- Problem found and the last alert with that key was RESOLVED by the owner: a new alert is raised (a reminder),
  unless the owner muted it. A muted problem stays quiet until it has gone away and come back.
- Problem no longer found: the alert is NOT closed (only the owner resolves); `cleared_on` records the day and the
  API shows `still_active: false`. `cleared_on` also ends a mute.
- A new warn or critical alert creates a notification; info alerts (dead stock, data gap) do not.
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml import alerts as engine
from app.models import Alert, Loan, Notification, Shop, StockItem
from app.rules import get_rules
from app.services import loans as loan_dates
from app.services import review as review_service
from app.services import stock as stock_service

NOTIFY_SEVERITIES = ("warn", "critical")


def dedupe_key(alert: dict) -> str:
    if alert["kind"] == "emi_due":
        return f"emi_due:{alert['params']['loan_id']}:{alert['params']['due_date']}"
    return alert["kind"]


def notify(db: Session, user_id: int, kind: str, payload: dict) -> Notification:
    """Add a notification (not committed here). The payload carries keys and numbers, never finished text."""
    n = Notification(user_id=user_id, kind=kind, payload_json=payload)
    db.add(n)
    return n


def found_today(db: Session, shop: Shop, today: date) -> list[dict]:
    """Gather the shop's numbers and run every alert rule."""
    rules = get_rules()
    logs = review_service.daily_logs(db, shop.id, today - timedelta(days=1))
    loans = list(db.scalars(select(Loan).where(Loan.shop_id == shop.id)))
    _, emis_paid, _ = review_service.loan_figures(loans, today, today - timedelta(days=1))   # due before today
    has_stock = db.scalar(select(StockItem.id).where(StockItem.shop_id == shop.id).limit(1)) is not None
    return engine.evaluate(
        today=today, rules=rules.alerts.rules,
        sales_by_day={d: v["sales"] for d, v in logs.items()},
        net_by_day={d: v["sales"] - v["purchases"] - v["expenses"] for d, v in logs.items()},
        advice=stock_service.advice(db, shop.id, today, rules.stock) if has_stock else None,
        loans=[{"loan_id": ln.id, "emi": ln.emi, "next_due_date": loan_dates.status(
            ln.start_date, ln.due_day, ln.tenure_months, ln.emi, today)["next_due_date"]} for ln in loans],
        cash=review_service.cash_position(shop.opening_cash, logs, emis_paid), launch_date=shop.launch_date)


def refresh(db: Session, shop: Shop, today: date) -> dict:
    """Bring the stored alerts in step with today's rules. Returns counts of what happened."""
    found = {dedupe_key(a): a for a in found_today(db, shop, today)}
    latest: dict[str, Alert] = {}
    for stored in db.scalars(select(Alert).where(Alert.shop_id == shop.id).order_by(Alert.id)):
        latest[stored.dedupe_key] = stored                                    # the newest row of each key wins
    raised = refreshed = muted = cleared = 0
    for key, a in found.items():
        row = latest.get(key)
        if row is not None and not row.resolved:
            row.params, row.severity, row.last_seen_on, row.cleared_on = a["params"], a["severity"], today, None
            refreshed += 1
        elif row is not None and row.muted and row.cleared_on is None:
            row.last_seen_on = today                                    # same problem, the owner asked for quiet
            muted += 1
        else:
            new = Alert(shop_id=shop.id, kind=a["kind"], severity=a["severity"], message_key=a["message_key"],
                        params=a["params"], dedupe_key=key, raised_on=today, last_seen_on=today)
            db.add(new)
            db.flush()
            if a["severity"] in NOTIFY_SEVERITIES:
                notify(db, shop.user_id, "alert", {"alert_id": new.id, "shop_id": shop.id, "kind": a["kind"],
                                                   "severity": a["severity"], "message_key": a["message_key"],
                                                   "params": a["params"], "is_reminder": row is not None})
            raised += 1
    for key, row in latest.items():
        if key not in found and row.cleared_on is None:
            row.cleared_on = today
            cleared += 1
    db.commit()
    return {"as_of": today, "raised": raised, "refreshed": refreshed, "muted_quiet": muted, "cleared": cleared}
