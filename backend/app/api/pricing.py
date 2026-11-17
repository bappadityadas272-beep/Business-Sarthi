"""Pricing and margin helper endpoint (M-11, ML10, DEC-89). Targets are assumptions from data/rules/pricing.yaml."""
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import Db, OwnShopConsented
from app.ml import pricing as ml10
from app.models import StockItem, StockMove
from app.rules import get_rules
from app.services import clock

router = APIRouter(prefix="/shops", tags=["pricing"])


@router.get("/{shop_id}/pricing")
def pricing(shop: OwnShopConsented, db: Db) -> dict:
    """Margin per category against the assumed target; flags categories below it. Computed on request, not stored."""
    rule = get_rules().pricing
    today = clock.today()
    items = [{"id": i.id, "name": i.name, "category": i.category, "cost": i.cost, "price": i.price}
             for i in db.scalars(select(StockItem).where(StockItem.shop_id == shop.id).order_by(StockItem.id))]
    rows = db.execute(select(StockMove.item_id, StockMove.day, StockMove.qty, StockMove.kind)
                      .join(StockItem, StockItem.id == StockMove.item_id).where(StockItem.shop_id == shop.id))
    moves = [{"item_id": r.item_id, "day": r.day, "qty": r.qty, "kind": r.kind} for r in rows]
    cats = ml10.analyse(items, moves, today, rule)
    return {"shop_id": shop.id, "as_of": today, "window_days": rule.window_days, "targets_are_assumptions": True,
            "rules_version": rule.version, "categories": cats,
            "flagged": [c["category"] for c in cats if c["below_target"]],
            "notes": ["pricing.targets_assumed", "pricing.demand_may_react", "pricing.costs_from_items"]}
