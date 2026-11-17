"""`GET /api/schemes/match` (C-03, DEC-86, DEC-87). Age, category and state are read from the request and never
stored. Facts come only from the scheme KB, each with its source URL and last_verified date."""
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import ConsentedUser, Db, _own_shop
from app.services import clock
from app.services import schemes as svc

router = APIRouter(tags=["schemes"])
Category = Literal["general", "sc", "st", "obc", "women", "minority", "pwd", "ex_servicemen"]


class SchemeMatch(BaseModel):
    id: str
    name: str
    name_en: str
    type: str
    summary: str
    how_to_apply: str
    why_it_may_fit: list[str]
    missing_requirements: list[str]
    please_confirm: list[str]
    checks: dict[str, str]
    unknown_checks: int
    similarity: float
    source_url: str
    url: str
    last_verified: str
    verified: bool
    label: str | None
    label_text: str | None


class MatchOut(BaseModel):
    shop_id: int
    as_of: str
    language: str
    profile_used: dict
    profile_stored: bool
    notice: str
    note: str | None
    schemes: list[SchemeMatch]
    excluded: list[dict]
    kb: dict | None
    decided_by_code: bool = True            # eligibility and ranking are fixed code rules (AGENTS rule 2)
    not_advice: bool = True


@router.get("/schemes/match", response_model=MatchOut)
def match_schemes(
    shop_id: int, user: ConsentedUser, db: Db,
    state: Annotated[str | None, Query(max_length=60)] = None,
    category: Annotated[list[Category] | None, Query()] = None,
    age: Annotated[int | None, Query(ge=14, le=100)] = None,
    need: Annotated[str | None, Query(max_length=300)] = None,
    language: Literal["hi", "hinglish", "en"] | None = None,
) -> dict:
    shop = _own_shop(db, user, shop_id)
    lang = language or (user.language if user.language in svc.LANGS else "en")
    profile = {"state": state, "categories": category, "age": age, "need": need}
    return svc.match(shop, clock.today(), profile, lang)
