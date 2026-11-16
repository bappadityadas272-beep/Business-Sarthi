"""Shops: create from the idea form and read (B-04). An owner sees only their own shops."""
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import ConsentedUser, CurrentUser, Db, OwnShop
from app.models import Shop
from app.schemas.profile import ShopIn, ShopOut

router = APIRouter(prefix="/shops", tags=["shops"])


@router.post("", response_model=ShopOut, status_code=201)
def create_shop(body: ShopIn, user: ConsentedUser, db: Db) -> Shop:
    shop = Shop(user_id=user.id, **body.model_dump())
    db.add(shop)
    db.commit()
    return shop


@router.get("", response_model=list[ShopOut])
def list_shops(user: CurrentUser, db: Db) -> list[Shop]:
    return list(db.scalars(select(Shop).where(Shop.user_id == user.id).order_by(Shop.id)))


@router.get("/{shop_id}", response_model=ShopOut)
def read_shop(shop: OwnShop) -> Shop:
    return shop
