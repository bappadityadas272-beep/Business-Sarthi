"""Delete-my-data (B-11, DEC-84): every row tied to the owner goes, consent history included.

Database rows go through the ORM cascades (user -> shops -> logs, stock items -> moves, ...). In-memory copies
also go: the chat answer cache entries of the owner's shops and any pending OTP for the phone. Backups made with
`make backup` are files outside the database and are NOT touched; RUNBOOK section 4 says to delete them by hand.

`redact_identifiers` (DEC-94): chat text loses phone, Aadhaar and PAN numbers before it is stored or sent to the
hosted LLM. A pattern safety net, like the log redactor in app/obs.py, not a guarantee: a number written in words,
split oddly or typed in Devanagari digits is not caught.
"""
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.llm import client as llm
from app.models import (
    Alert,
    Asset,
    ChatMessage,
    Consent,
    DailyLog,
    Forecast,
    Loan,
    Notification,
    Review,
    Shop,
    StockItem,
    StockMove,
    User,
)
from app.services import auth

log = logging.getLogger("sarthi.privacy")

REDACTED = "[redacted]"
_IDENTIFIERS = [
    re.compile(r"(?<![0-9A-Za-z])[2-9][0-9]{3}[\s-]?[0-9]{4}[\s-]?[0-9]{4}(?![0-9])"),            # Aadhaar: 12 digits
    re.compile(r"(?<![0-9A-Za-z+])(?:\+?91[\s-]?|0)?[6-9][0-9]{4}[\s-]?[0-9]{5}(?![0-9])"),       # Indian mobile
    re.compile(r"(?<![0-9A-Za-z])[A-Za-z]{5}[0-9]{4}[A-Za-z](?![0-9A-Za-z])"),                     # PAN
]


def redact_identifiers(text: str) -> str:
    """Phone, Aadhaar and PAN numbers -> '[redacted]'. Amounts with commas or under 10 digits stay as typed."""
    for p in _IDENTIFIERS:
        text = p.sub(REDACTED, text)
    return text

PER_SHOP = {"daily_log": DailyLog, "stock_item": StockItem, "asset": Asset, "loan": Loan, "forecast": Forecast,
            "review": Review, "alert": Alert, "chat_message": ChatMessage}


def owned_counts(db: Session, user_id: int) -> dict[str, int]:
    """Rows per table that belong to this user (also used by the tests to prove nothing is left)."""
    shop_ids = list(db.scalars(select(Shop.id).where(Shop.user_id == user_id)))
    n = {"user": db.scalar(select(func.count()).select_from(User).where(User.id == user_id)) or 0,
         "consent": db.scalar(select(func.count()).select_from(Consent).where(Consent.user_id == user_id)) or 0,
         "notification": db.scalar(select(func.count()).select_from(Notification)
                                   .where(Notification.user_id == user_id)) or 0,
         "shop": len(shop_ids)}
    for name, model in PER_SHOP.items():
        n[name] = db.scalar(select(func.count()).select_from(model).where(model.__table__.c.shop_id.in_(shop_ids))) or 0
    n["stock_move"] = db.scalar(select(func.count()).select_from(StockMove).join(StockItem)
                                .where(StockItem.shop_id.in_(shop_ids))) or 0
    return n


def delete_user_data(db: Session, user: User) -> dict[str, int]:
    shop_ids = [s.id for s in user.shops]
    phone = user.phone
    counts = owned_counts(db, user.id)
    db.delete(user)
    db.commit()
    llm.answer_cache.forget_shops(shop_ids)
    auth.forget_phone(phone)
    log.info("delete-my-data user_id=%s rows=%s", user.id, sum(counts.values()))     # no phone in the log
    return counts
