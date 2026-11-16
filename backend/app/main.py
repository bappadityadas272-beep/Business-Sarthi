from fastapi import FastAPI

from app.api import auth, forecast, health, loans, logs, me, reviews, shops, stock

app = FastAPI(
    title="Business Sarthi API",
    version="0.1.0",
    description="Prototype backend. Forecasts are estimates trained on synthetic data.",
)
for module in (health, auth, me, shops, forecast, logs, stock, loans, reviews):
    app.include_router(module.router, prefix="/api")
