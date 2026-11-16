"""ML2 feature table (ML_PLAN section 4, DEC-33): one row per shop x month k (k = 1..12).

Shared by training (M-03), evaluation (M-04) and the forecast service (M-05), so a shop profile turns into
exactly the same columns everywhere. Columns prefixed `latent_` in the synthetic data are NEVER used.
"""
from __future__ import annotations

import pandas as pd

HORIZON = 12
# Order matters: it is the column order the models are trained on.
FEATURES = [
    "size_sqft", "homes", "schools", "transit", "banks_atms", "competitors",
    "monthly_rent", "staff_count", "city_tier", "open_month", "k", "cal_month",
]
# +1: prediction never falls when the feature rises; -1: never rises; 0: free (DEC-34)
MONOTONE = {"size_sqft": 1, "homes": 1, "schools": 1, "transit": 1, "banks_atms": 1, "competitors": -1}
TARGET = "revenue"


def monotone_vector() -> list[int]:
    return [MONOTONE.get(f, 0) for f in FEATURES]


def month_rows(shops: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    """Expand static shop profiles to one row per month k. `shops` needs the static FEATURES + launch_date."""
    launch = pd.to_datetime(shops["launch_date"])
    rows = shops.assign(_launch=launch).loc[shops.index.repeat(horizon)].copy()
    rows["k"] = list(range(1, horizon + 1)) * len(shops)
    # calendar month of the middle of month k (months counted from the launch day), so festivals line up
    mid = [ln + pd.DateOffset(months=k - 1) + pd.Timedelta(days=15) for ln, k in zip(rows["_launch"], rows["k"], strict=True)]
    rows["cal_month"] = [d.month for d in mid]
    rows["open_month"] = rows["_launch"].dt.month
    return rows.drop(columns="_launch").reset_index(drop=True)


def monthly_revenue(shops: pd.DataFrame, daily: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    """Revenue per shop and month k, months counted from the launch day (same rule as labels.csv)."""
    d = daily.groupby(["shop_id", "day"], as_index=False)["sales"].sum()
    d = d.merge(shops[["shop_id", "launch_date"]], on="shop_id")
    launch, day = pd.to_datetime(d["launch_date"]), pd.to_datetime(d["day"])
    k = (day.dt.year - launch.dt.year) * 12 + (day.dt.month - launch.dt.month) + 1
    d["k"] = k - (day.dt.day < launch.dt.day).astype(int)
    d = d[d["k"].between(1, horizon)]
    return d.groupby(["shop_id", "k"], as_index=False)["sales"].sum().rename(columns={"sales": TARGET})


def training_table(shops: pd.DataFrame, daily: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    rows = month_rows(shops, horizon).merge(monthly_revenue(shops, daily, horizon), on=["shop_id", "k"])
    return rows[["shop_id", *FEATURES, TARGET]]
