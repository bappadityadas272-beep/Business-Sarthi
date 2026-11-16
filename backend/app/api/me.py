"""Profile (B-02 read; B-03 adds language update and consents)."""
from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.schemas.auth import Me

router = APIRouter(tags=["profile"])


@router.get("/me", response_model=Me)
def read_me(user: CurrentUser) -> Me:
    return Me.model_validate(user)
