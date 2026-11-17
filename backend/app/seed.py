"""Demo seed (D-05): `make seed` loads the two SYNTHETIC demo shops into the database.

Ramesh Kirana (expected first review: pivot) and Sunita General Store (expected: grow), each with its own demo
login. Everything written here is demo data: shops carry `is_demo`, the figures come from the synthetic generator
(`data/synthetic/out/demo/`, `is_synthetic=true`) and the hand-set values in `data/synthetic/config.yaml`.

Dates are SHIFTED to the day the seed runs (DEC-70): the last log is yesterday and the first 3-month review falls
due 2 days later, so "advance time" produces it live. Weekday and festival patterns in the data therefore no longer
line up with the calendar. Alerts are replayed day by day, as if the app had run since the launch.

Running it again deletes the demo users (and all their data) and writes them afresh."""
import calendar
import hashlib
import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.jobs import review_job
from app.ml import forecast as fc
from app.models import DailyLog, Forecast, Loan, Shop, StockItem, StockMove, User
from app.rules import get_rules
from app.services import alerts as alert_service
from app.services import clock, consent, osm

CONFIG = REPO_ROOT / "data" / "synthetic" / "config.yaml"
DEMO_DIR = REPO_ROOT / "data" / "synthetic" / "out" / "demo"
DAYS_LOGGED = 88                  # launch = today - 88: logs for 88 days, review due in 2 days (launch + 90)
EXPENSE_CATEGORY = "other"        # rent and wages are logged here once a month (DEC-64: logged costs only)
RESTOCK_EVERY, OPENING_COVER = 7, 12
FACTORS = (0.8, 0.9, 1.0, 1.1, 1.2)   # fixed day-to-day pattern of demo unit sales (mean 1.0)


class SeedError(RuntimeError):
    pass


