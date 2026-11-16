#!/usr/bin/env python3
"""Synthetic kirana shop data generator (checkpoint D-01, ML_PLAN section 2).

ALL OUTPUT IS SYNTHETIC. Every CSV has an `is_synthetic` column set to true, and `metadata.json` says so.

    python data/synthetic/generate.py                # 1,000 shops x 24 months -> data/synthetic/out/
    python data/synthetic/generate.py --seed 7 --out /tmp/x
    python data/synthetic/generate.py --demo         # also writes the 2 demo shops to out/demo/

Outputs:
    shops.csv   static features per shop (columns prefixed `latent_` are generator internals:
                never use them as model features)
    daily.csv   shop_id, day, category, sales, purchases
    labels.csv  revenue in months 1-3 and months 1-12 (supervised targets for ML2)
    metadata.json
Same seed + same config => byte-identical files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
GENERATOR_VERSION = "1.1.0"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAYS_PER_MONTH = 30.4375


def load_config(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


# ---------- multipliers (all vectorised over a DatetimeIndex) ----------
def festival_uplift(days: pd.DatetimeIndex, cfg: dict) -> dict[str, np.ndarray]:
    """Per-category festival uplift (0 = none). Linear ramp over `days` days up to `peak` on the festival
    date, times the festival's category profile (DEC-29). Overlapping festivals take the max."""
    base, profiles = cfg["category_mix"]["base"], cfg["festival_category"]
    uplift = {c: np.zeros(len(days)) for c in cfg["categories"]}
    day_ns = days.values.astype("datetime64[D]")
    for name, f in cfg["festivals"].items():
        if name == "verified":
            continue
        prof = profiles.get(name, profiles["default"])
        norm = sum(base[c] * prof[c] for c in cfg["categories"])   # keeps the average-shop uplift = peak
        n = int(f["days"])
        for d in f["dates"]:
            lag = (np.datetime64(d, "D") - day_ns).astype(int)     # days until the festival (0 = festival day)
            ramp = np.where((lag >= 0) & (lag < n), f["peak"] * (n - lag) / n, 0.0)
            for c in cfg["categories"]:
                uplift[c] = np.maximum(uplift[c], ramp * prof[c] / norm)
    return uplift


def calendar_mult(days: pd.DatetimeIndex, cfg: dict, weekday_scale: float = 1.0) -> np.ndarray:
    """Weekday x payday multiplier. `weekday_scale` stretches each weekday's distance from 1 (DEC-28)."""
    wd = np.array([cfg["weekday_mult"][WEEKDAYS[i]] for i in range(7)])[days.day_of_week]
    wd = 1.0 + (wd - 1.0) * weekday_scale
    p = cfg["payday"]
    dom, dim = days.day.values, days.days_in_month.values
    pay = np.where(dom <= p["first_days"], p["first_mult"],
                   np.where(dom > dim - p["last_days"], p["last_mult"], 1.0))
    return wd * pay


def ramp_mult(days: pd.DatetimeIndex, launch: pd.Timestamp, r0: float, tau: float) -> np.ndarray:
    m = (days - launch).days.values / DAYS_PER_MONTH
    return 1.0 - (1.0 - r0) * np.exp(-m / tau)


def trend_mult(days: pd.DatetimeIndex, launch: pd.Timestamp, g: float) -> np.ndarray:
    return (1.0 + g) ** ((days - launch).days.values / 365.25)


# ---------- shop sampling ----------
def sample_catchment(rng: np.random.Generator, cfg: dict) -> dict:
    out = {}
    for k, spec in cfg["catchment"].items():
        if spec["dist"] == "poisson":
            out[k] = int(rng.poisson(spec["lam"]))
        elif spec["dist"] == "loguniform":
            out[k] = int(round(np.exp(rng.uniform(np.log(spec["low"]), np.log(spec["high"])))))  # noqa: RUF046
        else:
            raise ValueError(f"unknown dist {spec['dist']}")
    return out


