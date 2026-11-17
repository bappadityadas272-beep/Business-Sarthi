"""Load and validate every rule file in data/rules/ with Pydantic (checkpoint D-04).

Usage: `load_rules()` returns a validated `Rules` bundle; `python -m app.rules` validates and prints a summary.
Invalid files raise `RuleFileError` naming the file.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.config import REPO_ROOT

RULES_DIR = REPO_ROOT / "data" / "rules"
CATEGORIES = ("staples", "dairy", "snacks_beverages", "household", "personal_care")
INDICATORS = Literal[
    "revenue_vs_p50", "gross_margin", "dscr", "cash_runway_days", "growth_rate",
    "stockout_days", "dead_stock_value", "data_completeness",
]
Op = Literal["<", "<=", ">", ">="]
Severity = Literal["info", "warn", "critical"]
Decision = Literal["grow", "hold", "pivot"]


class RuleFileError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Header(_Strict):
    version: int = Field(ge=1)
    source: str
    assumption: bool


class Condition(_Strict):
    indicator: INDICATORS
    op: Op
    value: float
    for_months: int | None = Field(default=None, ge=1, le=3)   # the N most recent 30-day blocks (DEC-64)
    pass_when_no_loan: bool = False                            # dscr only: met when the shop has no loan (DEC-64)

    @model_validator(mode="after")
    def _dscr_only(self):
        if (self.for_months or self.pass_when_no_loan) and self.indicator != "dscr":
            raise ValueError("for_months and pass_when_no_loan are only supported for dscr")
        return self


# ---- review_rules.yaml ----
class DecisionRule(_Strict):
    decision: Decision
    match: Literal["any", "all", "always"]
    conditions: list[Condition]

    @model_validator(mode="after")
    def _conditions_match_mode(self):
        if (self.match == "always") != (not self.conditions):
            raise ValueError("match 'always' needs no conditions; 'any'/'all' need at least one")
        return self


class ReviewRules(_Header):
    window_days: int = Field(gt=0)
    max_actions: int = Field(ge=1, le=5)
    min_block_logged_days: int = Field(ge=1, le=30)
    min_completeness_for_medium_confidence: float = Field(ge=0, le=1)
    decisions: list[DecisionRule]

    @model_validator(mode="after")
    def _complete_and_ordered(self):
        names = [d.decision for d in self.decisions]
        if sorted(names) != ["grow", "hold", "pivot"]:
            raise ValueError(f"need exactly one each of grow/hold/pivot, got {names}")
        if self.window_days != 90:
            raise ValueError("window_days must be 90: the engine works with three 30-day blocks")
        if self.decisions[-1].match != "always":
            raise ValueError("last decision must be the 'always' fallback")
        return self


# ---- alert_rules.yaml ----
class _Alert(_Strict):
    severity: Severity
    message_key: str = Field(pattern=r"^alert\.[a-z_]+$")


class SalesDip(_Alert):
    short_window_days: int = Field(gt=0)
    long_window_days: int = Field(gt=0)
    ratio_below: float = Field(gt=0, lt=1)
    robust_z_below: float = Field(lt=0)

    @model_validator(mode="after")
    def _windows(self):
        if self.short_window_days >= self.long_window_days:
            raise ValueError("short window must be shorter than long window")
        return self


class LowStock(_Alert):
    at_or_below_reorder_point: bool


class EmiDue(_Alert):
    days_before_due: int = Field(gt=0)
    projected_cash_below_emi: bool


class DeadStock(_Alert):
    no_sale_days: int = Field(gt=0)


class DataGap(_Alert):
    no_log_days: int = Field(gt=0)


class AlertRuleSet(_Strict):
    sales_dip: SalesDip
    low_stock: LowStock
    emi_due: EmiDue
    dead_stock: DeadStock
    data_gap: DataGap


class AlertRules(_Header):
    rules: AlertRuleSet


# ---- osm_tags.yaml ----
class TagFilter(_Strict):
    key: str = Field(pattern=r"^[a-z_:]+$")
    values: list[str] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def _plain_values(cls, v):
        if any(not x.replace("_", "").isalnum() for x in v):      # values go into an Overpass regex
            raise ValueError("tag values must be plain words")
        return v


class OsmTags(_Header):
    radius_m: int = Field(gt=0, le=2000)
    cache_days: int = Field(gt=0)
    cell_decimals: int = Field(ge=2, le=5)
    features: dict[Literal["competitors", "homes", "schools", "transit", "banks_atms"], list[TagFilter]]

    @model_validator(mode="after")
    def _all_features(self):
        if len(self.features) != 5 or any(not v for v in self.features.values()):
            raise ValueError("need tag filters for all 5 features")
        return self


# ---- blend.yaml ----
class Blend(_Header):
    k: float = Field(gt=0)
    level_only_below_days: int = Field(ge=0)
    low_confidence_missing_share: float = Field(gt=0, lt=1)
    low_confidence_below_days: int = Field(ge=0)
    min_days: int = Field(ge=2)
    damped_trend: bool
    error_rescale_min: float = Field(gt=0, le=1)
    error_rescale_max: float = Field(ge=1)
    interval_scale: float = Field(gt=0)

    def weight(self, n_days: int) -> float:
        """Weight on the shop's own model: n / (n + k)."""
        return n_days / (n_days + self.k) if n_days > 0 else 0.0


