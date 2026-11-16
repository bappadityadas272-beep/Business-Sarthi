"""Re-forecast (M-06, ML_PLAN section 5): shrinkage blend of the set-up forecast and the shop's own sales.

    prior      = the set-up forecast (ML2) for the same months
    own model  = ETS on DAILY total sales (damped additive trend + weekly seasonality; level only below
                 `level_only_below_days` observed days), summed to months
    blend      = w x own + (1 - w) x prior,  w = n_days / (n_days + k),  n_days = days actually logged
    band       = root-sum-of-squares of the two spreads (weighted w and 1 - w), rescaled by the shop's observed
                 error against its set-up forecast, times `interval_scale` (DEC-55, DEC-56)

Missing days stay missing: the state-space ETS skips them (they are never treated as zero sales).
Nothing after the forecast origin is read (`reforecast` cuts the series first).
"""
from __future__ import annotations

import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.exponential_smoothing import ExponentialSmoothing

from app.rules import Blend

Z10 = 1.2816                 # standard normal quantile for P10 / P90
MAX_DOWN = 0.95              # P10 is never below 5% of the not-yet-observed part of P50


class NotEnoughData(ValueError):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def month_windows(open_date: date, horizon: int = 12) -> list[tuple[date, date]]:
    """(start, end) of months 1..horizon counted from the opening day (same rule as the set-up forecast)."""
    starts = [(pd.Timestamp(open_date) + pd.DateOffset(months=k)).date() for k in range(horizon + 1)]
    return [(starts[k], starts[k + 1] - timedelta(days=1)) for k in range(horizon)]


def _fit(y: pd.Series, *, trend: bool, damped: bool, seasonal: bool):
    model = ExponentialSmoothing(y, trend=trend, damped_trend=trend and damped, seasonal=7 if seasonal else None,
                                 initialization_method="concentrated")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return model.fit(disp=False, maxiter=200)


def ets_daily(y: pd.Series, steps: int, *, level_only: bool, damped: bool = True) -> dict:
    """Forecast `steps` days after the end of `y` (daily index, NaN = missing day).
    Returns the daily forecast (never negative), the level smoothing weight, the one-step residual spread and the
    model used. Falls back to the level-only model if the full model cannot be fitted."""
    y = y.astype(float)
    res, name = None, "level_only"
    if not level_only:
        try:
            res = _fit(y, trend=True, damped=damped, seasonal=True)
            f = np.asarray(res.forecast(steps), dtype=float)
            if not np.isfinite(f).all():
                raise ValueError("non-finite forecast")
            name = "ets_damped_trend_weekly" if damped else "ets_trend_weekly"
        except Exception:                                    # noqa: BLE001  (any fit failure -> simpler model)
            res = None
    if res is None:
        res = _fit(y, trend=False, damped=False, seasonal=False)
        f = np.asarray(res.forecast(steps), dtype=float)
    resid = np.asarray(res.resid, dtype=float)
    resid = resid[np.isfinite(resid)][1:]                    # the first residual belongs to the initial state
    sigma = float(resid.std(ddof=1)) if resid.size > 2 else float(np.nanstd(y.to_numpy()))
    alpha = float(np.clip(dict(zip(res.param_names, res.params, strict=True)).get("smoothing_level", 0.5), 0.0, 1.0))
    return {"forecast": np.clip(f, 0.0, None), "alpha": alpha, "sigma": sigma, "model": name}


def sum_sd(alpha: float, sigma: float, a: int, b: int) -> float:
    """Spread of the SUM of the forecasts for steps a..b (1-based, inclusive) under simple exponential smoothing:
    the error at step h is e_h + alpha x (e_1 + ... + e_(h-1)), so the sum is a weighted sum of independent errors."""
    j = np.arange(1, b + 1)
    own = ((j >= a) & (j <= b)).astype(float)                # e_j counted once for its own day
    later = np.clip(b - np.maximum(j, a - 1), 0, None)       # days in a..b that come after day j
    return float(sigma * np.sqrt(((own + alpha * later) ** 2).sum()))


