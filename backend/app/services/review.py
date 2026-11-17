"""Run and store a 3-month review for one shop (M-08): gathers the numbers, calls the pure engine, saves the row."""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ml import review as engine
from app.models import DailyLog, Forecast, Loan, Review, Shop, StockItem
from app.rules import get_rules
from app.services import loans as loan_dates
from app.services import stock as stock_service


def daily_logs(db: Session, shop_id: int, last_day: date) -> dict[date, dict]:
    rows = db.execute(select(DailyLog.day, func.sum(DailyLog.sales), func.sum(DailyLog.purchases),
                             func.sum(DailyLog.expenses))
                      .where(DailyLog.shop_id == shop_id, DailyLog.day <= last_day).group_by(DailyLog.day))
    return {d: {"sales": float(s), "purchases": float(p), "expenses": float(e)} for d, s, p, e in rows}


def loan_figures(loans: list[Loan], period_start: date, period_end: date) -> tuple[float | None, float, bool]:
    """(total monthly EMI of loans running in the period or None, EMIs due up to period_end, any loan without dates).
    A loan stored without start date and tenure (before DEC-53) counts towards the monthly EMI, but its past
    instalments are unknown and are not taken off the cash figure."""
    monthly, paid, undated = 0.0, 0.0, False
    for ln in loans:
        if ln.start_date is None or ln.tenure_months is None:
            monthly, undated = monthly + ln.emi, True
            continue
        dates = loan_dates.schedule(ln.start_date, ln.due_day, ln.tenure_months)
        paid += ln.emi * sum(d <= period_end for d in dates)
        if ln.start_date <= period_end and any(d >= period_start for d in dates):
            monthly += ln.emi
    return (monthly if monthly > 0 else None), paid, undated


def cash_position(opening_cash: float | None, logs: dict[date, dict], emis_paid: float) -> float | None:
    """Opening cash + every logged sale - purchase - expense - instalments assumed paid on their due dates (DEC-65).
    None when the owner never entered an opening figure."""
    if opening_cash is None:
        return None
    return opening_cash + sum(v["sales"] - v["purchases"] - v["expenses"] for v in logs.values()) - emis_paid


def run(db: Session, shop: Shop, today: date) -> Review:
    """Review the 90 days ending yesterday and store it. Running again for the same period replaces the row."""
    rules = get_rules()
    period_end = today - timedelta(days=1)
    period_start = period_end - timedelta(days=rules.review.window_days - 1)
    logs = daily_logs(db, shop.id, period_end)
    prior = db.scalars(select(Forecast).where(Forecast.shop_id == shop.id, Forecast.kind == "setup")
                       .order_by(Forecast.id.desc()).limit(1)).first()
    months = None if prior is None else [
        {"start": date.fromisoformat(m["start"]), "end": date.fromisoformat(m["end"]), "p50": m["p50"]}
        for m in prior.horizon_months]
    loans = list(db.scalars(select(Loan).where(Loan.shop_id == shop.id)))
    monthly_emi, emis_paid, undated = loan_figures(loans, period_start, period_end)
    has_stock = (db.scalar(select(func.count()).select_from(StockItem)
                           .where(StockItem.shop_id == shop.id)) or 0) > 0
    advice = stock_service.advice(db, shop.id, today, rules.stock) if has_stock else None

    out = engine.review(
        period_end=period_end, rule=rules.review, actions=rules.actions, logs=logs, forecast_months=months,
        monthly_emi=monthly_emi, cash=cash_position(shop.opening_cash, logs, emis_paid),
        stockout_days=advice["stockout_days"] if advice else None,
        dead_stock_value=advice["dead_stock_value"] if advice else None, launch_date=shop.launch_date)
    notes = [*out["notes"], *(["loan_without_dates_emis_paid_unknown"] if undated else []),
             *([] if has_stock else ["no_stock_records"])]

    row = db.scalars(select(Review).where(Review.shop_id == shop.id, Review.period_end == period_end)).first()
    if row is None:
        row = Review(shop_id=shop.id, period_end=period_end)
        db.add(row)
    row.period_start, row.decision, row.indicators = out["period_start"], out["decision"], out["indicators"]
    row.reasons, row.actions, row.confidence, row.created_on = out["reasons"], out["actions"], out["confidence"], today
    row.details = {"notes": notes, "confidence_reasons": out["confidence_reasons"],
                   "forecast_id": prior.id if prior else None}
    db.commit()
    return row