def steady_revenue(feat: dict, size: float, tier: int, cfg: dict, noise: float) -> float:
    s = cfg["steady_revenue"]
    base = s["intercept"] + sum(c * feat[k] for k, c in s["coef"].items())
    v = (base * np.sqrt(size / s["size_ref"]) * cfg["city_tiers"]["demand_mult"][tier]
         * np.exp(s["competitor_decay"] * feat["competitors"]) * noise)
    return float(np.clip(v, *s["clip"]))


def sample_shop(rng: np.random.Generator, cfg: dict, i: int) -> dict:
    tiers = cfg["city_tiers"]
    tier = int(rng.choice(list(tiers["probs"]), p=list(tiers["probs"].values())))
    feat = sample_catchment(rng, cfg)
    size = float(round(rng.uniform(cfg["size_sqft"]["low"], cfg["size_sqft"]["high"])))
    start, end = (pd.Timestamp(cfg["launch_window"][k]) for k in ("start", "end"))
    launch = start + pd.Timedelta(days=int(rng.integers(0, (end - start).days + 1)))
    rent = float(np.clip(round(size * rng.uniform(*tiers["rent_per_sqft"][tier]), -2), *cfg["rent_clip"]))
    st = cfg["staff"]
    staff = int(rng.choice(list(st["probs"]), p=list(st["probs"].values())))
    wage = float(round(rng.uniform(*st["monthly_wage"]), -2))
    noise = float(np.exp(rng.normal(0, cfg["steady_revenue"]["shop_noise_sigma"])))
    mix_cfg = cfg["category_mix"]
    alpha = np.array([mix_cfg["base"][c] for c in cfg["categories"]]) * mix_cfg["dirichlet_concentration"]
    mix = rng.dirichlet(alpha)
    margins = {c: float(rng.uniform(*cfg["margins"][c])) for c in cfg["categories"]}
    sh = cfg["shock"]
    has_shock = bool(rng.random() < sh["prob"])
    shock_start = launch + pd.Timedelta(days=int(rng.uniform(*sh["start_month"]) * DAYS_PER_MONTH))
    shock_mult = float(rng.uniform(*sh["mult"]))
    r0, tau = float(rng.uniform(*cfg["ramp_up"]["r0"])), float(rng.uniform(*cfg["ramp_up"]["tau_months"]))
    trend = float(rng.uniform(*cfg["trend_annual"]))
    var = {k: float(rng.uniform(*cfg["shop_variation"][k])) for k in ("weekday", "ramp_up", "festival")}
    return {
        "shop_id": f"S{i:04d}", "shop_type": "kirana", "city_tier": tier, **feat, "size_sqft": size,
        "monthly_rent": rent, "staff_count": staff, "staff_wage": wage,
        "launch_date": launch.date().isoformat(),
        **{f"margin_{c}": round(m, 4) for c, m in margins.items()},
        "latent_steady_daily": round(steady_revenue(feat, size, tier, cfg, noise), 2),
        # effective ramp after per-shop variation: depth (1 - r0) and tau both scaled (DEC-28)
        "latent_ramp_r0": round(1.0 - (1.0 - r0) * var["ramp_up"], 4),
        "latent_ramp_tau": round(tau * var["ramp_up"], 4),
        "latent_trend": round(trend, 4),
        **{f"latent_var_{k}": round(v, 4) for k, v in var.items()},
        "latent_shock": has_shock,
        "latent_shock_start": shock_start.date().isoformat() if has_shock else "",
        "latent_shock_mult": round(shock_mult, 4) if has_shock else 1.0,
        **{f"latent_mix_{c}": round(float(m), 4) for c, m in zip(cfg["categories"], mix, strict=True)},
    }


