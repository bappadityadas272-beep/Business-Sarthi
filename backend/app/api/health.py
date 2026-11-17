"""Liveness, readiness and the "about" card (hardening, DEC-90).

/api/health  the process answers (used by the compose healthcheck); no dependencies checked.
/api/ready   200 only when the database answers with its tables, the forecast model is present and not stale, and
             the LLM is configured (the offline stub counts as configured), and login has a real JWT_SECRET outside
             dev mode (DEC-97). 503 otherwise, with each check's reason.
             Never calls the LLM and never shows a key.
/api/about   what this prototype is: the model card summary (is_synthetic) and the rule files' assumption flags.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import Db
from app.config import get_settings
from app.ml import forecast as fc
from app.rules import FILES, get_rules
from app.services import auth

router = APIRouter(tags=["health"])
VERSION = "0.1.0"


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "version": VERSION, "dev_mode": s.dev_mode, "llm_provider": s.llm_provider}


def llm_check() -> dict:
    s = get_settings()
    if s.llm_provider == "stub":
        return {"ok": True, "provider": "stub", "reason": "offline_stub_answers"}
    if not s.llm_api_key:
        return {"ok": False, "provider": s.llm_provider, "reason": "llm_api_key_missing"}
    return {"ok": True, "provider": s.llm_provider, "reason": None}


def db_check(db) -> dict:
    try:
        db.execute(text('SELECT 1 FROM "user" LIMIT 1'))
        db.execute(text('SELECT 1 FROM "shop" LIMIT 1'))
    except SQLAlchemyError:                              # no details: they may hold the database path
        db.rollback()
        return {"ok": False, "reason": "database_unavailable_or_not_migrated", "fix": "make migrate"}
    return {"ok": True, "reason": None}


@router.get("/ready")
def ready(db: Db) -> JSONResponse:
    m = fc.model_status()
    checks = {"database": db_check(db),
              "model": {k: m[k] for k in ("ok", "reason", "version", "fix")},
              "llm": llm_check(),
              "auth": auth.auth_check()}
    ok = all(c["ok"] for c in checks.values())
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)


CARD_KEYS = ("model", "version", "is_synthetic", "notice", "trained_on", "target", "horizon_months", "features",
             "band", "metrics_calibration_set_before_conformal")


@router.get("/about")
def about() -> dict:
    st = fc.model_status()
    card = None
    if st["reason"] != "model_files_missing":
        full = fc.load_card()
        card = {**{k: v for k, v in full.items() if k in CARD_KEYS}, "data": full.get("data", {})}
    r = get_rules()
    by_type = {type(getattr(r, f)): getattr(r, f) for f in type(r).model_fields}
    rules = {name: {"version": by_type[cls].version, "assumption": by_type[cls].assumption}
             for name, cls in FILES.items()}
    return {"app": "Business Sarthi", "version": VERSION, "is_prototype": True,
            "notice": "Prototype. Forecasts are ranges from a model trained on SYNTHETIC data, not promises. "
                      "Not financial, legal or medical advice.",
            "model": {"status": {k: st[k] for k in ("ok", "reason")}, "card": card,
                      "is_synthetic": st["is_synthetic"]},
            "rules": rules}

