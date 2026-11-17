"""Notifications for the logged-in owner: list with unread count, mark read (B-08)."""
from typing import cast

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.api.deps import CurrentUser, Db
from app.models import Notification
from app.schemas.alerts import NotificationOut, NotificationsOut, ReadAllOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


def as_out(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "payload": n.payload_json, "read": n.read, "created_at": n.created_at}


@router.get("", response_model=NotificationsOut)
def list_notifications(user: CurrentUser, db: Db, unread_only: bool = False, limit: int = 50) -> dict:
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read.is_(False))
    unread = db.scalar(select(func.count()).select_from(Notification)
                       .where(Notification.user_id == user.id, Notification.read.is_(False)))
    items = db.scalars(q.order_by(Notification.id.desc()).limit(max(1, min(limit, 200))))
    return {"unread": unread, "items": [as_out(n) for n in items]}


@router.post("/read-all", response_model=ReadAllOut)
def read_all(user: CurrentUser, db: Db) -> dict:
    done = cast(CursorResult, db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))
                      .values(read=True))).rowcount
    db.commit()
    return {"marked_read": done}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read_one(notification_id: int, user: CurrentUser, db: Db) -> dict:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(404, detail={"code": "notification_missing"})
    n.read = True
    db.commit()
    return as_out(n)