# ---- stock.yaml ----
class Stock(_Header):
    z: float = Field(ge=0)
    lead_time_days: int = Field(ge=1)
    cover_days: int = Field(ge=1)
    dead_no_sale_days: int = Field(ge=1)
    overstock_cover_days: int = Field(ge=1)
    abc_a_share: float = Field(gt=0, lt=1)
    abc_b_share: float = Field(ge=0, lt=1)
    abc_window_days: int = Field(ge=1)
    demand_halflife_days: float = Field(gt=0)
    ignore_empty_shelf_days: bool
    std_window_days: int = Field(ge=2)
    new_item_below_days: int = Field(ge=0)
    stockout_window_days: int = Field(ge=1)

    @model_validator(mode="after")
    def _consistent(self) -> "Stock":
        if self.abc_a_share + self.abc_b_share > 1:
            raise ValueError("abc_a_share + abc_b_share must not exceed 1")
        if self.overstock_cover_days <= self.cover_days:
            raise ValueError("overstock_cover_days must be above cover_days")
        return self


# ---- actions.yaml ----
class Action(_Strict):
    id: str = Field(pattern=r"^[a-z_]+$")
    message_key: str = Field(pattern=r"^action\.[a-z_]+$")
    decisions: list[Decision] = Field(min_length=1)
    trigger: Condition
    priority: int = Field(ge=1)


class Actions(_Header):
    actions: list[Action] = Field(min_length=1)

    @field_validator("actions")
    @classmethod
    def _unique_ids(cls, v):
        ids = [a.id for a in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate action ids")
        return v


# ---- location_weights.yaml ----
class FeatureWeight(_Strict):
    weight: float = Field(gt=0, le=1)
    cap: float = Field(gt=0)


class CompetitorWeight(_Strict):
    weight: float = Field(lt=0)
    free_count: int = Field(ge=0)
    cap: float = Field(gt=0)


class LocationWeights(_Header):
    radius_m: int = Field(gt=0, le=5000)
    features: dict[Literal["residential", "schools", "transit", "banks_atms"], FeatureWeight]
    competitors: CompetitorWeight

    @model_validator(mode="after")
    def _weights_sum_to_one(self):
        if len(self.features) != 4:
            raise ValueError("need all 4 features: residential, schools, transit, banks_atms")
        total = sum(f.weight for f in self.features.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"positive feature weights must sum to 1.0, got {total}")
        return self


# ---- product_mix.yaml ----
class MixProfile(_Strict):
    feature: Literal["residential", "schools", "transit", "banks_atms", "competitors"]
    min_count: int = Field(ge=0)
    adjust: dict[str, float]
    suggest_items: list[str] = []

    @field_validator("adjust")
    @classmethod
    def _known_and_balanced(cls, v):
        bad = set(v) - set(CATEGORIES)
        if bad:
            raise ValueError(f"unknown categories {bad}")
        if abs(sum(v.values())) > 1e-6:
            raise ValueError("adjustments must net to 0 so the mix still sums to 1")
        return v


class ShopTypeMix(_Strict):
    base: dict[str, float]
    profiles: dict[str, MixProfile] = {}

    @field_validator("base")
    @classmethod
    def _base_is_distribution(cls, v):
        if set(v) != set(CATEGORIES):
            raise ValueError(f"base must list exactly {CATEGORIES}")
        if any(x < 0 for x in v.values()) or abs(sum(v.values()) - 1.0) > 1e-6:
            raise ValueError("base shares must be non-negative and sum to 1.0")
        return v


class ProductMix(_Header):
    categories: list[str]
    shop_types: dict[str, ShopTypeMix] = Field(min_length=1)

    @field_validator("categories")
    @classmethod
    def _categories(cls, v):
        if tuple(v) != CATEGORIES:
            raise ValueError(f"categories must be {CATEGORIES}")
        return v


# ---- expansion.yaml ----
class Triangular(_Strict):
    low: float
    mode: float
    high: float

    @model_validator(mode="after")
    def _ordered(self):
        if not self.low <= self.mode <= self.high:
            raise ValueError("need low <= mode <= high")
        return self


class Range(_Strict):
    low: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self):
        if self.low > self.high:
            raise ValueError("need low <= high")
        return self


class ExpansionOption(_Strict):
    uplift: Triangular
    one_time_cost: Range
    monthly_cost: Range


