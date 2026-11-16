from datetime import date
from typing import Any, Literal

from pydantic import BaseModel


class ReviewOut(BaseModel):
    """A stored review. Reasons, actions and notes are message keys with values; the frontend localises them."""
    id: int
    shop_id: int
    period_start: date
    period_end: date
    created_on: date | None
    decision: Literal["grow", "hold", "pivot"]
    indicators: dict[str, Any]
    reasons: list[dict[str, Any]]
    actions: list[dict[str, str]]
    confidence: Literal["low", "medium"]
    confidence_reasons: list[str]
    notes: list[str]
    data_completeness: float
    is_estimate: bool = True
    thresholds_are_assumptions: bool = True      # review_rules.yaml: initial values, not yet tuned on real shops
