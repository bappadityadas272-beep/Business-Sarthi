"""Shared API dependencies: the logged-in user."""
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.services import auth

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