# ---------- daily series ----------
def simulate_daily(rng: np.random.Generator, shop: dict, cfg: dict, end: pd.Timestamp | None = None,
                   dip: dict | None = None) -> pd.DataFrame:
    launch = pd.Timestamp(shop["launch_date"])
    last = end if end is not None else launch + pd.DateOffset(months=cfg["months"]) - pd.Timedelta(days=1)
    days = pd.date_range(launch, last, freq="D")
    total = (shop["latent_steady_daily"] * calendar_mult(days, cfg, shop["latent_var_weekday"])
             * ramp_mult(days, launch, shop["latent_ramp_r0"], shop["latent_ramp_tau"])
             * trend_mult(days, launch, shop["latent_trend"])
             * np.exp(rng.normal(0, cfg["daily_noise_sigma"], len(days))))
    if shop["latent_shock"]:
        s0 = pd.Timestamp(shop["latent_shock_start"])
        in_shock = (days >= s0) & (days < s0 + pd.Timedelta(days=cfg["shock"]["length_days"]))
        total = np.where(in_shock, total * shop["latent_shock_mult"], total)
    if dip:
        in_dip = (days >= pd.Timestamp(dip["start"])) & (days <= pd.Timestamp(dip["end"]))
        total = np.where(in_dip, total * dip["mult"], total)

    lo, hi = cfg["purchases"]["restock_every_days"]
    restock_every = int(rng.integers(lo, hi + 1))
    restock_day = (np.arange(len(days)) % restock_every) == restock_every - 1
    restock_day[-1] = True                                   # flush the last partial cycle
    fest = festival_uplift(days, cfg)
    frames = []
    for c in cfg["categories"]:
        sales = (total * shop[f"latent_mix_{c}"] * (1.0 + shop["latent_var_festival"] * fest[c])
                 * np.exp(rng.normal(0, cfg["category_noise_sigma"], len(days))))
        sales = np.round(sales, 2)
        cogs = sales * (1.0 - shop[f"margin_{c}"])
        cycle = np.concatenate([[0], np.cumsum(restock_day)[:-1]])      # restock cycle index per day
        cycle_cogs = np.bincount(cycle, weights=cogs)
        factor = rng.uniform(*cfg["purchases"]["cogs_factor"], len(cycle_cogs))
        purchases = np.where(restock_day, (cycle_cogs * factor)[cycle], 0.0)
        frames.append(pd.DataFrame({"shop_id": shop["shop_id"], "day": days.date, "category": c,
                                    "sales": sales, "purchases": np.round(purchases, 2)}))
    return pd.concat(frames, ignore_index=True)


