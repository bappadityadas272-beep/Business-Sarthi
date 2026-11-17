"""SOS (B-10, DEC-83): `POST /api/sos` returns a shareable summary and a guided checklist. Nothing is stored."""
from datetime import date
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import ConsentedUser, Db, _own_shop
from app.services import clock, sos

router = APIRouter(tags=["sos"])


class SosIn(BaseModel):
    shop_id: int
    language: Literal["hi", "hinglish", "en"] | None = None      # default: the owner's profile language


class SosStep(BaseModel):
    key: str
    params: dict


class SosOut(BaseModel):
    shop_id: int
    as_of: date
    language: str
    stored: bool
    alerts: list[dict]
    emi: list[dict]
    last_30_days: dict
    steps: list[SosStep]
    share_text: str
    sources: list[str]
    steps_are_rules: bool = True            # chosen by fixed code rules, not by the LLM (AGENTS rule 2)
    not_advice: bool = True                 # prototype guidance, not financial advice (AGENTS rule 8)


@router.post("/sos", response_model=SosOut)
def make_sos(body: SosIn, user: ConsentedUser, db: Db) -> dict:
    shop = _own_shop(db, user, body.shop_id)
    lang = body.language or (user.language if user.language in sos.LANGS else "en")
    return sos.build(db, shop, clock.today(), lang)
