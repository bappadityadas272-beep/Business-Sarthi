"""3-month review when it falls due (B-09, DEC-69).

A review is due every `window_days` (90) days after the launch date: on launch + 90, + 180, ... It covers the 90 days
that ended the day before. Only the LATEST due date is looked at: reviews missed while the app was not running are
not made up afterwards. A shop without a launch date has no reviews."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Review, Shop
from app.rules import get_rules
from app.services import alerts as alert_service
from app.services import review as review_service


def due_date(launch_date: date | None, day: date, window_days: int) -> date | None:
    """The latest review date on or before `day`, or None when no review is due yet."""
    if launch_date is None:
        return None
    k = (day - launch_date).days // window_days
    return launch_date + timedelta(days=k * window_days) if k >= 1 else None


def next_due_date(launch_date: date | None, day: date, window_days: int) -> date | None:
    """The first review date after `day` (for the dashboard)."""
    if launch_date is None:
        return None
    k = max((day - launch_date).days // window_days, 0) + 1
    return launch_date + timedelta(days=k * window_days)


def run(db: Session, shop: Shop, day: date) -> Review | None:
    """Run and store the review that is due, once, and notify the owner. None when nothing is due or it exists."""
    due = due_date(shop.launch_date, day, get_rules().review.window_days)
    if due is None:
        return None
    period_end = due - timedelta(days=1)
    if db.scalars(select(Review.id).where(Review.shop_id == shop.id, Review.period_end == period_end)).first():
        return None
    row = review_service.run(db, shop, due)
    alert_service.notify(db, shop.user_id, "review_ready", {
        "review_id": row.id, "shop_id": shop.id, "decision": row.decision, "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(), "message_key": "notification.review_ready"})
    db.commit()
    return row