def prepare(daily: pd.Series, origin: date, prior_months: list[dict], rule: Blend, *, start: date | None = None) -> dict:
    """The expensive part (one ETS fit). `daily`: sales total per logged day (index = dates; a day that is absent
    or NaN is MISSING). `origin`: last day whose data may be used. `prior_months`: the set-up forecast months with
    k, start, end, p10, p50, p90. `start`: first day the shop was open (default: first logged day)."""
    s = pd.Series(daily, dtype=float).dropna()
    s.index = pd.to_datetime(s.index)
    s = s[s.index <= pd.Timestamp(origin)].sort_index()      # leakage guard: nothing after the origin
    if start is not None:
        s = s[s.index >= pd.Timestamp(start)]
    n_days = len(s)
    if n_days < rule.min_days:
        raise NotEnoughData("not_enough_days_logged", days_logged=n_days, needed=rule.min_days)
    first = pd.Timestamp(start) if start is not None else s.index[0]
    idx = pd.date_range(first, pd.Timestamp(origin), freq="D")
    y = s.reindex(idx)
    months = [m for m in prior_months if pd.Timestamp(m["end"]) > pd.Timestamp(origin)]
    if not months:
        raise NotEnoughData("forecast_horizon_over")
    steps = (pd.Timestamp(months[-1]["end"]) - pd.Timestamp(origin)).days
    ets = ets_daily(y, steps, level_only=n_days < rule.level_only_below_days, damped=rule.damped_trend)
    f = ets["forecast"]

    # the observed error of the shop against its original forecast, on the days it logged
    actual = prior_same = half = 0.0
    for m in prior_months:
        ms, me = pd.Timestamp(m["start"]), pd.Timestamp(m["end"])
        seen = s[(s.index >= ms) & (s.index <= me)]
        if len(seen) and m["p50"] > 0:
            share = len(seen) / ((me - ms).days + 1)
            actual += float(seen.sum())
            prior_same += m["p50"] * share
            half += (m["p90"] - m["p10"]) / 2 * share
    if prior_same > 0 and half > 0:
        observed_error = abs(actual / prior_same - 1.0)
        rescale = float(np.clip(observed_error / (half / prior_same), rule.error_rescale_min, rule.error_rescale_max))
    else:
        observed_error, rescale = None, 1.0

    weekly_rate = float(f[:7].mean())                         # ETS daily rate, used for missing days already past
    parts = []
    for m in months:
        ms, me = pd.Timestamp(m["start"]), pd.Timestamp(m["end"])
        past = y[(y.index >= ms) & (y.index <= me)]
        n_gap = int(past.isna().sum())
        a = max((ms - pd.Timestamp(origin)).days, 1)          # forecast steps that fall in this month
        b = (me - pd.Timestamp(origin)).days
        n_open = (b - a + 1) + n_gap                          # days of the month with no data yet
        ok = m["p50"] > 0
        parts.append({"k": m["k"], "start": m["start"], "end": m["end"], "prior_p50": float(m["p50"]),
                      "seen_sum": float(past.sum(skipna=True)), "days_logged": int(past.notna().sum()), "days_open": n_open,
                      "own_open": float(f[a - 1:b].sum()) + n_gap * weekly_rate,
                      "prior_open": m["p50"] / ((me - ms).days + 1) * n_open,
                      "ets_sd": sum_sd(ets["alpha"], ets["sigma"], a, b),
                      "down_p": 1 - m["p10"] / m["p50"] if ok else 0.0, "up_p": m["p90"] / m["p50"] - 1 if ok else 0.0})
    return {"origin": origin, "n_days": n_days, "span_days": len(idx), "missing_share": (len(idx) - n_days) / len(idx),
            "own_model": ets["model"], "observed_error": observed_error, "rescale": rescale, "parts": parts}


def combine(ctx: dict, rule: Blend, *, k: float | None = None, interval_scale: float | None = None) -> dict:
    """The cheap part: blend the prepared pieces with weight w = n_days / (n_days + k) and build the band."""
    kk = rule.k if k is None else k
    scale = rule.interval_scale if interval_scale is None else interval_scale
    n_days, missing_share = ctx["n_days"], ctx["missing_share"]
    w = n_days / (n_days + kk)
    out = []
    for p in ctx["parts"]:
        open_p50 = w * p["own_open"] + (1 - w) * p["prior_open"]
        ets_rel = Z10 * p["ets_sd"] / p["own_open"] if p["own_open"] > 0 else 0.0
        down = min(float(np.hypot(w * ets_rel, (1 - w) * p["down_p"])) * ctx["rescale"] * scale, MAX_DOWN)
        up = float(np.hypot(w * ets_rel, (1 - w) * p["up_p"])) * ctx["rescale"] * scale
        seen = p["seen_sum"]
        out.append({"k": p["k"], "start": p["start"], "end": p["end"],
                    "p10": round(seen + open_p50 * (1 - down)), "p50": round(seen + open_p50),
                    "p90": round(seen + open_p50 * (1 + up)),
                    "prior_p50": round(p["prior_p50"]), "own_p50": round(seen + p["own_open"]),
                    "actual_so_far": round(seen), "days_logged": p["days_logged"], "days_open": p["days_open"]})
    reasons = []
    if missing_share > rule.low_confidence_missing_share:
        reasons.append({"key": "confidence.many_days_missing",
                        "params": {"missing_percent": round(missing_share * 100),
                                   "limit_percent": round(rule.low_confidence_missing_share * 100)}})
    if n_days < rule.low_confidence_below_days:
        reasons.append({"key": "confidence.few_days_logged",
                        "params": {"days_logged": n_days, "needed": rule.low_confidence_below_days}})
    level = "low" if reasons else "medium"                    # never "high": the prior was trained on synthetic shops
    err = ctx["observed_error"]
    return {"kind": "reforecast", "is_estimate": True, "origin": ctx["origin"], "months": out,
            "n_days": n_days, "span_days": ctx["span_days"], "missing_share": round(missing_share, 4),
            "weight_own": round(w, 4), "k": kk, "own_model": ctx["own_model"],
            "observed_error": None if err is None else round(err, 4), "interval_rescale": round(ctx["rescale"], 4),
            "confidence": {"level": level, "reasons": [{"key": "confidence.synthetic_training", "params": {}}, *reasons]}}


def reforecast(daily: pd.Series, origin: date, prior_months: list[dict], rule: Blend, *, start: date | None = None,
               k: float | None = None, interval_scale: float | None = None) -> dict:
    return combine(prepare(daily, origin, prior_months, rule, start=start), rule, k=k, interval_scale=interval_scale)
