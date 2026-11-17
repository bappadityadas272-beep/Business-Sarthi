"""Set-up forecast (M-05, ML_PLAN section 4): ML2 P10/P50/P90 for 12 months plus plain-arithmetic outputs.

Everything here is code, not the LLM (AGENTS rule 2). Revenue comes from the ML2 model (trained on SYNTHETIC
shops); margin, wage and the payback extension are labelled assumptions from data/rules/forecast_assumptions.yaml.
"""
import hashlib
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import REPO_ROOT
from app.ml.features import FEATURES, HORIZON, month_rows
from app.ml.train import MODEL_DIR, MODEL_FILE, MODEL_VERSION, active_band, load, predict_quantiles
from app.rules import ForecastAssumptions, InvestmentSplit

PATHS = ("p10", "p50", "p90")
COUNT_FEATURES = ("homes", "schools", "transit", "banks_atms", "competitors")
RANGE_CHECKED = ("size_sqft", "monthly_rent", "staff_count", *COUNT_FEATURES)
DRIVER_LABELS = {
    "homes": "Homes within 500 m", "schools": "Schools within 500 m", "transit": "Bus stops, stations and markets within 500 m",
    "banks_atms": "Banks and ATMs within 500 m", "competitors": "Similar shops within 500 m",
    "size_sqft": "Shop size (sq ft)", "city_tier": "City tier",
}
NOTICE = "Estimate from a prototype model trained on synthetic data. A range, not a promise."


class ModelNotReady(RuntimeError):
    pass


@lru_cache(maxsize=4)
def load_model(model_dir: Path = MODEL_DIR):
    try:
        return load(model_dir)
    except OSError as e:
        raise ModelNotReady("ML2 model files not found; run `make train`") from e


def load_card(model_dir: Path = MODEL_DIR) -> dict:
    return json.loads((model_dir / "model_card.json").read_text(encoding="utf-8"))


SYNTH_CONFIG = REPO_ROOT / "data" / "synthetic" / "config.yaml"


