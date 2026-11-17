from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class SimulateIn(BaseModel):
    options: list[str] | None = Field(default=None, min_length=1, max_length=10)   # empty: every option in the rules


class Paybacks(BaseModel):
    p10: float | None          # None: beyond the horizon, or no payback
    p50: float | None
    p90: float | None


class Band(BaseModel):
    p10: int
    p50: int
    p90: int


class OptionOut(BaseModel):
    option: str
    payback_months: Paybacks
    p_payback_under_target: float
    payback_target_months: int
    share_no_payback: float
    extra_revenue_month: Band
    extra_profit_month: Band
    no_upfront_cost: bool
    assumptions: dict


class BaseOut(BaseModel):
    forecast_id: int
    forecast_kind: str
    made_on: date
    months_used: list[dict]
    monthly_revenue: Band


class MarginOut(BaseModel):
    value: float
    source: Literal["own_logs", "assumed"]
    reason: str | None
    logged_days: int
    window_days: int


class SimulateOut(BaseModel):
    shop_id: int
    as_of: date
    is_estimate: bool = True
    assumption: bool = True
    rules_version: int
    draws: int
    seed: int
    horizon_months: int
    base: BaseOut
    margin: MarginOut
    options: list[OptionOut]
    notes: list[str]
