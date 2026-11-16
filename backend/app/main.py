from fastapi import FastAPI

from app.api import health

app = FastAPI(
    title="Business Sarthi API",
    version="0.1.0",
    description="Prototype backend. Forecasts are estimates trained on synthetic data.",
)
app.include_router(health.router, prefix="/api")
