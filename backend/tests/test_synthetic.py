"""D-01: 200 shops x 24 months; same seed => identical files; every file labelled synthetic."""
import hashlib
import importlib.util
import json

import pandas as pd
import pytest

from app.config import REPO_ROOT

GEN_PATH = REPO_ROOT / "data" / "synthetic" / "generate.py"
_spec = importlib.util.spec_from_file_location("synthetic_generate", GEN_PATH)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _hashes(d):
    return {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("synA")
    gen.main(["--out", str(out), "--demo"])
    return out


def test_full_size_200_shops_24_months(full_run):
    shops = pd.read_csv(full_run / "shops.csv")
    daily = pd.read_csv(full_run / "daily.csv", parse_dates=["day"])
    assert len(shops) == 200 and shops.shop_id.is_unique
    span = daily.groupby("shop_id").day.agg(["min", "max", "nunique"])
    launch = pd.to_datetime(shops.set_index("shop_id").launch_date)
    assert (span["min"] == launch).all()
    expected_end = launch + pd.DateOffset(months=24) - pd.Timedelta(days=1)
    assert (span["max"] == expected_end).all()
    assert (span["nunique"] == (expected_end - launch).dt.days + 1).all()   # no missing days
    assert set(daily.category) == {"staples", "dairy", "snacks_beverages", "household", "personal_care"}
    assert (daily.sales > 0).all() and (daily.purchases >= 0).all()


def test_same_seed_identical(full_run, tmp_path):
    gen.main(["--out", str(tmp_path), "--demo"])
    assert _hashes(full_run) == _hashes(tmp_path)


def test_different_seed_differs(full_run, tmp_path):
    gen.main(["--out", str(tmp_path), "--seed", "7", "--n-shops", "5"])
    a = pd.read_csv(full_run / "shops.csv").head(5)
    b = pd.read_csv(tmp_path / "shops.csv")
    assert not a.equals(b)


def test_every_file_is_labelled_synthetic(full_run):
    files = [p for p in full_run.rglob("*") if p.is_file()]
    assert {p.name for p in files} >= {"shops.csv", "daily.csv", "labels.csv", "metadata.json", "loans.csv"}
    for p in files:
        if p.suffix == ".csv":
            assert pd.read_csv(p).is_synthetic.all(), p
        else:
            assert json.loads(p.read_text())["is_synthetic"] is True, p


def test_labels_match_daily(full_run):
    daily = pd.read_csv(full_run / "daily.csv", parse_dates=["day"])
    labels = pd.read_csv(full_run / "labels.csv").set_index("shop_id")
    shops = pd.read_csv(full_run / "shops.csv").set_index("shop_id")
    sid = "S0001"
    launch = pd.Timestamp(shops.loc[sid, "launch_date"])
    d = daily[daily.shop_id == sid]
    first3 = d[d.day < launch + pd.DateOffset(months=3)].sales.sum()
    year1 = d[d.day < launch + pd.DateOffset(months=12)].sales.sum()
    assert labels.loc[sid, "rev_first_3m"] == pytest.approx(first3, rel=1e-6)
    assert labels.loc[sid, "rev_12m"] == pytest.approx(year1, rel=1e-6)


def test_patterns_present(full_run):
    """Weekend uplift, ramp-up (month 1 below month 6) and Diwali spike exist in the data."""
    daily = pd.read_csv(full_run / "daily.csv", parse_dates=["day"])
    shops = pd.read_csv(full_run / "shops.csv")
    t = daily.groupby(["shop_id", "day"]).sales.sum().reset_index().merge(shops[["shop_id", "launch_date"]])
    t["m"] = (t.day - pd.to_datetime(t.launch_date)).dt.days // 30
    mature = t[t.m >= 8]
    weekend = mature[mature.day.dt.day_of_week >= 5].sales.mean()
    weekday = mature[mature.day.dt.day_of_week < 5].sales.mean()
    assert weekend / weekday > 1.08
    by_m = t.groupby(["shop_id", "m"]).sales.mean().unstack()
    assert (by_m[0] < by_m[5]).mean() > 0.9
    diwali = t[t.day == "2023-11-12"].sales.mean()
    assert diwali > 1.3 * t[(t.day >= "2023-11-20") & (t.day <= "2023-12-10")].sales.mean()


def _demo(full_run, shop_id):
    d = full_run / "demo"
    shop = pd.read_csv(d / "shops.csv").set_index("shop_id").loc[shop_id]
    daily = pd.read_csv(d / "daily.csv", parse_dates=["day"])
    loan = pd.read_csv(d / "loans.csv").set_index("shop_id").loc[shop_id]
    return shop, daily[daily.shop_id == shop_id], loan


def _monthly_dscr(shop, daily, loan):
    gross = sum((g.sales * shop[f"margin_{c}"]).groupby(g.day.dt.to_period("M")).sum()
                for c, g in daily.groupby("category"))
    sales = daily.groupby(daily.day.dt.to_period("M")).sales.sum()
    fixed = shop.monthly_rent + shop.staff_count * shop.staff_wage
    return sales, (gross - fixed) / loan.emi


def test_demo_ramesh_dip_and_squeeze(full_run):
    shop, daily, loan = _demo(full_run, "DEMO-001")
    assert shop["name"] == "Ramesh Kirana" and bool(shop["is_demo"])
    assert daily.day.min() == pd.Timestamp("2026-08-01") and daily.day.max() == pd.Timestamp("2026-10-31")
    assert loan.emi == 7500 and loan.due_day == 5
    tot = daily.groupby("day").sales.sum()
    in_dip = tot["2026-09-05":"2026-09-25"].mean()
    around = pd.concat([tot["2026-08-15":"2026-09-04"], tot["2026-09-26":"2026-10-10"]]).mean()
    assert in_dip < 0.8 * around
    _, dscr = _monthly_dscr(shop, daily, loan)
    assert dscr.min() < 1.0                                  # EMI squeeze exists


def test_demo_sunita_meets_grow_conditions(full_run):
    """review_rules grow: dscr >= 1.5, growth_rate > 0, data_completeness >= 0.7 (revenue_vs_p50 needs M-02)."""
    shop, daily, loan = _demo(full_run, "DEMO-002")
    assert shop["name"] == "Sunita General Store" and loan.due_day == 10
    assert daily.groupby("day").category.nunique().eq(5).all() and daily.day.nunique() == 92
    sales, dscr = _monthly_dscr(shop, daily, loan)
    assert (dscr >= 1.5).all(), dscr
    assert sales.is_monotonic_increasing, sales
    assert shop.latent_performance == 1.15


def test_floor_binds_rarely(full_run):
    shops = pd.read_csv(full_run / "shops.csv")
    floor = gen.load_config(GEN_PATH.parent / "config.yaml")[0]["steady_revenue"]["clip"][0]
    assert (shops.latent_steady_daily <= floor).mean() < 0.02


def test_per_shop_variation(full_run):
    shops = pd.read_csv(full_run / "shops.csv")
    for k in ("weekday", "ramp_up", "festival"):
        col = shops[f"latent_var_{k}"]
        assert col.between(0.9, 1.1).all() and col.std() > 0.03, k


def test_festival_uplift_differs_by_category(full_run):
    """Diwali profile: household rises more than staples (1.5 vs 0.7 before rescaling)."""
    daily = pd.read_csv(full_run / "daily.csv", parse_dates=["day"])
    by = daily.groupby(["day", "category"]).sales.sum().unstack()
    normal = by.loc["2023-11-20":"2023-12-10"].mean()
    lift = by.loc[pd.Timestamp("2023-11-12")] / normal
    assert lift["household"] > lift["staples"] + 0.3
    assert lift["snacks_beverages"] > lift["staples"]
