"""B-01: migration creates every table; models round-trip; constraints hold."""
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, make_engine
from app.models import EXPECTED_TABLES, Consent, DailyLog, Shop, StockItem, StockMove, User

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _shop(s: Session) -> Shop:
    u = User(phone="+919800000001", language="hi")
    s.add(u)
    s.flush()
    shop = Shop(user_id=u.id, lat=28.6, lon=77.2, budget=300000, monthly_rent=8000, staff_count=1)
    s.add(shop)
    s.flush()
    return shop


def test_alembic_upgrade_head_creates_all_tables(tmp_path):
    db = tmp_path / "mig.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db.as_posix()}"}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND,
                       env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    tables = set(inspect(make_engine(f"sqlite:///{db.as_posix()}")).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_models_match_expected_tables():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_roundtrip_shop_with_consent_and_logs(session):
    shop = _shop(session)
    session.add(Consent(user_id=shop.user_id, purpose="forecast"))
    session.add(DailyLog(shop_id=shop.id, day=date(2026, 1, 1), category="staples", sales=1200.0))
    session.commit()
    got = session.get(Shop, shop.id)
    assert got.user.consents[0].purpose == "forecast"
    assert got.daily_logs[0].sales == 1200.0


def test_daily_log_unique_per_shop_day_category(session):
    shop = _shop(session)
    session.add(DailyLog(shop_id=shop.id, day=date(2026, 1, 1), category="dairy", sales=1))
    session.add(DailyLog(shop_id=shop.id, day=date(2026, 1, 1), category="dairy", sales=2))
    with pytest.raises(IntegrityError):
        session.commit()


def test_foreign_keys_enforced(session):
    session.add(DailyLog(shop_id=999, day=date(2026, 1, 1), category="dairy"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_user_cascades_to_all_shop_rows(session):
    shop = _shop(session)
    item = StockItem(shop_id=shop.id, name="Atta 5kg", category="staples", unit="bag", cost=200, price=230)
    session.add(item)
    session.flush()
    session.add(StockMove(item_id=item.id, day=date(2026, 1, 1), qty=10, kind="purchase"))
    session.commit()
    session.delete(session.get(User, shop.user_id))
    session.commit()
    assert session.query(StockMove).count() == 0
    assert session.query(Shop).count() == 0
