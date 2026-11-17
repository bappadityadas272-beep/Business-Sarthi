"""Profile, language and consent (B-02, B-03)."""
from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, Db
from app.models import Consent
from app.schemas.auth import Me
from app.schemas.profile import ConsentIn, ConsentOut, ConsentRecord, DataDeleted, MeUpdate, Purpose
from app.services import consent, privacy

router = APIRouter(tags=["profile"])


@router.get("/me", response_model=Me)
def read_me(user: CurrentUser) -> Me:
    return Me.model_validate(user)


@router.put("/me", response_model=Me)
def update_me(body: MeUpdate, user: CurrentUser, db: Db) -> Me:
    user.language = body.language
    db.add(user)
    db.commit()
    return Me.model_validate(user)


def _out(purpose: str, rec: Consent | None) -> ConsentOut:
    return ConsentOut(purpose=purpose, required=consent.PURPOSES[purpose]["required"], active=rec is not None,
                      given_at=rec.given_at if rec else None)


@router.delete("/me/data", response_model=DataDeleted)
def delete_my_data(user: CurrentUser, db: Db) -> DataDeleted:
    """B-11 (DEC-84): delete the account and every row tied to it. Works without consent (withdrawing first is
    allowed). The token stops working; logging in again with the same phone starts a new, empty account."""
    return DataDeleted(deleted=privacy.delete_user_data(db, user))


@router.get("/consents", response_model=list[ConsentOut])
def list_consents(user: CurrentUser, db: Db) -> list[ConsentOut]:
    """Every purpose the app asks for, and whether this user has an active consent for it."""
    return [_out(p, consent.active(db, user.id, p)) for p in consent.PURPOSES]


@router.post("/consents", response_model=ConsentOut, status_code=201)
def give_consent(body: ConsentIn, user: CurrentUser, db: Db, response: Response) -> ConsentOut:
    rec, created = consent.give(db, user.id, body.purpose)
    if not created:
        response.status_code = 200
    return _out(body.purpose, rec)


@router.delete("/consents", response_model=ConsentOut)
def withdraw_consent(purpose: Purpose, user: CurrentUser, db: Db) -> ConsentOut:
    """Withdraw. Stored data stays until delete-my-data (B-11); new writes for `shop_data` are refused."""
    consent.withdraw(db, user.id, purpose)
    return _out(purpose, None)


@router.get("/consents/history", response_model=list[ConsentRecord])
def consent_history(user: CurrentUser, db: Db) -> list[ConsentRecord]:
    rows = db.scalars(select(Consent).where(Consent.user_id == user.id).order_by(Consent.id)).all()
    return [ConsentRecord(purpose=r.purpose, given_at=r.given_at, withdrawn_at=r.withdrawn_at) for r in rows]
