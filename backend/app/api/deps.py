"""Shared API dependencies: the logged-in user, consent check, shop ownership."""
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Shop, User
from app.services import auth, consent

_bearer = HTTPBearer(auto_error=False)
Db = Annotated[Session, Depends(get_db)]


def current_user(db: Db, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> User:
    if cred is None:
        raise HTTPException(401, detail={"code": "not_logged_in"}, headers={"WWW-Authenticate": "Bearer"})
    try:
        user = db.get(User, auth.read_token(cred.credentials))
    except auth.AuthError as e:
        raise HTTPException(401, detail={"code": e.code}, headers={"WWW-Authenticate": "Bearer"}) from e
    if user is None:
        raise HTTPException(401, detail={"code": "invalid_token"}, headers={"WWW-Authenticate": "Bearer"})
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def consented_user(user: CurrentUser, db: Db) -> User:
    """403 unless the user has an active `shop_data` consent (AGENTS rule 5)."""
    if consent.active(db, user.id, consent.SHOP_DATA) is None:
        raise HTTPException(403, detail={"code": "consent_required", "purpose": consent.SHOP_DATA})
    return user


ConsentedUser = Annotated[User, Depends(consented_user)]


def _own_shop(db: Session, user: User, shop_id: int) -> Shop:
    shop = db.get(Shop, shop_id)
    if shop is None or shop.user_id != user.id:          # same answer for "missing" and "not yours"
        raise HTTPException(404, detail={"code": "shop_not_found"})
    return shop


def owned_shop(shop_id: int, user: CurrentUser, db: Db) -> Shop:
    """Read access: the shop must belong to the caller."""
    return _own_shop(db, user, shop_id)


def owned_shop_consented(shop_id: int, user: ConsentedUser, db: Db) -> Shop:
    """Write or compute access: own shop AND active consent."""
    return _own_shop(db, user, shop_id)


OwnShop = Annotated[Shop, Depends(owned_shop)]
OwnShopConsented = Annotated[Shop, Depends(owned_shop_consented)]