def add_months(d: date, n: int) -> date:
    """Same day of the month `n` months later (the last day when the month is shorter)."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def load_demo(config: Path = CONFIG, demo_dir: Path = DEMO_DIR) -> tuple[dict, pd.DataFrame]:
    """(config, daily rows). Refuses data that is not labelled synthetic or was made from another config."""
    raw = config.read_bytes()
    cfg = yaml.safe_load(raw)
    try:
        meta = json.loads((demo_dir / "metadata.json").read_text(encoding="utf-8"))
        daily = pd.read_csv(demo_dir / "daily.csv", parse_dates=["day"])
    except OSError as e:
        raise SeedError(f"demo data not found in {demo_dir}; run `make synth` first") from e
    if meta.get("is_synthetic") is not True or not bool(daily["is_synthetic"].all()):
        raise SeedError("demo data is not labelled is_synthetic=true; refusing to load it")
    if meta.get("config_sha256") != hashlib.sha256(raw).hexdigest():
        raise SeedError("demo data was generated from a different config.yaml; run `make synth` again")
    return cfg, daily


def stock_moves(spec: dict, n_days: int, k: int) -> list[tuple[int, float, str]]:
    """(day offset, signed quantity, kind) for one demo item. Deterministic; a sale never exceeds what is on hand."""
    daily, pattern = float(spec["daily_units"]), spec["pattern"]
    out, on_hand = [(0, OPENING_COVER * daily, "purchase")], OPENING_COVER * daily
    for i in range(n_days):
        if i and i % RESTOCK_EVERY == 0 and pattern != "dead" and not (pattern == "low" and i > n_days - 10):
            out.append((i, RESTOCK_EVERY * daily, "purchase"))
            on_hand += RESTOCK_EVERY * daily
        if pattern == "dead" and i >= 21:
            continue
        wanted = float(i % 2 == 0) if pattern == "dead" else float(round(daily * FACTORS[(i * 7 + k * 3) % 5]))
        sold = min(on_hand, wanted)                 # a dead item sells 1 unit every other day, then stops
        if sold > 0:
            out.append((i, -sold, "sale"))
            on_hand -= sold
    return out


def _seed_shop(db: Session, dm: dict, cfg: dict, daily: pd.DataFrame, today: date, model: tuple) -> dict:
    rules = get_rules()
    src_launch = date.fromisoformat(dm["launch_date"])
    launch = today - timedelta(days=DAYS_LOGGED)
    shift = launch - src_launch

    user = User(phone=dm["phone"], language="hi")
    db.add(user)
    db.commit()
    consent.give(db, user.id, consent.SHOP_DATA)       # the demo owner is fictional; the seed gives the consent

    shop = Shop(user_id=user.id, shop_type="kirana", name=dm["name"], size_sqft=float(dm["size_sqft"]),
                city_tier=int(dm["city_tier"]), lat=float(dm["lat"]), lon=float(dm["lon"]), budget=float(dm["budget"]),
                monthly_rent=float(dm["monthly_rent"]), staff_count=int(dm["staff_count"]), launch_date=launch,
                is_demo=True, opening_cash=float(dm["opening_cash"]))
    db.add(shop)
    db.commit()

    # set-up forecast, made the same way as POST /forecast, with the demo's mock map counts
    loc = osm.location_counts(db, shop.lat, shop.lon, mode="mock")
    out = fc.setup_forecast(
        shop={"size_sqft": shop.size_sqft, "city_tier": shop.city_tier, "monthly_rent": shop.monthly_rent,
              "staff_count": shop.staff_count, "budget": shop.budget},
        counts=loc.counts, location_source=loc.source, open_date=launch, model=model[0], card=model[1],
        assumptions=rules.forecast, split_rule=rules.investment)
    db.add(Forecast(shop_id=shop.id, kind="setup", made_on=launch, drivers=out["drivers"], horizon_months=[
        {"k": m["k"], "start": m["start"].isoformat(), "end": m["end"].isoformat(), "p10": m["p10"], "p50": m["p50"],
         "p90": m["p90"]} for m in out["months"]]))

    rows = daily[daily["shop_id"] == dm["shop_id"]]
    n_logs = 0
    for r in rows.itertuples(index=False):
        day = r.day.date() + shift
        if day < today:
            db.add(DailyLog(shop_id=shop.id, day=day, category=r.category, sales=float(r.sales),
                            purchases=float(r.purchases), expenses=0.0))
            n_logs += 1
    fixed = float(dm["monthly_rent"]) + int(dm["staff_count"]) * float(dm["staff_wage"])
    for n in range(4):                                  # rent and wages on the launch day of every month
        if (day := add_months(launch, n)) < today:
            db.add(DailyLog(shop_id=shop.id, day=day, category=EXPENSE_CATEGORY, sales=0.0, purchases=0.0,
                            expenses=fixed))

    ln = dm["loan"]                                     # EMI falls on the launch day of every month (DEC-71)
    db.add(Loan(shop_id=shop.id, principal=float(ln["principal"]), emi=float(ln["emi"]), due_day=launch.day,
                start_date=launch, tenure_months=int(ln["tenure_months"])))

    for k, spec in enumerate(cfg["demo_stock"]):
        item = StockItem(shop_id=shop.id, name=spec["name"], category=spec["category"], unit=spec["unit"],
                         cost=float(spec["cost"]), price=float(spec["price"]))
        db.add(item)
        db.flush()
        for offset, qty, kind in stock_moves(spec, DAYS_LOGGED, k):
            db.add(StockMove(item_id=item.id, day=launch + timedelta(days=offset), qty=qty, kind=kind))
    db.commit()

    raised = 0
    for i in range(1, DAYS_LOGGED + 1):                 # replay: what the daily job would have found each day
        day = launch + timedelta(days=i)
        review_job.run(db, shop, day)                   # nothing is due before launch + 90
        raised += alert_service.refresh(db, shop, day)["raised"]
    return {"shop_id": shop.id, "name": shop.name, "phone": user.phone, "launch_date": launch, "log_rows": n_logs,
            "alerts_raised": raised, "first_review_due": launch + timedelta(days=rules.review.window_days),
            "source_shop": dm["shop_id"]}


def seed(db: Session, today: date, *, config: Path = CONFIG, demo_dir: Path = DEMO_DIR,
         model: tuple | None = None) -> dict:
    """Delete the demo users, then write them again as of `today`."""
    cfg, daily = load_demo(config, demo_dir)
    if model is None:
        try:
            model = fc.load_model()
        except fc.ModelNotReady as e:
            raise SeedError("forecast model not found; run `make train` first") from e
    for dm in cfg["demos"]:
        old = db.scalars(select(User).where(User.phone == dm["phone"])).first()
        if old is not None:
            db.delete(old)
    db.commit()
    return {"is_synthetic": True, "is_demo": True, "today": today,
            "shops": [_seed_shop(db, dm, cfg, daily, today, model) for dm in cfg["demos"]]}


def demo_present(db: Session, config: Path = CONFIG) -> bool:
    """True when every demo login already exists (used by `--if-missing`, so a restart keeps the demo state)."""
    phones = [dm["phone"] for dm in yaml.safe_load(config.read_text(encoding="utf-8"))["demos"]]
    found = db.scalars(select(User.phone).where(User.phone.in_(phones))).all()
    return len(set(found)) == len(phones)


def main(argv: list[str] | None = None) -> None:
    import argparse

    from app.db import SessionLocal
    ap = argparse.ArgumentParser(description="Load the two SYNTHETIC demo shops (replaces them if present).")
    ap.add_argument("--if-missing", action="store_true", help="do nothing when the demo shops already exist")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    with SessionLocal() as db:
        if args.if_missing and demo_present(db):
            print("[SYNTHETIC DEMO DATA] demo shops already present; not reseeded (run `make seed` to reset them)")
            return
        try:
            out = seed(db, clock.today())
        except SeedError as e:
            raise SystemExit(f"seed failed: {e}") from e
    print(f"[SYNTHETIC DEMO DATA] seeded as of {out['today']} (dates shifted to today; not real shops)")
    for s in out["shops"]:
        print(f"  {s['name']}: login phone {s['phone']} (mock OTP), shop id {s['shop_id']}, launched "
              f"{s['launch_date']}, {s['log_rows']} log rows, {s['alerts_raised']} alerts raised in the replay, "
              f"first review due {s['first_review_due']}")


if __name__ == "__main__":
    main()
