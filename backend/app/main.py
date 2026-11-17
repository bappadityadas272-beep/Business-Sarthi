"""FastAPI app: routers under /api, plus the hardening layer (DEC-90, DEC-91): JSON logs with phones masked, one
error shape, CORS for the configured origins only, a body size limit, rate limits, dev routes only in DEV_MODE."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import errors
from app.api import (
    alerts,
    auth,
    chat,
    dev,
    forecast,
    health,
    loans,
    logs,
    me,
    notifications,
    pricing,
    reviews,
    schemes,
    shops,
    simulate,
    sos,
    stock,
)
from app.config import get_settings
from app.jobs import scheduler
from app.ml import forecast as fc
from app.obs import BodyLimit, DevGate, RequestLog, setup_logging

setup_logging()
log = logging.getLogger("sarthi.startup")


def startup_checks() -> dict:
    """Clear errors in the log when the forecast model is missing or stale or the LLM key is missing. The API still
    starts (other modules work); forecasts answer 503 model_not_ready and /api/ready says not_ready."""
    from app.api.health import llm_check
    m, llm = fc.model_status(), llm_check()
    if not m["ok"]:
        log.error("forecast model not ready: %s. Run `make train` (forecasts answer 503 until then)", m["reason"])
    if not llm["ok"]:
        log.error("LLM provider %s has no LLM_API_KEY; chat will fail. Set it in .env or use LLM_PROVIDER=stub",
                  llm["provider"])
    return {"model": m, "llm": llm}


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup_checks()
    scheduler.start()                                # no-op when SCHEDULER_ENABLED=0
    yield
    scheduler.stop()


app = FastAPI(
    lifespan=lifespan,
    title="Business Sarthi API",
    version="0.1.0",
    description="Prototype backend. Forecasts are estimates trained on synthetic data.",
)
for module in (health, auth, me, shops, forecast, logs, stock, loans, reviews, alerts, notifications, pricing, chat, schemes,
               simulate, sos, dev):
    app.include_router(module.router, prefix="/api")

errors.install(app)
app.add_middleware(DevGate)
app.add_middleware(BodyLimit)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origin_list, allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
app.add_middleware(RequestLog)                       # outermost: logs every answer, including 404, 413 and 429

_full_openapi = app.openapi


def openapi() -> dict:
    """With DEV_MODE off the dev routes are not in the docs either (DEC-91)."""
    app.openapi_schema = None
    schema = _full_openapi()
    if not get_settings().dev_mode:
        schema = {**schema, "paths": {p: v for p, v in schema["paths"].items() if not p.startswith("/api/dev")}}
    return schema


app.openapi = openapi
