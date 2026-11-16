"""Stock items, stock moves and assets (B-06). On-hand is never stored: it is the sum of the moves of an item."""
from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Db, OwnShop, OwnShopConsented
from app.models import Asset, StockItem, StockMove
from app.schemas.records import AssetIn, AssetOut, MovesIn, MovesSaved, StockItemIn, StockItemOut
from app.services import clock

router = APIRouter(prefix="/shops", tags=["stock"])
OUTWARD = ("sale", "waste")


def items_with_on_hand(db: Session, shop_id: int, item_ids: set[int] | None = None) -> list[dict]:
    q = (select(StockItem, func.coalesce(func.sum(StockMove.qty), 0.0))
         .outerjoin(StockMove, StockMove.item_id == StockItem.id)
         .where(StockItem.shop_id == shop_id).group_by(StockItem.id).order_by(StockItem.id))
    if item_ids is not None:
        q = q.where(StockItem.id.in_(item_ids))
    return [{"id": i.id, "name": i.name, "category": i.category, "unit": i.unit, "cost": i.cost, "price": i.price,
             "reorder_point": i.reorder_point, "on_hand": round(float(qty), 3),
             "stock_value": round(float(qty) * i.cost, 2)} for i, qty in db.execute(q)]


@router.get("/{shop_id}/stock", response_model=list[StockItemOut])
def list_stock(shop: OwnShop, db: Db) -> list[dict]:
    return items_with_on_hand(db, shop.id)


@router.post("/{shop_id}/stock", response_model=StockItemOut, status_code=201)
def add_item(body: StockItemIn, shop: OwnShopConsented, db: Db) -> dict:
    name = body.name.strip()
    clash = db.scalar(select(StockItem.id).where(StockItem.shop_id == shop.id,
                                                 func.lower(StockItem.name) == name.lower()))
    if clash is not None:
        raise HTTPException(409, detail={"code": "item_exists", "item_id": clash})
    today = clock.today()
    day = body.opening_day or today
    if day > today:
        raise HTTPException(422, detail={"code": "day_in_future", "days": [day.isoformat()]})
    item = StockItem(shop_id=shop.id, name=name, category=body.category, unit=body.unit, cost=body.cost,
                     price=body.price)
    if body.opening_qty > 0:
        item.moves.append(StockMove(day=day, qty=body.opening_qty, kind="adjust"))
    db.add(item)
    db.commit()
    return items_with_on_hand(db, shop.id, {item.id})[0]


@router.post("/{shop_id}/stock/moves", response_model=MovesSaved, status_code=201)
def add_moves(body: MovesIn, shop: OwnShopConsented, db: Db) -> dict:
    """All or nothing. Purchase, sale and waste take a positive quantity; sale and waste are stored as negative."""
    today = clock.today()
    ids = {m.item_id for m in body.moves}
    own = set(db.scalars(select(StockItem.id).where(StockItem.shop_id == shop.id, StockItem.id.in_(ids))))
    if ids - own:
        raise HTTPException(404, detail={"code": "item_not_found", "item_ids": sorted(ids - own)})
    for m in body.moves:
        if m.day > today:
            raise HTTPException(422, detail={"code": "day_in_future", "days": [m.day.isoformat()]})
        if m.qty == 0 or (m.kind != "adjust" and m.qty < 0):
            raise HTTPException(422, detail={"code": "bad_quantity", "item_id": m.item_id, "kind": m.kind})
    for m in body.moves:
        db.add(StockMove(item_id=m.item_id, day=m.day, kind=m.kind, qty=-m.qty if m.kind in OUTWARD else m.qty))
    db.commit()
    return {"saved": len(body.moves), "items": items_with_on_hand(db, shop.id, ids)}


@router.get("/{shop_id}/assets", response_model=list[AssetOut])
def list_assets(shop: OwnShop, db: Db) -> list[Asset]:
    return list(db.scalars(select(Asset).where(Asset.shop_id == shop.id).order_by(Asset.id)))


@router.post("/{shop_id}/assets", response_model=AssetOut, status_code=201)
def add_asset(body: AssetIn, shop: OwnShopConsented, db: Db) -> Asset:
    asset = Asset(shop_id=shop.id, **body.model_dump())
    db.add(asset)
    db.commit()
    return asset
