"""Stock advice for one shop: reads items and moves, then calls the pure ML4 code (M-07)."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml import reorder
from app.models import StockItem, StockMove
from app.rules import Stock


def advice(db: Session, shop_id: int, today: date, rule: Stock) -> dict:
    items = [{"id": i.id, "name": i.name, "category": i.category, "unit": i.unit, "cost": i.cost, "price": i.price}
             for i in db.scalars(select(StockItem).where(StockItem.shop_id == shop_id).order_by(StockItem.id))]
    rows = db.execute(select(StockMove.item_id, StockMove.day, StockMove.qty, StockMove.kind)
                      .join(StockItem, StockItem.id == StockMove.item_id).where(StockItem.shop_id == shop_id))
    moves = [{"item_id": r.item_id, "day": r.day, "qty": r.qty, "kind": r.kind} for r in rows]
    return reorder.advise(items, moves, today, rule)
