"""In-process scheduler (B-09, APScheduler). One job: every hour, do the day's work for every shop.

The work is idempotent (an alert is not raised twice, a review is stored once per period), so running it often is
safe and a server that was switched off at night still catches up the same day. Shops whose owner has no active
`shop_data` consent are skipped (AGENTS rule 5)."""
import logging
from datetime import date
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.jobs import alert_job, review_job
from app.models import Shop
from app.services import clock, consent

log = logging.getLogger(__name__)
JOB_ID = "daily_shop_checks"
_scheduler: BackgroundScheduler | None = None


def run_day(db: Session, day: date) -> dict:
    """Alerts and due reviews for every consented shop, as of `day`. One failing shop does not stop the others."""
    out: dict[str, Any] = {"day": day, "shops": 0, "skipped_no_consent": 0, "alerts_raised": 0, "reviews_created": 0, "errors": 0}
    for shop in db.scalars(select(Shop).order_by(Shop.id)).all():
        if consent.active(db, shop.user_id, consent.SHOP_DATA) is None:
            out["skipped_no_consent"] += 1
            continue
        out["shops"] += 1
        try:
            if review_job.run(db, shop, day) is not None:
                out["reviews_created"] += 1
            out["alerts_raised"] += alert_job.run(db, shop, day)
        except Exception:                                    # keep going; the log has the details
            db.rollback()
            out["errors"] += 1
            log.exception("daily job failed for shop %s on %s", shop.id, day)
    return out


def _tick() -> None:
    from app.db import SessionLocal
    with SessionLocal() as db:
        result = run_day(db, clock.today())
    log.info("daily job: %s", result)


def start() -> BackgroundScheduler | None:
    """Start the scheduler unless it is switched off or already running."""
    global _scheduler
    s = get_settings()
    if not s.scheduler_enabled or _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(_tick, "interval", minutes=s.scheduler_interval_minutes, id=JOB_ID, max_instances=1,
                       coalesce=True)
    _scheduler.start()
    return _scheduler


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
