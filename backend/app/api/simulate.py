"""Expansion simulator endpoint (M-10, ML9, DEC-88). Every range comes from data/rules/expansion.yaml (assumptions)."""
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import Db, OwnShopConsented
from app.ml import simulate as ml9
from app.models import DailyLog, Forecast
from app.rules import get_rules
from app.schemas.simulate import SimulateIn, SimulateOut
from app.services import clock

router = APIRouter(prefix="/shops", tags=["simulate"])


def own_margin(db, shop_id: int, today: date, window_days: int) -> tuple[float | None, int]:
    """(gross margin = (sales - purchases) / sales over the logged days of the window, logged days)."""
    first = today - timedelta(days=window_days)
    rows = db.execute(select(DailyLog.day, func.sum(DailyLog.sales), func.sum(DailyLog.purchases))
                      .where(DailyLog.shop_id == shop_id, DailyLog.day >= first, DailyLog.day < today)
                      .group_by(DailyLog.day)).all()
    sales = sum(float(s) for _, s, _ in rows)
    purchases = sum(float(p) for _, _, p in rows)
    return ((sales - purchases) / sales if sales > 0 else None), len(rows)


def pick_margin(value: float | None, days: int, rules) -> dict:
    ex, assumed = rules.expansion, rules.forecast.gross_margin
    reason = None
    if days < ex.margin_min_logged_days:
        reason = "few_logged_days"
    elif value is None or not 0 < value < 1:
        reason = "own_margin_out_of_range"     # e.g. buying stock faster than selling it in the window
    if reason:
        return {"value": assumed, "source": "assumed", "reason": reason, "logged_days": days,
                "window_days": ex.margin_window_days}
    return {"value": round(value, 4), "source": "own_logs", "reason": None, "logged_days": days,
            "window_days": ex.margin_window_days}


@router.post("/{shop_id}/simulate", response_model=SimulateOut)
def simulate(shop: OwnShopConsented, db: Db, body: SimulateIn | None = None) -> dict:
    """Payback range and P(payback < target) per expansion option. Nothing is stored."""
    rules = get_rules()
    ex = rules.expansion
    today = clock.today()
    fc = db.scalars(select(Forecast).where(Forecast.shop_id == shop.id).order_by(Forecast.id.desc()).limit(1)).first()
    if fc is None:
        raise HTTPException(409, detail={"code": "forecast_missing"})
    months = [{**m, "start": date.fromisoformat(m["start"]), "end": date.fromisoformat(m["end"])}
              for m in fc.horizon_months]
    try:
        band, ahead = ml9.monthly_band(months, today, ex.months_ahead)
    except ValueError as e:
        raise HTTPException(409, detail={"code": "forecast_has_no_month_ahead"}) from e
    margin = pick_margin(*own_margin(db, shop.id, today, ex.margin_window_days), rules)
    seed = shop.id * 1_000_003 + fc.id                       # same shop + same forecast = same answer
    horizon = rules.forecast.payback_max_months
    try:
        options = ml9.simulate(band, margin["value"], ex, seed=seed, horizon_months=horizon,
                               options=body.options if body else None)
    except KeyError as e:
        raise HTTPException(422, detail={"code": "unknown_option", "options": e.args[0],
                                         "known": list(ex.options)}) from e
    notes = ["simulate.assumed_ranges", "simulate.not_a_promise"]
    if margin["source"] == "assumed":
        notes.append("simulate.assumed_margin")
    if any(o["no_upfront_cost"] for o in options):
        notes.append("simulate.no_upfront_cost")
    return {"shop_id": shop.id, "as_of": today, "rules_version": ex.version, "draws": ex.draws, "seed": seed,
            "horizon_months": horizon,
            "base": {"forecast_id": fc.id, "forecast_kind": fc.kind, "made_on": fc.made_on,
                     "months_used": [{"k": m["k"], "start": m["start"], "end": m["end"]} for m in ahead],
                     "monthly_revenue": {k: round(v) for k, v in band.items()}},
            "margin": margin, "options": options, "notes": notes}
