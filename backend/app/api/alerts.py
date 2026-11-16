"""Alerts: list, resolve (with an optional mute) and refresh (B-08). The rules are code; no LLM is involved."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from sqlalchemy import case, select

from app.api.deps import Db, OwnShop, OwnShopConsented
from app.models import Alert
from app.schemas.alerts import AlertOut, RefreshOut, ResolveIn
from app.services import alerts as alert_service
from app.services import clock

router = APIRouter(prefix="/shops", tags=["alerts"])
_RANK = case({"critical": 0, "warn": 1}, value=Alert.severity, else_=2)


def as_out(a: Alert) -> dict:
    return {"id": a.id, "shop_id": a.shop_id, "kind": a.kind, "severity": a.severity, "message_key": a.message_key,
            "params": a.params, "raised_on": a.raised_on, "last_seen_on": a.last_seen_on,
            "still_active": a.cleared_on is None, "cleared_on": a.cleared_on, "resolved": a.resolved,
            "resolved_on": a.resolved_on, "muted": a.muted, "created_at": a.created_at}


@router.get("/{shop_id}/alerts", response_model=list[AlertOut])
def list_alerts(shop: OwnShop, db: Db, status: Literal["open", "all"] = "open") -> list[dict]:
    """Open alerts (default) or all of them, most severe first, then newest first. Reads only; see `refresh`."""
    q = select(Alert).where(Alert.shop_id == shop.id)
    if status == "open":
        q = q.where(Alert.resolved.is_(False))
    return [as_out(a) for a in db.scalars(q.order_by(_RANK, Alert.id.desc()))]


@router.post("/{shop_id}/alerts/refresh", response_model=RefreshOut)
def refresh_alerts(shop: OwnShopConsented, db: Db) -> dict:
    """Check every alert rule now. The daily job (B-09) calls the same service."""
    return alert_service.refresh(db, shop, clock.today())


@router.post("/{shop_id}/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: int, shop: OwnShop, db: Db, body: ResolveIn | None = None) -> dict:
    """Mark as resolved. With `mute: true` the same continuing problem will not be raised again (DEC-67).
    Calling it again is allowed, for example to mute an alert that was already resolved."""
    a = db.get(Alert, alert_id)
    if a is None or a.shop_id != shop.id:
        raise HTTPException(404, detail={"code": "alert_missing"})
    if not a.resolved:
        a.resolved, a.resolved_on = True, clock.today()
    if body is not None and body.mute:
        a.muted = True
    db.commit()
    return as_out(a)