def model_status(model_dir: Path = MODEL_DIR, config_path: Path = SYNTH_CONFIG) -> dict:
    """Is the ML2 model usable? `ok` False with a `reason` when files are missing, the card is from another model
    version, the model file does not match the hash in its card, or the SYNTHETIC config changed since training
    (stale: run `make train`). Not cached: the files are small (the model is about 130 KB), a check takes ms."""
    d, cfg = Path(model_dir), Path(config_path)
    out = {"ok": False, "reason": None, "version": None, "is_synthetic": True, "fix": "make train"}
    try:
        card = json.loads((d / "model_card.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {**out, "reason": "model_files_missing"}
    out.update(version=card.get("version"), is_synthetic=bool(card.get("is_synthetic", True)))
    f = d / MODEL_FILE
    if not f.exists():
        return {**out, "reason": "model_files_missing"}
    if card.get("version") != MODEL_VERSION:
        return {**out, "reason": "model_version_mismatch"}
    if hashlib.sha256(f.read_bytes()).hexdigest() != card.get("files_sha256", {}).get(MODEL_FILE):
        return {**out, "reason": "model_file_changed"}
    if cfg.exists() and hashlib.sha256(cfg.read_bytes()).hexdigest() != card.get("data", {}).get("config_sha256"):
        return {**out, "reason": "model_stale_config_changed"}
    return {**out, "ok": True, "fix": None}


def next_month_start(today: date) -> date:
    return date(today.year + (today.month == 12), today.month % 12 + 1, 1)


def resolve_open_date(requested: date | None, launch_date: date | None, today: date) -> tuple[date, str]:
    """Opening date and where it came from (DEC-51)."""
    if requested:
        return requested, "request"
    if launch_date:
        return launch_date, "shop"
    return next_month_start(today), "assumed_next_month"


def predict_months(model, card: dict, profile: dict, open_date: date) -> tuple[pd.DataFrame, np.ndarray]:
    """Feature rows for months 1..12 and the (12, 3) array of P10, P50, P90."""
    X = month_rows(pd.DataFrame([{**profile, "launch_date": open_date.isoformat()}]), HORIZON)
    return X, predict_quantiles(model, active_band(card), X)


def payback_month(op_profit: np.ndarray, investment: float, steady_from: int, max_months: int) -> int | None:
    """First month in which cumulative operating profit covers the investment, or None within `max_months`.
    Months after the forecast horizon earn the mean operating profit of months steady_from..12 (assumption)."""
    steady = float(np.mean(op_profit[steady_from - 1:]))
    cum = 0.0
    for m in range(1, max_months + 1):
        cum += float(op_profit[m - 1]) if m <= len(op_profit) else steady
        if cum >= investment:
            return m
    return None


def investment_split(budget: float, rent: float, fixed_costs: float, rule: InvestmentSplit) -> dict:
    deposit = rule.deposit_months_rent * rent
    reserve = rule.reserve_months_fixed_costs * fixed_costs
    left = budget - deposit - reserve
    out = {"budget": round(budget), "deposit": round(deposit), "cash_reserve": round(reserve),
           "budget_too_low": left < 0, "shortfall": round(max(-left, 0)), "stock": None, "fixtures": None,
           "is_assumption": True}
    if left >= 0:
        stock = round(left * rule.remainder_split["stock"])
        out["stock"], out["fixtures"] = stock, round(left) - stock
    return out


def top_drivers(model, X: pd.DataFrame, profile: dict, allowed: list[str], top: int) -> list[dict]:
    """LightGBM feature contributions, averaged over the 12 months, for the allowed inputs only (DEC-52).
    A contribution is measured against the average prediction over the training shops."""
    contrib = np.asarray(model.predict(X[FEATURES], pred_contrib=True))[:, :-1].mean(axis=0)
    by_feature = dict(zip(FEATURES, contrib, strict=True))
    ranked = sorted(allowed, key=lambda f: -abs(by_feature[f]))
    out = []
    for f in ranked[:top]:
        effect = float(by_feature[f])
        if abs(effect) < 1:                     # no measurable effect: not a driver
            continue
        direction = "up" if effect > 0 else "down"
        value = profile[f]
        value = int(value) if float(value).is_integer() else round(float(value), 1)
        verb = "raises" if effect > 0 else "lowers"
        out.append({
            "feature": f, "value": value, "direction": direction, "message_key": f"driver.{f}.{direction}",
            "effect_inr_per_month": int(round(effect, -2)),
            "text": f"{DRIVER_LABELS[f]}: {value}. This {verb} the estimate compared with a typical shop in our data.",
        })
    return out


def confidence(location_source: str, profile: dict, feature_stats: dict | None) -> dict:
    """`medium` at best: the model has only seen synthetic shops (DEC-50). `low` when the location counts are not
    measured OSM data or an input lies outside the range of the training shops."""
    reasons = [{"key": "confidence.synthetic_training", "params": {}}]
    low = False
    if location_source in ("mock", "fallback_assumed"):
        low = True
        reasons.append({"key": f"confidence.location_{location_source}", "params": {}})
    outside = [f for f in RANGE_CHECKED
               if feature_stats and not feature_stats[f]["min"] <= profile[f] <= feature_stats[f]["max"]]
    if outside:
        low = True
        reasons.append({"key": "confidence.outside_training_range", "params": {"features": outside}})
    return {"level": "low" if low else "medium", "reasons": reasons}


def setup_forecast(*, shop: dict, counts: dict[str, int], location_source: str, open_date: date, model, card: dict,
                   assumptions: ForecastAssumptions, split_rule: InvestmentSplit) -> dict:
    """`shop` needs size_sqft, city_tier, monthly_rent, staff_count and budget."""
    profile = {"size_sqft": float(shop["size_sqft"]), "city_tier": int(shop["city_tier"]),
               "monthly_rent": float(shop["monthly_rent"]), "staff_count": int(shop["staff_count"]),
               **{f: int(counts[f]) for f in COUNT_FEATURES}}
    X, q = predict_months(model, card, profile, open_date)
    margin = assumptions.gross_margin
    fixed = profile["monthly_rent"] + profile["staff_count"] * assumptions.staff_wage_monthly \
        + assumptions.other_fixed_costs_monthly
    gross, op = q * margin, q * margin - fixed
    starts = [(pd.Timestamp(open_date) + pd.DateOffset(months=k)).date() for k in range(HORIZON + 1)]

    def trio(row) -> dict:
        return {p: round(float(v)) for p, v in zip(PATHS, row, strict=True)}

    months = [{"k": k + 1, "start": starts[k], "end": starts[k + 1] - pd.Timedelta(days=1).to_pytimedelta(),
               **trio(q[k]), "gross_profit": trio(gross[k]), "operating_profit": trio(op[k])} for k in range(HORIZON)]
    break_even = fixed / margin
    reached = next((m["k"] for m in months if m["p50"] >= break_even), None)
    budget = float(shop["budget"])
    pay = {p: payback_month(op[:, i], budget, assumptions.payback_steady_from_month, assumptions.payback_max_months)
           for i, p in enumerate(PATHS)}
    return {
        "kind": "setup", "is_estimate": True, "trained_on_synthetic": bool(card.get("is_synthetic", True)),
        "notice": NOTICE, "model_version": card.get("version"),
        "open_date": open_date,
        "months": months,
        "assumptions": {"gross_margin": margin, "staff_wage_monthly": assumptions.staff_wage_monthly,
                        "other_fixed_costs_monthly": assumptions.other_fixed_costs_monthly, "is_assumption": True,
                        "source": assumptions.source},
        "fixed_costs_monthly": round(fixed),
        "break_even": {"revenue_monthly": round(break_even), "first_month_p50_reaches": reached},
        # fastest = every month at P90, slowest = every month at P10; None = not within max_months
        "payback": {"fastest_months": pay["p90"], "typical_months": pay["p50"], "slowest_months": pay["p10"],
                    "investment": round(budget), "max_months": assumptions.payback_max_months,
                    "extended_beyond_forecast": any(v is None or v > HORIZON for v in pay.values()),
                    "is_assumption": True},
        "investment_split": investment_split(budget, profile["monthly_rent"], fixed, split_rule),
        "drivers": top_drivers(model, X, profile, list(assumptions.driver_features), assumptions.drivers_top),
        "confidence": confidence(location_source, profile, card.get("feature_stats")),
    }
