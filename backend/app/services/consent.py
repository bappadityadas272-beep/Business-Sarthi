"""Consent records (B-03, DEC-43). AGENTS rule 5: no shop data is stored or used before consent exists."""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Consent

SHOP_DATA = "shop_data"            # required: store the shop's data and use it for this owner's forecasts, reviews, alerts
BENCHMARKING = "benchmarking"      # optional: anonymised peer comparison later; no feature uses it yet
PURPOSES = {SHOP_DATA: {"required": True}, BENCHMARKING: {"required": False}}


def active(db: Session, user_id: int, purpose: str) -> Consent | None:
    q = select(Consent).where(Consent.user_id == user_id, Consent.purpose == purpose, Consent.withdrawn_at.is_(None))
    return db.scalars(q.order_by(Consent.id.desc())).first()


def give(db: Session, user_id: int, purpose: str) -> tuple[Consent, bool]:
    """(record, created). Giving a consent that is already active returns the existing record."""
    existing = active(db, user_id, purpose)
    if existing:
        return existing, False
    c = Consent(user_id=user_id, purpose=purpose)
    db.add(c)
    db.commit()
    return c, True


def withdraw(db: Session, user_id: int, purpose: str) -> bool:
    """Marks the active record withdrawn (history is kept). False if there was none."""
    c = active(db, user_id, purpose)
    if c is None:
        return False
    c.withdrawn_at = datetime.now(UTC)
    db.commit()
    return True
