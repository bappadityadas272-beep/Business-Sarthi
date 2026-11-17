"""Mock OTP login (B-02). PROTOTYPE: no SMS is sent; see app/services/auth.py."""
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app import ratelimit
from app.api.deps import Db
from app.config import get_settings
from app.models import User
from app.schemas.auth import OtpRequest, OtpRequested, OtpVerify, Token
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])
_STATUS = {"invalid_phone": 422, "otp_too_many_tries": 429}


def _fail(e: auth.AuthError) -> HTTPException:
    return HTTPException(_STATUS.get(e.code, 401), detail={"code": e.code})


@router.post("/otp/request", response_model=OtpRequested)
def otp_request(body: OtpRequest, request: Request) -> OtpRequested:
    try:
        phone = auth.normalise_phone(body.phone)
        ratelimit.check((ratelimit.OTP_PER_PHONE, phone),
                        (ratelimit.OTP_PER_IP, request.client.host if request.client else "unknown"))
        code = auth.request_otp(phone)
    except auth.AuthError as e:
        raise _fail(e) from e
    return OtpRequested(expires_in_seconds=int(auth.OTP_TTL.total_seconds()),
                        dev_otp=code if get_settings().dev_mode else None)


@router.post("/otp/verify", response_model=Token)
def otp_verify(body: OtpVerify, db: Db) -> Token:
    try:
        phone = auth.verify_otp(body.phone, body.otp)
    except auth.AuthError as e:
        raise _fail(e) from e
    user = db.scalar(select(User).where(User.phone == phone))
    is_new = user is None
    if user is None:
        user = User(phone=phone)
        db.add(user)
        db.commit()
        db.refresh(user)                    # created_at as stored, so the account stamp matches later reads
    token, ttl = auth.create_token(user.id, created_at=user.created_at)
    return Token(access_token=token, expires_in_seconds=ttl, is_new_user=is_new)