class Expansion(_Header):
    draws: int = Field(ge=100)
    payback_target_months: int = Field(gt=0)
    months_ahead: int = Field(ge=1, le=12)                 # forecast months that form the base band (DEC-88)
    margin_window_days: int = Field(ge=7)                  # own gross margin from this many days of logs
    margin_min_logged_days: int = Field(ge=1)              # fewer logged days: use the assumed margin
    options: dict[str, ExpansionOption] = Field(min_length=1)


# ---- investment_split.yaml ----
class InvestmentSplit(_Header):
    deposit_months_rent: float = Field(ge=0)
    reserve_months_fixed_costs: float = Field(ge=0)
    remainder_split: dict[Literal["stock", "fixtures"], float]

    @field_validator("remainder_split")
    @classmethod
    def _split_sums_to_one(cls, v):
        if set(v) != {"stock", "fixtures"} or any(x < 0 for x in v.values()) or abs(sum(v.values()) - 1) > 1e-6:
            raise ValueError("remainder_split needs stock and fixtures, non-negative, summing to 1.0")
        return v


# ---- forecast_assumptions.yaml ----
class ForecastAssumptions(_Header):
    gross_margin: float = Field(gt=0, lt=1)
    staff_wage_monthly: float = Field(ge=0)
    other_fixed_costs_monthly: float = Field(ge=0)
    payback_steady_from_month: int = Field(ge=1, le=12)
    payback_max_months: int = Field(ge=12, le=120)
    drivers_top: int = Field(ge=1, le=5)
    driver_features: list[Literal["homes", "schools", "transit", "banks_atms", "competitors", "size_sqft",
                                  "city_tier", "monthly_rent", "staff_count"]] = Field(min_length=1)


# ---- pricing.yaml ----
class Pricing(_Header):
    window_days: int = Field(ge=7)
    target_margins: dict[str, float]

    @field_validator("target_margins")
    @classmethod
    def _every_category(cls, v):
        if set(v) != set(CATEGORIES):
            raise ValueError(f"target_margins must list exactly {CATEGORIES}")
        if any(not 0 < x < 1 for x in v.values()):
            raise ValueError("target margins must be between 0 and 1")
        return v


# ---- bundle ----
FILES: dict[str, type[_Header]] = {
    "investment_split.yaml": InvestmentSplit,
    "review_rules.yaml": ReviewRules,
    "alert_rules.yaml": AlertRules,
    "blend.yaml": Blend,
    "stock.yaml": Stock,
    "actions.yaml": Actions,
    "location_weights.yaml": LocationWeights,
    "product_mix.yaml": ProductMix,
    "expansion.yaml": Expansion,
    "osm_tags.yaml": OsmTags,
    "forecast_assumptions.yaml": ForecastAssumptions,
    "pricing.yaml": Pricing,
}


class Rules(_Strict):
    review: ReviewRules
    alerts: AlertRules
    blend: Blend
    stock: Stock
    actions: Actions
    location: LocationWeights
    product_mix: ProductMix
    expansion: Expansion
    investment: InvestmentSplit
    osm: OsmTags
    forecast: ForecastAssumptions
    pricing: Pricing


def load_file(path: Path, model: type[_Header]) -> _Header:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return model.model_validate(data)
    except FileNotFoundError as e:
        raise RuleFileError(f"{path.name}: file missing") from e
    except (yaml.YAMLError, ValidationError) as e:
        raise RuleFileError(f"{path.name}: {e}") from e


def load_rules(rules_dir: Path = RULES_DIR) -> Rules:
    f = {name: load_file(rules_dir / name, model) for name, model in FILES.items()}
    dead_alert, dead_stock = f["alert_rules.yaml"].rules.dead_stock.no_sale_days, f["stock.yaml"].dead_no_sale_days
    if dead_alert != dead_stock:                                   # one definition of dead stock (M-07, M-09)
        raise RuleFileError(f"alert_rules.yaml: dead_stock.no_sale_days ({dead_alert}) differs from stock.yaml "
                            f"dead_no_sale_days ({dead_stock})")
    return Rules(
        review=f["review_rules.yaml"], alerts=f["alert_rules.yaml"], blend=f["blend.yaml"],
        stock=f["stock.yaml"],
        actions=f["actions.yaml"], location=f["location_weights.yaml"],
        product_mix=f["product_mix.yaml"], expansion=f["expansion.yaml"],
        investment=f["investment_split.yaml"], osm=f["osm_tags.yaml"],
        forecast=f["forecast_assumptions.yaml"], pricing=f["pricing.yaml"],
    )


@lru_cache
def get_rules() -> Rules:
    return load_rules()


if __name__ == "__main__":
    r = load_rules()
    for name, model in FILES.items():
        obj = load_file(RULES_DIR / name, model)
        print(f"OK  {name:24s} v{obj.version}  assumption={obj.assumption}")
    print(f"{len(FILES)} rule files valid; {len(r.actions.actions)} actions; "
          f"{len(r.expansion.options)} expansion options")
