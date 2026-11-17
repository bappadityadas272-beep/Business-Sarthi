from contextlib import asynccontextmanager

from fastapi import FastAPI

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
    reviews,
    schemes,
    shops,
    sos,
    stock,
)
from app.jobs import scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler.start()                                # no-op when SCHEDULER_ENABLED=0
    yield
    scheduler.stop()


app = FastAPI(
    lifespan=lifespan,
    title="Business Sarthi API",
    version="0.1.0",
    description="Prototype backend. Forecasts are estimates trained on synthetic data.",
)
for module in (health, auth, me, shops, forecast, logs, stock, loans, reviews, alerts, notifications, chat, schemes,
               sos, dev):
    app.include_router(module.router, prefix="/api")
