from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

Language = Literal["hi", "en"]                       # SPEC: Hindi and English in the prototype
Purpose = Literal["shop_data", "benchmarking"]


class MeUpdate(BaseModel):
    language: Language


class ConsentIn(BaseModel):
    purpose: Purpose


class ConsentOut(BaseModel):
    purpose: str
    required: bool
    active: bool
    given_at: UtcDatetime | None = None


class ConsentRecord(BaseModel):
    purpose: str
    given_at: UtcDatetime
    withdrawn_at: UtcDatetime | None = None


class ShopIn(BaseModel):
    """Idea intake. Size and city tier are typed by the owner (DEC-42)."""
    name: str = Field(min_length=1, max_length=80)
    shop_type: Literal["kirana"] = "kirana"
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    size_sqft: float = Field(ge=30, le=5000)
    city_tier: Literal[1, 2, 3]
    budget: float = Field(gt=0, le=1e8)
    monthly_rent: float = Field(ge=0, le=1e7)
    staff_count: int = Field(default=0, ge=0, le=50)
    launch_date: date | None = None                  # None = idea stage, not opened yet
    opening_cash: float | None = Field(default=None, ge=0, le=1e9)   # cash at launch; None = not told (DEC-65)


class ShopPatch(BaseModel):
    """Fields the owner may change later. Only opening cash for now (DEC-65)."""
    model_config = ConfigDict(extra="forbid")
    opening_cash: float | None = Field(ge=0, le=1e9)


class ShopOut(ShopIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_demo: bool
