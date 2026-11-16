"""Set-up forecast (M-05) and re-forecast (M-06) endpoints."""
from dataclasses import asdict
from datetime import date, timedelta
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.api.deps import Db, OwnShopConsented
from app.ml import forecast as fc
from app.ml import reforecast as rf
from app.models import DailyLog, Forecast
from app.rules import get_rules
from app.schemas.forecast import ForecastIn, ForecastOut, ReforecastOut
from app.services import clock, osm

router = APIRouter(prefix="/shops", tags=["forecast"])


def forecast_model():
    """(model, card). Overridden in tests with a small model."""
    try:
        return fc.load_model()
    except fc.ModelNotReady as e:
        raise HTTPException(503, detail={"code": "model_not_ready"}) from e


Model = Annotated[tuple, Depends(forecast_model)]


@router.post("/{shop_id}/forecast", response_model=ForecastOut)
def make_setup_forecast(shop: OwnShopConsented, db: Db, model: Model, body: ForecastIn | None = None) -> dict:
    if shop.size_sqft is None or shop.city_tier is None:
        raise HTTPException(422, detail={"code": "shop_profile_incomplete", "fields": ["size_sqft", "city_tier"]})
    today = clock.today()
    open_date, open_source = fc.resolve_open_date(body.open_date if body else None, shop.launch_date, today)
    try:
        loc = osm.location_counts(db, shop.lat, shop.lon)
    except osm.OsmError as e:
        raise HTTPException(503, detail={"code": "location_data_unavailable"}) from e
    rules = get_rules()
    out = fc.setup_forecast(
        shop={"size_sqft": shop.size_sqft, "city_tier": shop.city_tier, "monthly_rent": shop.monthly_rent,
              "staff_count": shop.staff_count, "budget": shop.budget},
        counts=loc.counts, location_source=loc.source, open_date=open_date, model=model[0], card=model[1],
        assumptions=rules.forecast, split_rule=rules.investment)
    row = Forecast(shop_id=shop.id, kind="setup", made_on=today, drivers=out["drivers"],
                   horizon_months=[{"k": m["k"], "start": m["start"].isoformat(), "end": m["end"].isoformat(),
                                    "p10": m["p10"], "p50": m["p50"], "p90": m["p90"]} for m in out["months"]])
    db.add(row)
    db.commit()
    location = {**{k: v for k, v in asdict(loc).items() if k != "cell"}, "is_measured": loc.is_measured}
    return {**out, "forecast_id": row.id, "shop_id": shop.id, "made_on": today, "open_date_source": open_source,
            "location": location}


@router.post("/{shop_id}/reforecast", response_model=ReforecastOut)
def make_reforecast(shop: OwnShopConsented, db: Db) -> dict:
    """Blend the latest set-up forecast with the shop's own logged sales, using days up to yesterday only."""
    prior = db.scalars(select(Forecast).where(Forecast.shop_id == shop.id, Forecast.kind == "setup")
                       .order_by(Forecast.id.desc()).limit(1)).first()
    if prior is None:
        raise HTTPException(409, detail={"code": "setup_forecast_missing"})
    months = [{**m, "start": date.fromisoformat(m["start"]), "end": date.fromisoformat(m["end"])}
              for m in prior.horizon_months]
    today = clock.today()
    origin, start = today - timedelta(days=1), months[0]["start"]
    rows = db.execute(select(DailyLog.day, func.sum(DailyLog.sales)).where(
        DailyLog.shop_id == shop.id, DailyLog.day >= start, DailyLog.day <= origin).group_by(DailyLog.day)).all()
    daily = pd.Series({pd.Timestamp(d): float(v) for d, v in rows}, dtype=float)   # a day with no log row is MISSING
    try:
        out = rf.reforecast(daily, origin, months, get_rules().blend, start=start)
    except rf.NotEnoughData as e:
        raise HTTPException(422, detail={"code": e.code, **e.params}) from e
    row = Forecast(shop_id=shop.id, kind="reforecast", made_on=today, drivers=[],
                   horizon_months=[{"k": m["k"], "start": m["start"].isoformat(), "end": m["end"].isoformat(),
                                    "p10": m["p10"], "p50": m["p50"], "p90": m["p90"]} for m in out["months"]])
    db.add(row)
    db.commit()
    return {**out, "forecast_id": row.id, "shop_id": shop.id, "made_on": today, "based_on_forecast_id": prior.id}
