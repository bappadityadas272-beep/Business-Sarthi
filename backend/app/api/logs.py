"""Daily logs (B-05): bulk save with one row per (shop, day, category), and range read."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import Db, OwnShop, OwnShopConsented
from app.models import DailyLog
from app.schemas.records import LogsIn, LogsOut, LogsSaved
from app.services import clock

router = APIRouter(prefix="/shops", tags=["logs"])


@router.post("/{shop_id}/logs", response_model=LogsSaved)
def save_logs(body: LogsIn, shop: OwnShopConsented, db: Db) -> dict:
    """Saving the same (day, category) again replaces the earlier figures. A day that is never sent stays missing."""
    today = clock.today()
    future = sorted({e.day.isoformat() for e in body.entries if e.day > today})
    if future:
        raise HTTPException(422, detail={"code": "day_in_future", "days": future[:10]})
    latest = {(e.day, e.category): e for e in body.entries}          # repeated in one request: the last one wins
    days = {d for d, _ in latest}
    rows = db.scalars(select(DailyLog).where(DailyLog.shop_id == shop.id, DailyLog.day >= min(days),
                                             DailyLog.day <= max(days)))
    existing = {(r.day, r.category): r for r in rows}
    created = updated = 0
    for key, e in latest.items():
        row = existing.get(key)
        if row is None:
            db.add(DailyLog(shop_id=shop.id, **e.model_dump()))
            created += 1
        else:
            row.sales, row.purchases, row.expenses = e.sales, e.purchases, e.expenses
            updated += 1
    db.commit()
    return {"created": created, "updated": updated}


@router.get("/{shop_id}/logs", response_model=LogsOut)
def read_logs(shop: OwnShop, db: Db, date_from: Annotated[date | None, Query(alias="from")] = None,
              date_to: Annotated[date | None, Query(alias="to")] = None) -> dict:
    """Both ends are included. Days with no entry are simply absent (missing, not zero)."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, detail={"code": "from_after_to"})
    q = select(DailyLog).where(DailyLog.shop_id == shop.id)
    if date_from:
        q = q.where(DailyLog.day >= date_from)
    if date_to:
        q = q.where(DailyLog.day <= date_to)
    rows = list(db.scalars(q.order_by(DailyLog.day, DailyLog.category)))
    totals: dict[date, dict] = {}
    for r in rows:
        t = totals.setdefault(r.day, {"day": r.day, "sales": 0.0, "purchases": 0.0, "expenses": 0.0})
        t["sales"] += r.sales
        t["purchases"] += r.purchases
        t["expenses"] += r.expenses
    return {"date_from": date_from, "date_to": date_to, "days_logged": len(totals), "entries": rows,
            "daily_totals": list(totals.values())}
