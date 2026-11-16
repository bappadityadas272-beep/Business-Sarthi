from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import UtcDatetime


class AlertOut(BaseModel):
    """A stored alert. `message_key` and `params` are localised by the frontend; the server sends no sentences."""
    id: int
    shop_id: int
    kind: str
    severity: Literal["info", "warn", "critical"]
    message_key: str
    params: dict[str, Any]
    raised_on: date | None
    last_seen_on: date | None
    still_active: bool                 # False: the problem was not found at the latest check, the alert is kept
    cleared_on: date | None
    resolved: bool
    resolved_on: date | None
    muted: bool
    created_at: UtcDatetime
    rules_are_assumptions: bool = True


class ResolveIn(BaseModel):
    mute: bool = False                 # True: do not remind me again while this same problem continues (DEC-67)


class RefreshOut(BaseModel):
    as_of: date
    raised: int
    refreshed: int
    muted_quiet: int
    cleared: int


class NotificationOut(BaseModel):
    id: int
    kind: str
    payload: dict[str, Any]
    read: bool
    created_at: UtcDatetime | None


class NotificationsOut(BaseModel):
    unread: int
    items: list[NotificationOut]


class ReadAllOut(BaseModel):
    marked_read: int