def make_labels(shops: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.merge(shops[["shop_id", "launch_date"]], on="shop_id")
    launch = pd.to_datetime(d["launch_date"])
    day = pd.to_datetime(d["day"])
    month_k = (day.dt.year - launch.dt.year) * 12 + (day.dt.month - launch.dt.month) + 1
    month_k -= (day.dt.day < launch.dt.day).astype(int)       # months counted from the launch day
    d["month_k"] = month_k
    rev = d.groupby(["shop_id", "month_k"])["sales"].sum().unstack(fill_value=0.0)
    out = pd.DataFrame({
        "shop_id": rev.index,
        "rev_first_3m": rev.loc[:, 1:3].sum(axis=1).round(2).values,
        "rev_12m": rev.loc[:, 1:12].sum(axis=1).round(2).values,
    })
    out["is_synthetic"] = True
    return out


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df = df.copy()
    df["is_synthetic"] = True
    df.to_csv(path, index=False, lineterminator="\n", float_format="%.4f")


def write_metadata(out: Path, cfg_hash: str, seed: int, files: dict[str, int], extra: dict | None = None):
    meta = {
        "is_synthetic": True,
        "warning": "SYNTHETIC DATA for prototype training and demos. Not real shop data.",
        "generator": "data/synthetic/generate.py", "generator_version": GENERATOR_VERSION,
        "seed": seed, "config_sha256": cfg_hash, "rows": files,
        "festival_dates_verified": False, **(extra or {}),
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def generate(cfg: dict, cfg_hash: str, seed: int, out: Path, n_shops: int | None = None) -> dict[str, int]:
    rng = np.random.default_rng(seed)
    out.mkdir(parents=True, exist_ok=True)
    shops = [sample_shop(rng, cfg, i + 1) for i in range(n_shops or cfg["n_shops"])]
    daily = pd.concat([simulate_daily(rng, s, cfg) for s in shops], ignore_index=True)
    shops_df = pd.DataFrame(shops)
    labels = make_labels(shops_df, daily)
    write_csv(shops_df, out / "shops.csv")
    write_csv(daily, out / "daily.csv")
    labels.to_csv(out / "labels.csv", index=False, lineterminator="\n", float_format="%.2f")
    rows = {"shops.csv": len(shops_df), "daily.csv": len(daily), "labels.csv": len(labels)}
    write_metadata(out, cfg_hash, seed, rows, {"months_per_shop": cfg["months"]})
    return rows


def demo_shop(dm: dict, cfg: dict) -> dict:
    feat = {k: dm[k] for k in ("homes", "schools", "transit", "banks_atms", "competitors")}
    return {
        "shop_id": dm["shop_id"], "name": dm["name"], "shop_type": "kirana", "city_tier": dm["city_tier"],
        **feat, "size_sqft": float(dm["size_sqft"]), "monthly_rent": float(dm["monthly_rent"]),
        "staff_count": dm["staff_count"], "staff_wage": float(dm["staff_wage"]), "budget": float(dm["budget"]),
        "launch_date": dm["launch_date"], "is_demo": True,
        **{f"margin_{c}": round(float(np.mean(cfg["margins"][c])), 4) for c in cfg["categories"]},
        "latent_steady_daily": round(
            steady_revenue(feat, dm["size_sqft"], dm["city_tier"], cfg, dm["performance"]), 2),
        "latent_performance": dm["performance"],
        "latent_ramp_r0": float(np.mean(cfg["ramp_up"]["r0"])),
        "latent_ramp_tau": float(np.mean(cfg["ramp_up"]["tau_months"])),
        "latent_trend": float(np.mean(cfg["trend_annual"])),
        "latent_var_weekday": 1.0, "latent_var_ramp_up": 1.0, "latent_var_festival": 1.0,
        "latent_shock": False, "latent_shock_start": "", "latent_shock_mult": 1.0,
        **{f"latent_mix_{c}": cfg["category_mix"]["base"][c] for c in cfg["categories"]},
    }


def generate_demo(cfg: dict, cfg_hash: str, seed: int, out: Path) -> dict[str, int]:
    """Fixed, hand-set demo shops (Ramesh Kirana, Sunita General Store); only the noise is seeded."""
    out.mkdir(parents=True, exist_ok=True)
    shops, daily, loans = [], [], []
    for k, dm in enumerate(cfg["demos"]):
        rng = np.random.default_rng(seed + 1_000_003 + k)   # own stream: demos never shift training data
        shop = demo_shop(dm, cfg)
        shops.append(shop)
        daily.append(simulate_daily(rng, shop, cfg, end=pd.Timestamp(dm["end_date"]), dip=dm.get("dip")))
        loans.append({"shop_id": dm["shop_id"], **dm["loan"]})
    daily_df = pd.concat(daily, ignore_index=True)
    write_csv(pd.DataFrame(shops), out / "shops.csv")
    write_csv(daily_df, out / "daily.csv")
    write_csv(pd.DataFrame(loans), out / "loans.csv")
    rows = {"shops.csv": len(shops), "daily.csv": len(daily_df), "loans.csv": len(loans)}
    write_metadata(out, cfg_hash, seed, rows, {"demo": True, "demo_shops": [d["shop_id"] for d in cfg["demos"]]})
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=HERE / "config.yaml")
    ap.add_argument("--seed", type=int, default=None, help="default: seed in config.yaml")
    ap.add_argument("--out", type=Path, default=HERE / "out")
    ap.add_argument("--n-shops", type=int, default=None, help="override n_shops (for quick tests)")
    ap.add_argument("--demo", action="store_true", help="also write the demo shops to <out>/demo/")
    a = ap.parse_args(argv)
    cfg, h = load_config(a.config)
    seed = cfg["seed"] if a.seed is None else a.seed
    rows = generate(cfg, h, seed, a.out, a.n_shops)
    print(f"[SYNTHETIC] wrote {a.out}: {rows} (seed={seed}, {date.today().isoformat()})")
    if a.demo:
        rows = generate_demo(cfg, h, seed, a.out / "demo")
        print(f"[SYNTHETIC] wrote {a.out / 'demo'}: {rows}")


if __name__ == "__main__":
    main()
