"""Set-up forecast endpoint (M-05)."""
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import Db, OwnShopConsented
from app.ml import forecast as fc
from app.models import Forecast
from app.rules import get_rules
from app.schemas.forecast import ForecastIn, ForecastOut
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
