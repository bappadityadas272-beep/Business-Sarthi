"""Sensitivity and edge-case check of the set-up forecast (ML2 + plain arithmetic). SYNTHETIC model.

    docker compose run --rm -T -w /repo/backend backend python ../eval/forecast_sensitivity.py
    python ../eval/forecast_sensitivity.py [--models DIR] [--json] [--write]

Needs the trained model (`make train`). Calls the same code as the API: app.ml.forecast.setup_forecast for the
forecast and app.schemas.profile.ShopIn for input validation. Nothing is tuned here.

Base shop: the demo shop DEMO-001 from data/synthetic/config.yaml (hand-set demo values, not market data), with
location source "live" so only the moved input changes. One input moves at a time: monthly rent, size, competitors,
city tier (and homes and staff for context), first across the TRAINING range of the model card (feature_stats),
then outside it, then at and beyond the API limits.

Checks (PASS / FAIL; the script exits 1 if any FAIL):
  order       every month: 0 < P10 <= P50 <= P90, all finite
  monotone    competitors up -> P50 never up; size and homes up -> P50 never down (DEC-34)
  confidence  never "high"; "low" whenever an input is outside the training range; "medium" otherwise
  api         inputs outside the API limits are refused by ShopIn (a clear 422 in the API), not forecast
  break_even  equals (rent + staff x wage + other fixed costs) / margin and rises with rent
  high_rent   at the API maximum rent: no month reaches break-even, every operating profit is negative, no payback
  low_rev     the most adverse in-limit profile still gives finite, ordered numbers; payback_month gives None
              (not a crash, not a fake month) when operating profit never covers the investment
INFO (reported, not judged): the P10-P90 band width as a share of P50 for each scenario.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from pydantic import ValidationError

from app.ml import forecast as fc
from app.ml.train import MODEL_DIR
from app.rules import load_rules
from app.schemas.profile import ShopIn

REPORT = REPO / "docs" / "FORECAST_SENSITIVITY_REPORT.md"
CONFIG = REPO / "data" / "synthetic" / "config.yaml"
BASE_DEMO = "DEMO-001"
SHOP_KEYS = ("size_sqft", "city_tier", "monthly_rent", "staff_count", "budget")
API_LIMITS = {"size_sqft": (30, 5000), "monthly_rent": (0, 1e7), "staff_count": (0, 50), "city_tier": (1, 3)}
MONOTONE_UP, MONOTONE_DOWN = ("size_sqft", "homes"), ("competitors",)
INTEGER = {"homes", "schools", "transit", "banks_atms", "competitors", "staff_count", "city_tier"}


def base_profile() -> tuple[dict, dict, date]:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    demo = next(d for d in cfg["demos"] if d["shop_id"] == BASE_DEMO)
    shop = {k: demo[k] for k in SHOP_KEYS}
    counts = {k: int(demo[k]) for k in fc.COUNT_FEATURES}
    return shop, counts, date.fromisoformat(str(demo["launch_date"]))


def sweep_values(feat: str, stats: dict) -> list[tuple[float, str]]:
    """(value, where) pairs: 7 points across the training range, then outside it, then the API edges."""
    if feat == "city_tier":
        return [(1, "in"), (2, "in"), (3, "in")]
    lo, hi = stats[feat]["min"], stats[feat]["max"]
    vals = [(float(v), "in") for v in np.linspace(lo, hi, 7)]
    vals += [(lo * 0.5, "out"), (hi * 1.5, "out"), (hi * 3, "out")] if lo > 0 else [(hi * 1.5, "out"), (hi * 3, "out")]
    if feat in API_LIMITS:
        vals += [(float(API_LIMITS[feat][0]), "api_min"), (float(API_LIMITS[feat][1]), "api_max")]
    if feat in INTEGER:
        vals = [(float(round(v)), w) for v, w in vals]
    seen, out = set(), []
    for v, w in sorted(vals):
        if v not in seen and v >= 0:
            seen.add(v)
            out.append((v, w))
    return out


def in_training_range(shop: dict, counts: dict, stats: dict) -> list[str]:
    prof = {**shop, **counts}
    return [f for f in fc.RANGE_CHECKED if not stats[f]["min"] <= prof[f] <= stats[f]["max"]]


def run_one(shop, counts, open_date, model, card, rules, source="live") -> dict:
    out = fc.setup_forecast(shop=shop, counts=counts, location_source=source, open_date=open_date, model=model,
                            card=card, assumptions=rules.forecast, split_rule=rules.investment)
    q = np.array([[m["p10"], m["p50"], m["p90"]] for m in out["months"]], dtype=float)
    op = np.array([[m["operating_profit"][p] for p in fc.PATHS] for m in out["months"]], dtype=float)
    return {
        "annual": {p: float(q[:, i].sum()) for i, p in enumerate(fc.PATHS)},
        "month_p50": q[:, 1].tolist(),
        "width_share": float(((q[:, 2] - q[:, 0]) / q[:, 1]).mean()),
        "ordered": bool(np.isfinite(q).all() and (q[:, 0] > 0).all() and (q[:, 0] <= q[:, 1]).all()
                        and (q[:, 1] <= q[:, 2]).all()),
        "confidence": out["confidence"]["level"],
        "confidence_reasons": [r["key"] for r in out["confidence"]["reasons"]],
        "break_even": out["break_even"]["revenue_monthly"],
        "break_even_month": out["break_even"]["first_month_p50_reaches"],
        "fixed_costs": out["fixed_costs_monthly"],
        "op_profit_max": float(op.max()), "op_finite": bool(np.isfinite(op).all()),
        "payback": {k: out["payback"][k] for k in ("fastest_months", "typical_months", "slowest_months")},
        "budget_too_low": out["investment_split"]["budget_too_low"],
    }


def api_check(shop: dict, feat: str, value) -> str | None:
    """None if ShopIn accepts the shop with `feat` = value, else the field that failed."""
    body = {"name": "Sensitivity check", "lat": 26.8, "lon": 80.9, **shop, feat: value}
    try:
        ShopIn.model_validate(body)
        return None
    except ValidationError as e:
        return ",".join(str(err["loc"][0]) for err in e.errors())


def evaluate(model_dir: Path = MODEL_DIR) -> dict:
    st = fc.model_status(model_dir)
    if not st["ok"]:
        raise SystemExit(f"model not ready ({st['reason']}): run `make train` first")
    model, card = fc.load_model(model_dir)
    rules = load_rules()
    stats = card["feature_stats"]
    shop0, counts0, open_date = base_profile()
    base = run_one(shop0, counts0, open_date, model, card, rules)
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    sweeps = {}
    for feat in ("monthly_rent", "size_sqft", "competitors", "city_tier", "homes", "staff_count"):
        rows = []
        for v, where in sweep_values(feat, stats if feat != "city_tier" else {}):
            val = int(v) if feat in INTEGER else float(v)
            shop, counts = dict(shop0), dict(counts0)
            (counts if feat in fc.COUNT_FEATURES else shop)[feat] = val
            refused = api_check(shop, feat, val) if feat in SHOP_KEYS else None
            row = {"value": val, "where": where, "api_refused": refused}
            if refused is None:
                r = run_one(shop, counts, open_date, model, card, rules)
                outside = in_training_range(shop, counts, stats)
                row.update(r, outside_training=outside,
                           p50_change=round(r["annual"]["p50"] / base["annual"]["p50"] - 1, 4))
                check("order", r["ordered"] and r["op_finite"], f"{feat}={val}")
                check("confidence", r["confidence"] != "high" and (r["confidence"] == "low") == bool(outside),
                      f"{feat}={val}: {r['confidence']}, outside={outside}")
                margin, wage = rules.forecast.gross_margin, rules.forecast.staff_wage_monthly
                fixed = shop["monthly_rent"] + shop["staff_count"] * wage + rules.forecast.other_fixed_costs_monthly
                check("break_even", r["break_even"] == round(fixed / margin), f"{feat}={val}: {r['break_even']} vs "
                      f"{round(fixed / margin)}")
            rows.append(row)
        sweeps[feat] = rows
        fc_rows = [r for r in rows if r["api_refused"] is None]
        if feat in MONOTONE_UP + MONOTONE_DOWN:
            sign = 1 if feat in MONOTONE_UP else -1
            m = np.array([r["month_p50"] for r in fc_rows])          # rows sorted by value
            breaks = int(((np.diff(m, axis=0) * sign) < -0.5).sum())  # 0.5 INR: rounding of whole rupees
            check("monotone", breaks == 0, f"{feat}: {breaks} wrong-way steps in {m[1:].size} month checks")
        if feat == "monthly_rent":
            be = [r["break_even"] for r in fc_rows]
            check("break_even", all(b2 >= b1 for b1, b2 in zip(be, be[1:], strict=False)),
                  "break-even never falls as rent rises")

    # inputs the API must refuse
    refuse = [("size_sqft", 10), ("size_sqft", 10000), ("monthly_rent", -1), ("monthly_rent", 2e7),
              ("staff_count", -1), ("staff_count", 60), ("city_tier", 0), ("city_tier", 4), ("budget", 0),
              ("budget", -50000), ("size_sqft", float("nan")), ("monthly_rent", float("inf"))]
    api = []
    for feat, v in refuse:
        got = api_check(shop0, feat, v)
        api.append({"field": feat, "value": str(v), "refused_by": got})
        check("api", got is not None, f"{feat}={v} refused={got}")

    # very high rent at the API maximum
    hr_shop = {**shop0, "monthly_rent": API_LIMITS["monthly_rent"][1]}
    hr = run_one(hr_shop, counts0, open_date, model, card, rules)
    check("high_rent", hr["break_even_month"] is None, f"break-even month {hr['break_even_month']}")
    check("high_rent", hr["op_profit_max"] < 0, f"largest monthly operating profit {hr['op_profit_max']:,.0f}")
    check("high_rent", all(v is None for v in hr["payback"].values()), f"payback {hr['payback']}")
    check("high_rent", hr["confidence"] == "low", f"confidence {hr['confidence']}")

    # very low revenue: the most adverse profile the API accepts, location counts at 0 / high competition
    worst_counts = {"homes": 0, "schools": 0, "transit": 0, "banks_atms": 0,
                    "competitors": int(stats["competitors"]["max"])}
    worst_shop = {**shop0, "size_sqft": float(API_LIMITS["size_sqft"][0]), "city_tier": 3}
    lo = run_one(worst_shop, worst_counts, open_date, model, card, rules)
    check("low_rev", lo["ordered"] and lo["op_finite"], f"annual P50 {lo['annual']['p50']:,.0f}")
    lo_out = in_training_range(worst_shop, worst_counts, stats)
    check("low_rev", (lo["confidence"] == "low") == bool(lo_out), f"confidence {lo['confidence']}, outside={lo_out}")
    if lo["op_profit_max"] < 0:
        check("low_rev", all(v is None for v in lo["payback"].values()), f"payback {lo['payback']}")
    pm = rules.forecast.payback_max_months
    for label, arr, inv in (("all negative", np.full(12, -1000.0), 100000.0), ("all zero", np.zeros(12), 1.0),
                            ("tiny positive", np.full(12, 1.0), 1e6)):
        got = fc.payback_month(arr, inv, rules.forecast.payback_steady_from_month, pm)
        expect = None if label != "tiny positive" or math.ceil(inv / 1.0) > pm else math.ceil(inv)
        check("low_rev", got == expect, f"payback_month({label}, investment {inv:,.0f}) = {got}, expected {expect}")

    mock = run_one(shop0, counts0, open_date, model, card, rules, source="mock")
    check("confidence", mock["confidence"] == "low", f"mock location source -> {mock['confidence']}")
    widths = sorted({round(r["width_share"], 4) for rows in sweeps.values() for r in rows if "width_share" in r})
    return {"is_synthetic": True, "model_version": card.get("version"), "base_shop": BASE_DEMO,
            "base": {k: base[k] for k in ("annual", "confidence", "break_even", "payback", "width_share")},
            "training_range": {k: stats[k] for k in fc.RANGE_CHECKED},
            "sweeps": sweeps, "api_refusals": api, "high_rent": hr, "low_revenue": lo,
            "band_width_share_values": widths, "checks": checks,
            "failed": [c for c in checks if not c["ok"]]}


def _fmt(v) -> str:
    return "none" if v is None else f"{v}"


def render(r: dict) -> str:
    fails = r["failed"]
    by: dict[str, list[bool]] = {}
    for c in r["checks"]:
        by.setdefault(c["check"], []).append(c["ok"])
    lines = [
        "# FORECAST_SENSITIVITY_REPORT: set-up forecast sensitivity and edge cases", "",
        "> Generated by `eval/forecast_sensitivity.py --write`. Do not edit by hand.",
        "> **Model trained on SYNTHETIC data (`is_synthetic: true`).** This checks behaviour, not accuracy.", "",
        f"Model `{r['model_version']}`, base shop {r['base_shop']} (hand-set demo values). Base annual P50 "
        f"INR {r['base']['annual']['p50']:,.0f}, confidence {r['base']['confidence']}.", "",
        "## Checks", "", "| Check | Passed | Failed |", "|---|---|---|",
        *[f"| {k} | {sum(v)} | {len(v) - sum(v)} |" for k, v in by.items()], "",
    ]
    if fails:
        lines += ["### Failed checks", "", *[f"- {c['check']}: {c['detail']}" for c in fails], ""]
    for feat, rows in r["sweeps"].items():
        lines += [f"## {feat}", "", "| Value | Where | API | Annual P10 | Annual P50 | Annual P90 | P50 vs base | "
                  "Band / P50 | Confidence | Break-even / month | Month P50 reaches it | Payback fast / typical / slow |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for x in rows:
            if x["api_refused"]:
                lines.append(f"| {x['value']} | {x['where']} | refused ({x['api_refused']}) | | | | | | | | | |")
                continue
            a, p = x["annual"], x["payback"]
            lines.append(f"| {x['value']} | {x['where']} | ok | {a['p10']:,.0f} | {a['p50']:,.0f} | {a['p90']:,.0f} | "
                         f"{x['p50_change']:+.1%} | {x['width_share']:.0%} | {x['confidence']} | {x['break_even']:,} | "
                         f"{_fmt(x['break_even_month'])} | {_fmt(p['fastest_months'])} / {_fmt(p['typical_months'])} / "
                         f"{_fmt(p['slowest_months'])} |")
        lines.append("")
    lines += ["## Inputs the API refuses", "", "| Field | Value | Refused by |", "|---|---|---|",
              *[f"| {a['field']} | {a['value']} | {a['refused_by'] or '**ACCEPTED**'} |" for a in r["api_refusals"]], "",
              "## Band width (INFO)", "",
              f"Distinct mean (P90 - P10) / P50 values over all scenarios: {r['band_width_share_values']}. The band is "
              "P50 times fixed ratios per month (DEC-35), so its relative width does not grow for unusual inputs; only "
              "the confidence flag signals them.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", type=Path, default=MODEL_DIR)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help=f"write {REPORT.relative_to(REPO)}")
    a = ap.parse_args(argv)
    r = evaluate(a.models)
    text = render(r)
    print(json.dumps(r, indent=2, default=str) if a.json else text)
    if a.write:
        REPORT.write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"\nwrote {REPORT}")
    sys.exit(1 if r["failed"] else 0)


if __name__ == "__main__":
    main()
