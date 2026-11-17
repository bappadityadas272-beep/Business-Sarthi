"""Mock phone OTP and JWT (checkpoint B-02, DEC-10, DEC-40, DEC-41).

PROTOTYPE ONLY: no SMS is sent. The code is kept in process memory (lost on restart, one process only) and is
printed to the server log; a production build would use an SMS provider and a shared store.
"""
from __future__ import annotations

import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.config import DEV_JWT_SECRET, get_settings
from app.obs import mask_phone

log = logging.getLogger("sarthi.auth")

OTP_TTL = timedelta(minutes=5)
OTP_MAX_TRIES = 5
TOKEN_TTL = timedelta(days=7)
JWT_ALG = "HS256"
DEFAULT_SECRET = DEV_JWT_SECRET
_PHONE = re.compile(r"^\+?[1-9][0-9]{9,14}$")


MIN_SECRET_LEN = 32          # HS256 key of at least 256 bits (RFC 7518 section 3.2)


class AuthNotConfigured(RuntimeError):
    """DEV_MODE is off and JWT_SECRET is unset, the dev placeholder, or too short (DEC-41, DEC-97).
    The API answers 503 `auth_not_configured` and /api/ready says why; no token is made or read."""

    def __init__(self, reason: str, fix: str):
        super().__init__(f"{reason}: {fix}")
        self.reason = reason


def auth_check() -> dict:
    """Readiness of login. Dev mode may use the placeholder secret; outside it a real secret is required."""
    s = get_settings()
    if s.dev_mode:
        return {"ok": True, "reason": "dev_mode_placeholder_secret" if s.jwt_secret == DEFAULT_SECRET else None}
    fix = f"set JWT_SECRET in .env (at least {MIN_SECRET_LEN} random characters)"
    if not s.jwt_secret or s.jwt_secret == DEFAULT_SECRET:
        return {"ok": False, "reason": "jwt_secret_not_set", "fix": fix}
    if len(s.jwt_secret) < MIN_SECRET_LEN:
        return {"ok": False, "reason": "jwt_secret_too_short", "fix": fix}
    return {"ok": True, "reason": None}


def require_configured() -> None:
    c = auth_check()
    if not c["ok"]:
        raise AuthNotConfigured(c["reason"], c["fix"])


class AuthError(Exception):
    """Raised with a stable `code` the API turns into an error response."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class _Otp:
    code: str
    expires: datetime
    tries: int = 0


_store: dict[str, _Otp] = {}


def normalise_phone(phone: str) -> str:
    p = re.sub(r"[\s\-()]", "", phone or "")
    if not _PHONE.match(p):
        raise AuthError("invalid_phone")
    if p.startswith("+"):
        return p
    return "+91" + p if len(p) == 10 else "+" + p      # a bare 10-digit number is taken as Indian


def request_otp(phone: str, now: datetime | None = None) -> str:
    """Create (or replace) the code for this phone and return it. The caller decides whether to reveal it."""
    phone = normalise_phone(phone)
    code = f"{secrets.randbelow(10**6):06d}"
    _store[phone] = _Otp(code, (now or datetime.now(UTC)) + OTP_TTL)
    if get_settings().dev_mode:
        log.warning("MOCK OTP for %s is %s (DEV_MODE; no SMS is sent)", mask_phone(phone), code)   # DEC-90
    return code


def verify_otp(phone: str, code: str, now: datetime | None = None) -> str:
    """Return the normalised phone if the code is right; a code works once."""
    phone = normalise_phone(phone)
    entry = _store.get(phone)
    if entry is None:
        raise AuthError("otp_not_requested")
    if (now or datetime.now(UTC)) > entry.expires:
        _store.pop(phone, None)
        raise AuthError("otp_expired")
    if not hmac.compare_digest(entry.code, str(code or "")):
        entry.tries += 1
        if entry.tries >= OTP_MAX_TRIES:
            _store.pop(phone, None)
            raise AuthError("otp_too_many_tries")
        raise AuthError("otp_wrong")
    _store.pop(phone, None)
    return phone


def _secret() -> str:
    require_configured()
    return get_settings().jwt_secret


def account_stamp(created_at: datetime) -> int:
    """The account's creation time in microseconds. SQLite can reuse the id of a deleted user (B-11), so a token
    names the account by id AND this stamp; an old owner's token then cannot open a new account with the same id."""
    created = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)     # SQLite drops the zone
    return round(created.timestamp() * 1_000_000)


def create_token(user_id: int, now: datetime | None = None, created_at: datetime | None = None) -> tuple[str, int]:
    """(token, seconds until it expires). The API always passes `created_at`; a token without it is refused."""
    now = now or datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + TOKEN_TTL}
    if created_at is not None:
        payload["acc"] = account_stamp(created_at)
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG), int(TOKEN_TTL.total_seconds())


def read_token(token: str) -> tuple[int, int | None]:
    """(user id, account stamp or None). The caller compares the stamp with the user row."""
    try:
        data = jwt.decode(token, _secret(), algorithms=[JWT_ALG], options={"require": ["sub", "exp"]})
        acc = data.get("acc")
        return int(data["sub"]), (int(acc) if acc is not None else None)
    except (jwt.PyJWTError, ValueError, TypeError) as e:
        raise AuthError("invalid_token") from e


def forget_phone(phone: str) -> None:
    """Delete-my-data (B-11): drop a pending OTP for this phone."""
    _store.pop(phone, None)


def reset_store() -> None:
    """Tests only."""
    _store.clear()
