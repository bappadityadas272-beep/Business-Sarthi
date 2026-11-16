"""3-month review: run now, read the latest, list all (M-08). The decision comes from rules, never from the LLM."""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import Db, OwnShop, OwnShopConsented
from app.models import Review
from app.schemas.review import ReviewOut
from app.services import clock
from app.services import review as review_service

router = APIRouter(prefix="/shops", tags=["reviews"])


def as_out(row: Review) -> dict:
    return {"id": row.id, "shop_id": row.shop_id, "period_start": row.period_start, "period_end": row.period_end,
            "created_on": row.created_on, "decision": row.decision, "indicators": row.indicators,
            "reasons": row.reasons, "actions": row.actions, "confidence": row.confidence,
            "confidence_reasons": row.details.get("confidence_reasons", []), "notes": row.details.get("notes", []),
            "data_completeness": row.indicators.get("data_completeness", 0.0)}


@router.post("/{shop_id}/reviews/run", response_model=ReviewOut)
def run_review(shop: OwnShopConsented, db: Db) -> dict:
    return as_out(review_service.run(db, shop, clock.today()))


@router.get("/{shop_id}/reviews/latest", response_model=ReviewOut)
def latest_review(shop: OwnShop, db: Db) -> dict:
    row = db.scalars(select(Review).where(Review.shop_id == shop.id)
                     .order_by(Review.period_end.desc(), Review.id.desc()).limit(1)).first()
    if row is None:
        raise HTTPException(404, detail={"code": "review_missing"})
    return as_out(row)


@router.get("/{shop_id}/reviews", response_model=list[ReviewOut])
def list_reviews(shop: OwnShop, db: Db) -> list[dict]:
    rows = db.scalars(select(Review).where(Review.shop_id == shop.id).order_by(Review.period_end.desc(), Review.id.desc()))
    return [as_out(r) for r in rows]
