from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import UtcDatetime


class ForecastIn(BaseModel):
    open_date: date | None = None          # empty: the shop's launch date, else the first day of next month


class Trio(BaseModel):
    p10: int
    p50: int
    p90: int


class ForecastMonth(Trio):
    k: int
    start: date
    end: date
    gross_profit: Trio
    operating_profit: Trio


class Reason(BaseModel):
    key: str
    params: dict = {}


class Confidence(BaseModel):
    level: Literal["low", "medium", "high"]
    reasons: list[Reason]


class Driver(BaseModel):
    feature: str
    value: float
    direction: Literal["up", "down"]
    message_key: str
    effect_inr_per_month: int
    text: str


class Assumptions(BaseModel):
    gross_margin: float
    staff_wage_monthly: float
    other_fixed_costs_monthly: float
    is_assumption: bool = True
    source: str


class BreakEven(BaseModel):
    revenue_monthly: int
    first_month_p50_reaches: int | None


class Payback(BaseModel):
    fastest_months: int | None             # every month at P90
    typical_months: int | None             # every month at P50
    slowest_months: int | None             # every month at P10; None = not within max_months
    investment: int
    max_months: int
    extended_beyond_forecast: bool
    is_assumption: bool = True


class InvestmentSplitOut(BaseModel):
    budget: int
    deposit: int
    cash_reserve: int
    stock: int | None
    fixtures: int | None
    budget_too_low: bool
    shortfall: int
    is_assumption: bool = True


class LocationOut(BaseModel):
    counts: dict[str, int]
    source: Literal["live", "cache", "mock", "fallback_assumed"]
    is_measured: bool
    radius_m: int
    fetched_at: UtcDatetime | None
    attribution: str | None


class ForecastOut(BaseModel):
    forecast_id: int
    shop_id: int
    kind: Literal["setup", "reforecast"]
    made_on: date
    is_estimate: bool = True
    trained_on_synthetic: bool
    notice: str
    model_version: str | None
    open_date: date
    open_date_source: Literal["request", "shop", "assumed_next_month"]
    location: LocationOut
    months: list[ForecastMonth]
    assumptions: Assumptions
    fixed_costs_monthly: int
    break_even: BreakEven
    payback: Payback
    investment_split: InvestmentSplitOut
    drivers: list[Driver]
    confidence: Confidence


class ReforecastMonth(Trio):
    k: int
    start: date
    end: date
    prior_p50: int                         # the set-up forecast for the same month
    own_p50: int                           # the shop's own model alone
    actual_so_far: int                     # sales already logged in this month
    days_logged: int
    days_open: int                         # days of the month still estimated


class ReforecastOut(BaseModel):
    forecast_id: int
    shop_id: int
    kind: Literal["reforecast"]
    made_on: date
    origin: date                           # last day whose logs were used
    based_on_forecast_id: int
    is_estimate: bool = True
    trained_on_synthetic: bool = True
    months: list[ReforecastMonth]
    n_days: int
    span_days: int
    missing_share: float
    weight_own: float
    k: float
    own_model: str
    observed_error: float | None
    interval_rescale: float
    confidence: Confidence
