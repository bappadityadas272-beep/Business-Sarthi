"""Method check on a PUBLIC retail dataset (ML_PLAN section 8, D-02). REAL data, not synthetic (is_synthetic: false).

    docker compose run --rm -T -w /repo/backend backend python ../eval/public_validation.py --data ../eval/public_data
    python ../eval/public_validation.py --data DIR_OR_FILE [--horizon 4] [--test-weeks 26] [--seed 42] [--json] [--write]

Dataset: UCI Online Retail II, CC BY 4.0 (docs/PUBLIC_DATA.md). The raw file is never committed; put it in
eval/public_data/ (git-ignored). CustomerID is never read.

What is checked: the METHOD of ML2 (DEC-35, DEC-38), not the ML2 model itself, which needs shop profiles this
dataset does not have. One series = one product's weekly revenue. For a forecast origin week t we predict week
t + h (h = --horizon) from the series' own past only.

    method      LightGBM P50 with Huber loss (params of app.ml.train), leaf size by series-grouped CV on TRAIN
                series only; band P10 = P50 x r10, P90 = P50 x r90, r10/r90 from split conformal on actual / P50
                over the CALIBRATION series (app.ml.calibrate.conformal_bounds, target 80%).
    qgbm_cqr    LightGBM with objective="quantile" at 0.1 / 0.5 / 0.9 plus conformalised quantile regression
                (CQR) on the calibration series. A second reading of "quantile GBM + conformal"; same leaf size.
    seasonal    Seasonal naive: P50 = revenue of week t + h - 52; band = P50 + split-conformal residual bounds
    _naive      from the calibration series (clipped at 0).

Leakage rules (checked in code, not by assert): series are split 60/20/20 into train / calibration / test by a
seeded permutation; train and calibration rows have targets BEFORE the cut week, test rows ON or AFTER it, so no
model or band ever sees a test-period week; features of a row use weeks <= its origin only; series are chosen,
and volume groups are cut, from weeks before the cut only.

Targets (ML_PLAN section 8, unchanged): method P10-P90 coverage within 75% to 85%, and method beats seasonal naive
(lower WAPE and lower mean pinball). Results are reported as measured, MET or MISSED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import lightgbm as lgb
from sklearn.model_selection import GroupKFold

from app.ml.calibrate import TARGET_COVERAGE, conformal_bounds
from app.ml.train import ALPHAS, CV_FOLDS, LEAF_GRID, PARAMS, pinball

DEFAULT_DATA = REPO / "eval" / "public_data"
REPORT = REPO / "docs" / "PUBLIC_VALIDATION_REPORT.md"
DATASET = {
    "name": "Online Retail II", "publisher": "UCI Machine Learning Repository",
    "url": "https://archive.ics.uci.edu/dataset/502/online+retail+ii", "doi": "https://doi.org/10.24432/C5CG6D",
    "licence": "CC BY 4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0/",
    "citation": "Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository. "
                "https://doi.org/10.24432/C5CG6D",
    "changes": "Filtered and aggregated to weekly revenue per product by Business Sarthi; not the original data.",
}
SEASON = 52                         # weeks
COVERAGE_BAND = (0.75, 0.85)        # ML_PLAN section 8
MIN_ACTIVE_SHARE = 0.80             # a series needs sales in >= 80% of the weeks before the cut (assumption)
SCALE_WEEKS = 13                    # level = mean revenue of the 13 weeks up to the origin
HUBER_DELTA_SCALED = 1.0            # Huber delta in units of the series level (assumption; ML2 uses INR 20,000)
P50_FLOOR = 1.0                     # same floor as app.ml.train.predict_quantiles (1 currency unit)
BOOTSTRAP = 500                     # series-level bootstrap draws for the uncertainty of the headline numbers
PRODUCT_CODE = r"^\d{5}[A-Za-z]{0,2}$"     # real products; drops POST, M, D, DOT, BANK CHARGES, gift cards, tests
COLUMNS = {"invoice": ("Invoice", "InvoiceNo"), "stock_code": ("StockCode",), "quantity": ("Quantity",),
           "invoice_date": ("InvoiceDate",), "price": ("Price", "UnitPrice"), "country": ("Country",)}
NEVER_READ = ("customer",)          # CustomerID / Customer ID: excluded at read time (docs/PUBLIC_DATA.md)
FEATURES = ["lag0", "lag1", "lag2", "lag3", "roll4", "roll13", "seas", "seas_mean3", "zero_share13", "log_level",
            "woy"]
METHODS = ("method", "qgbm_cqr", "seasonal_naive")


# ---------------------------------------------------------------- reading and cleaning

def _wanted(col: str) -> bool:
    c = str(col).strip().lower().replace(" ", "")
    return not any(c.startswith(n) for n in NEVER_READ) and any(
        c == a.lower() for names in COLUMNS.values() for a in names)


def _sha256(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()


def input_files(data: Path) -> list[Path]:
    files = sorted([*data.glob("*.csv"), *data.glob("*.xlsx")]) if data.is_dir() else [data]
    files = [f for f in files if f.is_file()]
    if not files:
        raise SystemExit(f"no .csv or .xlsx file in {data}: download the dataset first (docs/PUBLIC_DATA.md)")
    return files


def read_sources(files: list[Path]) -> list[pd.DataFrame]:
    """One frame per sheet or CSV, columns renamed to COLUMNS keys, all as text. CustomerID is never loaded."""
    frames = []
    for f in files:
        if f.suffix.lower() == ".xlsx":
            try:
                sheets = pd.read_excel(f, sheet_name=None, usecols=_wanted, dtype=str)
            except ImportError as e:
                raise SystemExit("reading .xlsx needs openpyxl, which is not in the backend image: export each "
                                 "sheet to CSV into the same folder instead (docs/PUBLIC_DATA.md)") from e
            frames += list(sheets.values())
        else:
            try:
                frames.append(pd.read_csv(f, usecols=_wanted, dtype=str, encoding="utf-8"))
            except UnicodeDecodeError:
                frames.append(pd.read_csv(f, usecols=_wanted, dtype=str, encoding="latin-1"))
    out = []
    for df in frames:
        ren = {}
        for key, names in COLUMNS.items():
            hit = [c for c in df.columns if str(c).strip().lower().replace(" ", "") in {n.lower() for n in names}]
            if not hit:
                raise SystemExit(f"column {names[0]} not found (columns: {list(df.columns)})")
            ren[hit[0]] = key
        out.append(df.rename(columns=ren)[list(COLUMNS)])
    return out


def clean(sources: list[pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """Sales lines only. An invoice found in more than one source (sheets can overlap) is kept from the first."""
    seen: set[str] = set()
    parts, dup_rows = [], 0
    for df in sources:
        inv = df["invoice"].astype(str).str.strip()
        dup = inv.isin(seen)
        dup_rows += int(dup.sum())
        seen |= set(inv[~dup])
        parts.append(df[~dup])
    df = pd.concat(parts, ignore_index=True)
    counts = {"rows_read": int(sum(len(s) for s in sources)), "rows_in_overlapping_invoices_dropped": dup_rows}
    inv = df["invoice"].astype(str).str.strip()
    code = df["stock_code"].astype(str).str.strip().str.upper()
    qty = pd.to_numeric(df["quantity"], errors="coerce")
    price = pd.to_numeric(df["price"], errors="coerce")
    when = pd.to_datetime(df["invoice_date"], errors="coerce", format="mixed")
    keep = {
        "not_cancelled_or_adjustment": inv.str.fullmatch(r"\d+"),   # C... = cancel, A... = bad-debt adjustment
        "product_code": code.str.fullmatch(PRODUCT_CODE),
        "quantity_positive": qty > 0,
        "price_positive": price > 0,
        "date_parsed": when.notna(),
    }
    mask = np.ones(len(df), dtype=bool)
    for name, m in keep.items():
        ok = m.fillna(False).to_numpy(dtype=bool)
        counts[f"dropped_{name}"] = int((mask & ~ok).sum())
        mask &= ok
    out = pd.DataFrame({"series": code[mask].to_numpy(), "when": when[mask].to_numpy(),
                        "revenue": (qty[mask] * price[mask]).to_numpy()})
    counts["rows_kept"] = len(out)
    return out, counts


def weekly(lines: pd.DataFrame) -> pd.DataFrame:
    """series x week revenue (weeks Monday to Sunday), 0 where a series sold nothing. Partial first and last
    weeks of the whole dataset are dropped, so every week has 7 days of data."""
    day0, day1 = lines["when"].min().normalize(), lines["when"].max().normalize()
    wk = lines["when"].dt.to_period("W-SUN").dt.start_time
    full = pd.date_range(wk.min(), wk.max(), freq="7D")
    full = full[(full >= day0) & (full + pd.Timedelta(days=6) <= day1)]
    m = lines.assign(week=wk).groupby(["series", "week"])["revenue"].sum().unstack(fill_value=0.0)
    return m.reindex(columns=full, fill_value=0.0).astype(float)


# ---------------------------------------------------------------- rows, split, features

def split_series(ids: list[str], seed: int) -> dict[str, list[str]]:
    ids = sorted(ids)
    order = np.random.default_rng(seed).permutation(len(ids))
    n_tr, n_cal = round(len(ids) * 0.6), round(len(ids) * 0.2)

    def pick(a: int, b: int) -> list[str]:
        return sorted(ids[i] for i in order[a:b])
    return {"train": pick(0, n_tr), "calibration": pick(n_tr, n_tr + n_cal), "test": pick(n_tr + n_cal, len(ids))}


def make_rows(W: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """One row per (series, target week). Target index j = origin t + horizon; every feature uses weeks <= t,
    except the seasonal ones, which use weeks j - 53 .. j - 51 (all <= t because horizon <= 51)."""
    if not 1 <= horizon <= SEASON - 2:
        raise SystemExit(f"--horizon must be 1..{SEASON - 2}")
    Y = W.to_numpy()
    weeks = W.columns
    first = max(SEASON + 1, SCALE_WEEKS - 1 + horizon)
    out = []
    for j in range(first, Y.shape[1]):
        t = j - horizon
        hist13 = Y[:, t - SCALE_WEEKS + 1:t + 1]
        level = hist13.mean(axis=1)
        s = level + 1.0                                  # scale; +1 keeps dormant series finite (assumption)
        out.append(pd.DataFrame({
            "series": W.index, "target_week": weeks[j], "origin_week": weeks[t], "j": j,
            "y": Y[:, j], "scale": s,
            "lag0": Y[:, t] / s, "lag1": Y[:, t - 1] / s, "lag2": Y[:, t - 2] / s, "lag3": Y[:, t - 3] / s,
            "roll4": Y[:, t - 3:t + 1].mean(axis=1) / s, "roll13": level / s,
            "seas": Y[:, j - SEASON] / s, "seas_mean3": Y[:, j - SEASON - 1:j - SEASON + 2].mean(axis=1) / s,
            "zero_share13": (hist13 <= 0).mean(axis=1), "log_level": np.log1p(level),
            "woy": weeks[j].isocalendar()[1],
            "snaive": Y[:, j - SEASON],
        }))
    rows = pd.concat(out, ignore_index=True)
    if (rows["j"] - horizon < rows["j"] - SEASON + 1).any():   # not assert: kept under python -O
        raise ValueError("a seasonal feature reaches past the origin week")
    return rows


# ---------------------------------------------------------------- models

def _lgb(objective: str, leaf: int, seed: int, alpha: float | None = None) -> lgb.LGBMRegressor:
    params = {k: v for k, v in PARAMS.items() if k not in ("objective", "alpha")}
    if objective == "huber":
        params["alpha"] = HUBER_DELTA_SCALED
    else:
        params["alpha"] = alpha
    return lgb.LGBMRegressor(objective=objective, min_child_samples=leaf, random_state=seed, **params)


def p50_method(model, rows: pd.DataFrame) -> np.ndarray:
    return np.maximum(model.predict(rows[FEATURES]), 0.0) * rows["scale"].to_numpy()


def ratio_band(y: np.ndarray, p50: np.ndarray) -> tuple[float, float]:
    return conformal_bounds(y / np.maximum(p50, P50_FLOOR), 1 - TARGET_COVERAGE)


def apply_ratio(p50: np.ndarray, band: tuple[float, float]) -> np.ndarray:
    base = np.maximum(p50, P50_FLOOR)
    return np.sort(np.column_stack([base * band[0], base, base * band[1]]), axis=1)


def choose_leaf(train: pd.DataFrame, seed: int) -> tuple[int, dict]:
    """Like app.ml.train.choose_leaf: out-of-fold P50 per leaf size, folds grouped by SERIES, on train rows only;
    lowest mean pinball of the ratio band wins, ties to the smaller leaf."""
    y, yz, g = train["y"].to_numpy(), (train["y"] / train["scale"]).to_numpy(), train["series"]
    scores = {}
    for leaf in LEAF_GRID:
        oof = np.zeros(len(train))
        for tr, va in GroupKFold(n_splits=CV_FOLDS).split(train, yz, g):
            m = _lgb("huber", leaf, seed).fit(train.iloc[tr][FEATURES], yz[tr])
            oof[va] = p50_method(m, train.iloc[va])
        r = y / np.maximum(oof, P50_FLOOR)
        q = apply_ratio(oof, (float(np.quantile(r, 0.1)), float(np.quantile(r, 0.9))))
        scores[leaf] = round(float(np.mean([pinball(y, q[:, i], a) for i, a in enumerate(ALPHAS)])), 4)
    return min(LEAF_GRID, key=lambda lf: (scores[lf], lf)), scores


def cqr_quantile(scores: np.ndarray, alpha: float) -> float:
    """Upper conformal quantile: the ceil((n+1)(1-alpha))-th smallest score (finite-sample corrected)."""
    s = np.sort(scores)
    k = min(len(s), int(np.ceil((len(s) + 1) * (1 - alpha))))
    return float(s[k - 1])


def fit_all(part: dict[str, pd.DataFrame], seed: int) -> tuple[dict[str, np.ndarray], dict]:
    tr, cal, te = part["train"], part["calibration"], part["test"]
    leaf, leaf_scores = choose_leaf(tr, seed)
    yz = (tr["y"] / tr["scale"]).to_numpy()
    y_cal = cal["y"].to_numpy()

    huber = _lgb("huber", leaf, seed).fit(tr[FEATURES], yz)
    band = ratio_band(y_cal, p50_method(huber, cal))
    q = {"method": apply_ratio(p50_method(huber, te), band)}

    qm = [_lgb("quantile", leaf, seed, a).fit(tr[FEATURES], yz) for a in ALPHAS]

    def raw(rows: pd.DataFrame) -> np.ndarray:
        return np.sort(np.column_stack([m.predict(rows[FEATURES]) for m in qm]), axis=1)   # scaled units
    rc = raw(cal)
    e = np.maximum(rc[:, 0] - y_cal / cal["scale"].to_numpy(), y_cal / cal["scale"].to_numpy() - rc[:, 2])
    qhat = cqr_quantile(e, 1 - TARGET_COVERAGE)
    rt = raw(te)
    s_te = te["scale"].to_numpy()[:, None]
    adj = np.column_stack([rt[:, 0] - qhat, rt[:, 1], rt[:, 2] + qhat]) * s_te
    q["qgbm_cqr"] = np.sort(np.maximum(adj, 0.0), axis=1)

    res = y_cal - cal["snaive"].to_numpy()
    lo, hi = conformal_bounds(res, 1 - TARGET_COVERAGE)
    sn = te["snaive"].to_numpy()
    q["seasonal_naive"] = np.sort(np.maximum(np.column_stack([sn + lo, sn, sn + hi]), 0.0), axis=1)
    info = {"leaf": leaf, "leaf_cv_mean_pinball": {str(k): v for k, v in leaf_scores.items()},
            "method_ratio_band": {"r10": round(band[0], 6), "r90": round(band[1], 6)},
            "cqr_qhat_scaled": round(qhat, 6), "seasonal_naive_residual_band": [round(lo, 2), round(hi, 2)]}
    return q, info


# ---------------------------------------------------------------- metrics

def wape(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.abs(y - p).sum() / y.sum()) if y.sum() > 0 else float("nan")


def metrics(y: np.ndarray, q: np.ndarray) -> dict:
    inside = (y >= q[:, 0]) & (y <= q[:, 2])
    pb = {f"p{round(a * 100):02d}": round(pinball(y, q[:, i], a), 4) for i, a in enumerate(ALPHAS)}
    return {"n": len(y), "wape": round(wape(y, q[:, 1]), 4), "pinball": pb,
            "mean_pinball": round(float(np.mean(list(pb.values()))), 4),
            "coverage": round(float(inside.mean()), 4), "below_p10": round(float((y < q[:, 0]).mean()), 4),
            "above_p90": round(float((y > q[:, 2]).mean()), 4),
            "width_share_of_mean_actual": round(float((q[:, 2] - q[:, 0]).mean() / max(y.mean(), 1e-9)), 4)}


def bootstrap(te: pd.DataFrame, q: dict[str, np.ndarray], seed: int, draws: int = BOOTSTRAP) -> dict:
    """Resample TEST SERIES with replacement (a series' weeks move together); 5th and 95th percentiles."""
    y = te["y"].to_numpy()
    idx_by = list(te.groupby("series").indices.values())
    rng = np.random.default_rng(seed)
    cov, gain = [], []
    for _ in range(draws):
        pick = np.concatenate([idx_by[i] for i in rng.integers(0, len(idx_by), len(idx_by))])
        qm, qs = q["method"][pick], q["seasonal_naive"][pick]
        cov.append(((y[pick] >= qm[:, 0]) & (y[pick] <= qm[:, 2])).mean())
        gain.append(1 - wape(y[pick], qm[:, 1]) / wape(y[pick], qs[:, 1]))
    def p(a: list) -> list[float]:
        return [round(float(np.nanpercentile(a, 5)), 4), round(float(np.nanpercentile(a, 95)), 4)]
    return {"draws": draws, "unit": "test series", "method_coverage_p5_p95": p(cov),
            "method_wape_gain_vs_seasonal_naive_p5_p95": p(gain)}


def groups(te: pd.DataFrame, pre: pd.DataFrame, train_ids: list[str]) -> dict[str, np.ndarray]:
    """Group labels per test row: volume tercile (cuts from TRAIN series, pre-cut weeks) and target quarter."""
    mean_pre = pre.mean(axis=1)
    cuts = [float(x) for x in mean_pre.loc[train_ids].quantile([1 / 3, 2 / 3])]
    vol = pd.cut(te["series"].map(mean_pre), [-np.inf, *cuts, np.inf], labels=["low", "mid", "high"]).astype(str)
    qtr = te["target_week"].dt.year.astype(str) + "-Q" + te["target_week"].dt.quarter.astype(str)
    return {"volume_tercile": vol.to_numpy(), "target_quarter": qtr.to_numpy(), "_cuts": np.array(cuts)}


# ---------------------------------------------------------------- run

def evaluate(data: Path, horizon: int, test_weeks: int, seed: int) -> dict:
    files = input_files(data)
    lines, counts = clean(read_sources(files))
    W = weekly(lines)
    n_weeks = W.shape[1]
    cut_j = n_weeks - test_weeks                      # first test target index
    first_target = max(SEASON + 1, SCALE_WEEKS - 1 + horizon)
    if cut_j - first_target < 8:
        raise SystemExit(f"too few weeks before the cut: {n_weeks} weeks, test {test_weeks}, need targets from "
                         f"week index {first_target}")
    pre = W.iloc[:, :cut_j]
    active = (pre > 0).mean(axis=1) >= MIN_ACTIVE_SHARE   # chosen from pre-cut weeks only
    W = W[active]
    pre = pre[active]
    if len(W) < 50:
        raise SystemExit(f"only {len(W)} series pass the activity filter; the check needs at least 50")
    split = split_series(W.index.tolist(), seed)
    sets = {k: set(v) for k, v in split.items()}
    if (sets["train"] & sets["calibration"]) or (sets["train"] & sets["test"]) or (sets["calibration"] & sets["test"]):
        raise ValueError("series overlap between train, calibration and test")

    rows = make_rows(W, horizon)
    part = {
        "train": rows[rows["series"].isin(sets["train"]) & (rows["j"] < cut_j)].reset_index(drop=True),
        "calibration": rows[rows["series"].isin(sets["calibration"]) & (rows["j"] < cut_j)].reset_index(drop=True),
        "test": rows[rows["series"].isin(sets["test"]) & (rows["j"] >= cut_j)].reset_index(drop=True),
    }
    if part["train"]["j"].max() >= part["test"]["j"].min() or part["calibration"]["j"].max() >= cut_j:
        raise ValueError("a train or calibration target lies in the test period")
    q, info = fit_all(part, seed)
    te = part["test"]
    y = te["y"].to_numpy()
    res = {m: metrics(y, q[m]) for m in METHODS}
    g = groups(te, pre, split["train"])
    by = {}
    for name in ("volume_tercile", "target_quarter"):
        lab = g[name]
        by[name] = {str(v): {m: metrics(y[lab == v], q[m][lab == v]) for m in METHODS}
                    for v in sorted(set(lab), key=lambda x: (["low", "mid", "high"].index(x)
                                                             if x in ("low", "mid", "high") else 9, x))}
    m, sn = res["method"], res["seasonal_naive"]
    cov_ok = COVERAGE_BAND[0] <= m["coverage"] <= COVERAGE_BAND[1]
    return {
        "is_synthetic": False, "dataset": DATASET,
        "input": {"files": [f.name for f in files], "sha256": _sha256(files), "cleaning": counts},
        "setup": {"series_unit": "product (StockCode)", "frequency": "weekly (Mon-Sun)", "weeks": n_weeks,
                  "first_week": str(W.columns[0].date()), "last_week": str(W.columns[-1].date()),
                  "cut_week": str(W.columns[cut_j].date()), "test_weeks": test_weeks, "horizon_weeks": horizon,
                  "min_active_share_before_cut": MIN_ACTIVE_SHARE, "series_kept": len(W),
                  "series_split": {k: len(v) for k, v in split.items()}, "split_seed": seed,
                  "rows": {k: len(v) for k, v in part.items()}, "target_coverage": TARGET_COVERAGE,
                  "huber_delta_scaled": HUBER_DELTA_SCALED, "monotone_constraints": "none (no profile features)",
                  "volume_tercile_cuts": [round(float(c), 2) for c in g["_cuts"]]},
        "fit": info, "overall": res, "by_group": by, "bootstrap": bootstrap(te, q, seed),
        "targets": {
            "coverage_in_band": {"value": m["coverage"], "band": list(COVERAGE_BAND), "met": bool(cov_ok)},
            "wape_below_seasonal_naive": {"method": m["wape"], "seasonal_naive": sn["wape"],
                                          "met": bool(m["wape"] < sn["wape"])},
            "mean_pinball_below_seasonal_naive": {"method": m["mean_pinball"], "seasonal_naive": sn["mean_pinball"],
                                                  "met": bool(m["mean_pinball"] < sn["mean_pinball"])},
        },
    }


def _mark(ok: bool) -> str:
    return "MET" if ok else "**MISSED**"


def _rows(d: dict) -> list[str]:
    out = ["| Method | Rows | WAPE | Pinball P10 | Pinball P50 | Pinball P90 | Coverage P10-P90 | Below P10 | "
           "Above P90 | Width / mean actual |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, v in d.items():
        p = v["pinball"]
        out.append(f"| {name} | {v['n']} | {v['wape']:.3f} | {p['p10']:,.2f} | {p['p50']:,.2f} | {p['p90']:,.2f} | "
                   f"{v['coverage']:.1%} | {v['below_p10']:.1%} | {v['above_p90']:.1%} | "
                   f"{v['width_share_of_mean_actual']:.2f} |")
    return out


def render(r: dict) -> str:
    s, t, d, b = r["setup"], r["targets"], r["dataset"], r["bootstrap"]
    lines = [
        "# PUBLIC_VALIDATION_REPORT: method check on public retail data", "",
        "> Generated by `eval/public_validation.py --write`. Do not edit by hand.",
        "> **REAL public data (`is_synthetic: false`)**, one UK online retailer: this checks the forecasting METHOD,",
        "> not the accuracy of the app's ML2 model for Indian shops (docs/PUBLIC_DATA.md, ML_PLAN section 13).", "",
        f"Data: {d['citation']} Licence {d['licence']} ({d['licence_url']}). {d['changes']}", "",
        f"- Input files {', '.join(r['input']['files'])}, SHA-256 `{r['input']['sha256'][:12]}`; "
        f"rows read {r['input']['cleaning']['rows_read']:,}, kept {r['input']['cleaning']['rows_kept']:,}.",
        f"- {s['series_kept']} product series (sales in at least {s['min_active_share_before_cut']:.0%} of the weeks "
        f"before the cut), {s['weeks']} full weeks {s['first_week']} to {s['last_week']}.",
        f"- Split by series {s['series_split']} (seed {s['split_seed']}); train and calibration targets before "
        f"{s['cut_week']}, test targets from {s['cut_week']} ({s['test_weeks']} weeks). Horizon {s['horizon_weeks']} weeks.",
        f"- Leaf size {r['fit']['leaf']} by series-grouped CV on train rows {r['fit']['leaf_cv_mean_pinball']}; "
        f"method band r10 {r['fit']['method_ratio_band']['r10']:.3f}, r90 {r['fit']['method_ratio_band']['r90']:.3f} "
        f"(split conformal, target {s['target_coverage']:.0%}).", "",
        "## Targets (ML_PLAN section 8)", "",
        "| Target | Result | Status |", "|---|---|---|",
        f"| Method P10-P90 coverage within {t['coverage_in_band']['band'][0]:.0%} to "
        f"{t['coverage_in_band']['band'][1]:.0%} | {t['coverage_in_band']['value']:.1%} "
        f"(series bootstrap 5-95%: {b['method_coverage_p5_p95'][0]:.1%} to {b['method_coverage_p5_p95'][1]:.1%}) | "
        f"{_mark(t['coverage_in_band']['met'])} |",
        f"| Method WAPE below seasonal naive | {t['wape_below_seasonal_naive']['method']:.3f} vs "
        f"{t['wape_below_seasonal_naive']['seasonal_naive']:.3f} (gain 5-95%: "
        f"{b['method_wape_gain_vs_seasonal_naive_p5_p95'][0]:+.1%} to "
        f"{b['method_wape_gain_vs_seasonal_naive_p5_p95'][1]:+.1%}) | {_mark(t['wape_below_seasonal_naive']['met'])} |",
        f"| Method mean pinball below seasonal naive | {t['mean_pinball_below_seasonal_naive']['method']:,.2f} vs "
        f"{t['mean_pinball_below_seasonal_naive']['seasonal_naive']:,.2f} | "
        f"{_mark(t['mean_pinball_below_seasonal_naive']['met'])} |", "",
        "## Overall (test series, test weeks)", "", *_rows(r["overall"]), "",
        "Pinball loss is in the dataset's currency (GBP) per series-week; lower is better.", "",
    ]
    for name, title in (("volume_tercile", "By volume tercile (cuts from train series, pre-cut weeks)"),
                        ("target_quarter", "By target quarter")):
        lines += [f"## {title}", ""]
        for grp, v in r["by_group"][name].items():
            lines += [f"### {grp}", "", *_rows(v), ""]
    lines += ["Groups hold fewer series than the whole test set, and a series' weeks move together, so a group's "
              "coverage can sit several points from the overall figure by chance.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA, help="folder or file (.csv per sheet, or .xlsx)")
    ap.add_argument("--horizon", type=int, default=4, help="weeks ahead (1..50)")
    ap.add_argument("--test-weeks", type=int, default=26)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--json", action="store_true", help="print the raw result as JSON")
    ap.add_argument("--write", action="store_true", help=f"write {REPORT.relative_to(REPO)}")
    a = ap.parse_args(argv)
    r = evaluate(a.data, a.horizon, a.test_weeks, a.seed)
    text = render(r)
    print(json.dumps(r, indent=2) if a.json else text)
    if a.write:
        REPORT.write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"\nwrote {REPORT}")


if __name__ == "__main__":
    main()
