"""Request and response shapes for daily logs, stock, assets and loans (B-05 to B-07)."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["staples", "dairy", "snacks_beverages", "household", "personal_care", "other"]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- daily logs ----
class LogEntry(_Out):
    day: date
    category: Category
    sales: float = Field(0, ge=0, le=1e9)
    purchases: float = Field(0, ge=0, le=1e9)
    expenses: float = Field(0, ge=0, le=1e9)


class LogsIn(BaseModel):
    entries: list[LogEntry] = Field(min_length=1, max_length=2000)


class LogsSaved(BaseModel):
    created: int
    updated: int


class DayTotal(BaseModel):
    day: date
    sales: float
    purchases: float
    expenses: float


class LogsOut(BaseModel):
    date_from: date | None
    date_to: date | None
    days_logged: int
    entries: list[LogEntry]
    daily_totals: list[DayTotal]


# ---- stock ----
class StockItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    category: Category
    unit: str = Field(min_length=1, max_length=16)
    cost: float = Field(ge=0, le=1e7)
    price: float = Field(ge=0, le=1e7)
    opening_qty: float = Field(0, ge=0, le=1e7)      # stored as an `adjust` move on `opening_day`
    opening_day: date | None = None                  # default: today


class StockItemOut(BaseModel):
    id: int
    name: str
    category: str
    unit: str
    cost: float
    price: float
    reorder_point: float | None
    on_hand: float                                   # always the sum of the moves of the item
    stock_value: float                               # on_hand x cost


class StockAdviceItem(BaseModel):
    item_id: int
    name: str
    category: str
    unit: str
    abc: Literal["A", "B", "C"]
    on_hand: float
    stock_value: float
    demand_source: Literal["own_sales", "category_average", "none"]
    history_days: int
    mean_daily_demand: float | None                  # None: a new item with no other item in its category
    std_daily_demand: float | None
    reorder_point: float | None
    reorder_now: bool
    reorder_qty: float | None
    cover_days: float | None                         # on hand / mean daily demand
    days_since_last_sale: int | None
    dead_stock: bool
    overstock: bool
    stockout_days: int


class StockAdviceOut(BaseModel):
    """Estimates from the shop's own stock moves and the rules in data/rules/stock.yaml (assumptions)."""
    as_of: date
    is_estimate: bool = True
    items: list[StockAdviceItem]
    reorder_list: list[int]                          # item ids to reorder now: A items first, then least cover
    dead_stock_value: float
    overstock_value: float
    stockout_days: int                               # days in the window on which an active item ended at zero
    window_days: int
    settings: dict[str, float]


class MoveIn(BaseModel):
    """`qty` is positive for purchase, sale and waste (the kind gives the direction); `adjust` is signed."""
    item_id: int
    day: date
    qty: float = Field(ge=-1e7, le=1e7)
    kind: Literal["purchase", "sale", "adjust", "waste"]


class MovesIn(BaseModel):
    moves: list[MoveIn] = Field(min_length=1, max_length=2000)


class MovesSaved(BaseModel):
    saved: int
    items: list[StockItemOut]                        # the items touched, with their new on-hand


class AssetIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    cost: float = Field(ge=0, le=1e9)
    bought_on: date | None = None


class AssetOut(_Out):
    id: int
    name: str
    cost: float
    bought_on: date | None


# ---- loans ----
class LoanIn(BaseModel):
    principal: float = Field(gt=0, le=1e9)
    emi: float = Field(gt=0, le=1e9)
    due_day: int = Field(ge=1, le=31)
    start_date: date
    tenure_months: int = Field(ge=1, le=360)


class Instalment(BaseModel):
    n: int
    due_date: date
    emi: float


class LoanOut(BaseModel):
    id: int
    principal: float
    emi: float
    due_day: int
    start_date: date | None
    tenure_months: int | None
    next_due_date: date | None
    days_to_next_due: int | None
    instalments_total: int | None
    instalments_due_so_far: int | None               # by date only: the app does not track payments
    instalments_left: int | None
    last_due_date: date | None
    schedule: list[Instalment]
