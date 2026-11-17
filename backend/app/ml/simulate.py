"""ML9 expansion simulator (M-10, DEC-88). Pure functions: no HTTP, no database.

For each option in data/rules/expansion.yaml (every range there is an ASSUMPTION, DEC-21) and each of `draws` draws:
- base monthly revenue: one draw from the shop's latest forecast band. The band is the mean P10/P50/P90 of the next
  forecast months (per 30 days); the draw is a split normal through it (P50 the median, P10 and P90 the 10th and 90th
  percentiles), clipped at zero.
- uplift ~ triangular(low, mode, high) as a share of base revenue; one-time cost and monthly cost ~ uniform(low, high).
- extra profit per month = base x uplift x gross margin - monthly cost.
- payback months = one-time cost / extra profit; no payback when extra profit <= 0.
Reported: P10/P50/P90 of payback months (None = beyond the horizon or never), P(payback < target), extra revenue and
extra profit bands. These are estimates on assumed ranges, not a promise.
"""
from datetime import date

import numpy as np

from app.rules import Expansion

Z90 = 1.2815515655446004            # standard normal 90th percentile
DAYS_PER_MONTH = 30


def monthly_band(months: list[dict], today: date, n: int = 3) -> tuple[dict, list[dict]]:
    """Mean P10/P50/P90 per 30 days over the next `n` forecast months that have not ended. Raises ValueError if none."""
    ahead = [m for m in months if m["end"] >= today][:n]
    if not ahead:
        raise ValueError("no forecast month ahead")
    per = []
    for m in ahead:
        days = (m["end"] - m["start"]).days + 1
        per.append({q: m[q] * DAYS_PER_MONTH / days for q in ("p10", "p50", "p90")})
    band = {q: float(np.mean([p[q] for p in per])) for q in ("p10", "p50", "p90")}
    return band, ahead


def draw_revenue(band: dict, rng: np.random.Generator, n: int) -> np.ndarray:
    z = rng.standard_normal(n)
    down = (band["p50"] - band["p10"]) / Z90
    up = (band["p90"] - band["p50"]) / Z90
    return np.clip(band["p50"] + np.where(z < 0, z * down, z * up), 0.0, None)


def _q(a: np.ndarray, horizon: int) -> dict:
    """P10/P50/P90 of payback months; a quantile above the horizon (or no payback) is None."""
    out = {}
    for name, p in (("p10", 10), ("p50", 50), ("p90", 90)):
        v = float(np.percentile(a, p, method="inverted_cdf"))      # no interpolation between "no payback" draws
        out[name] = None if not np.isfinite(v) or v > horizon else round(v, 1)
    return out


def _band(a: np.ndarray) -> dict:
    return {name: round(float(np.percentile(a, p))) for name, p in (("p10", 10), ("p50", 50), ("p90", 90))}


def simulate(band: dict, margin: float, rule: Expansion, *, seed: int, horizon_months: int,
             options: list[str] | None = None) -> list[dict]:
    names = options or list(rule.options)
    unknown = [o for o in names if o not in rule.options]
    if unknown:
        raise KeyError(unknown)
    rng = np.random.default_rng(seed)
    n, target = rule.draws, rule.payback_target_months
    out = []
    for name in names:
        o = rule.options[name]
        base = draw_revenue(band, rng, n)
        uplift = rng.triangular(o.uplift.low, o.uplift.mode, o.uplift.high, n) if o.uplift.high > o.uplift.low \
            else np.full(n, o.uplift.mode)
        one_time = rng.uniform(o.one_time_cost.low, o.one_time_cost.high, n)
        monthly = rng.uniform(o.monthly_cost.low, o.monthly_cost.high, n)
        extra_rev = base * uplift
        extra_profit = extra_rev * margin - monthly
        with np.errstate(divide="ignore", invalid="ignore"):
            payback = np.where(extra_profit > 0, one_time / np.where(extra_profit > 0, extra_profit, 1.0), np.inf)
        out.append({
            "option": name,
            "payback_months": _q(payback, horizon_months),
            "p_payback_under_target": round(float(np.mean(payback < target)), 3),
            "payback_target_months": target,
            "share_no_payback": round(float(np.mean(~np.isfinite(payback))), 3),
            "extra_revenue_month": _band(extra_rev),
            "extra_profit_month": _band(extra_profit),
            "no_upfront_cost": o.one_time_cost.high == 0,
            "assumptions": {"assumption": True, "uplift": o.uplift.model_dump(),
                            "one_time_cost": o.one_time_cost.model_dump(), "monthly_cost": o.monthly_cost.model_dump()},
        })
    return out
