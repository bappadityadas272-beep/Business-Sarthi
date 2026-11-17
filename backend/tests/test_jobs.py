"""B-09: review due dates, the daily job, the scheduler and the demo advance-time endpoint."""
from datetime import date, timedelta

from app.api import dev as dev_api
from app.config import get_settings
from app.jobs import review_job, scheduler
from app.models import DailyLog, Forecast
from app.services import clock
from tests.conftest import SHOP


def test_due_dates():
    launch = date(2026, 1, 1)
    assert review_job.due_date(None, date(2026, 6, 1), 90) is None
    assert review_job.due_date(launch, launch + timedelta(days=89), 90) is None
    assert review_job.due_date(launch, launch + timedelta(days=90), 90) == launch + timedelta(days=90)
    assert review_job.due_date(launch, launch + timedelta(days=179), 90) == launch + timedelta(days=90)
    assert review_job.due_date(launch, launch + timedelta(days=180), 90) == launch + timedelta(days=180)
    assert review_job.next_due_date(launch, launch, 90) == launch + timedelta(days=90)
    assert review_job.next_due_date(launch, launch + timedelta(days=90), 90) == launch + timedelta(days=180)
    assert review_job.next_due_date(launch - timedelta(days=400), launch - timedelta(days=500), 90) == launch - timedelta(days=310)
    assert review_job.next_due_date(None, launch, 90) is None


def _open_shop(client, headers, db_factory, days_open: int, sales: float = 500.0) -> int:
    """A shop launched `days_open` days ago with a log for every day since and a set-up forecast of 1000 a day."""
    launch = clock.today() - timedelta(days=days_open)
    shop_id = client.post("/api/shops", headers=headers, json={**SHOP, "launch_date": launch.isoformat()}).json()["id"]
    with db_factory() as s:
        for i in range(days_open):
            s.add(DailyLog(shop_id=shop_id, day=launch + timedelta(days=i), category="all", sales=sales,
                           purchases=sales * 0.85, expenses=0.0))
        end = launch + timedelta(days=364)
        s.add(Forecast(shop_id=shop_id, kind="setup", made_on=launch, horizon_months=[
            {"k": 1, "start": launch.isoformat(), "end": end.isoformat(), "p10": 0, "p50": 365000, "p90": 0}]))
        s.commit()
    return shop_id


def test_advancing_90_days_triggers_a_review_and_stores_it(client, consented, db_factory):
    """The acceptance line of B-09."""
    shop_id = _open_shop(client, consented, db_factory, days_open=60)
    start = clock.today()
    assert client.get(f"/api/shops/{shop_id}/reviews/latest", headers=consented).status_code == 404

    r = client.post("/api/dev/advance-time", headers=consented, json={"days": 90})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["today"] == (start + timedelta(days=90)).isoformat() == client.get("/api/dev/clock").json()["today"]
    assert body["days_advanced"] == 90 and body["reviews_created"] == 1 and body["errors"] == 0

    review = client.get(f"/api/shops/{shop_id}/reviews/latest", headers=consented).json()
    due = start - timedelta(days=60) + timedelta(days=90)                       # launch + 90
    assert review["period_end"] == (due - timedelta(days=1)).isoformat() and review["created_on"] == due.isoformat()
    assert review["decision"] == "pivot"                                         # sales at half the forecast
    assert review["indicators"]["days_logged"] == 60 and review["confidence"] == "low"   # 60 of 90 days logged

    notes = client.get("/api/notifications", headers=consented).json()["items"]
    ready = [n for n in notes if n["kind"] == "review_ready"]
    assert len(ready) == 1 and ready[0]["payload"]["review_id"] == review["id"]
    assert ready[0]["payload"]["decision"] == "pivot"
    kinds = {a["kind"] for a in client.get(f"/api/shops/{shop_id}/alerts", headers=consented).json()}
    assert "data_gap" in kinds                                                   # nothing was logged while time passed

    # the same period is never reviewed twice
    assert scheduler.run_day(db_factory(), clock.today())["reviews_created"] == 0
    assert len(client.get(f"/api/shops/{shop_id}/reviews", headers=consented).json()) == 1


def test_daily_job_skips_shops_without_consent(client, consented, db_factory):
    shop_id = _open_shop(client, consented, db_factory, days_open=95)
    assert client.delete("/api/consents", headers=consented, params={"purpose": "shop_data"}).status_code == 200
    with db_factory() as db:
        out = scheduler.run_day(db, clock.today())
    assert out["shops"] == 0 and out["skipped_no_consent"] == 1 and out["reviews_created"] == 0
    assert client.get(f"/api/shops/{shop_id}/reviews", headers=consented).json() == []


def test_daily_job_runs_a_due_review_once(client, consented, db_factory):
    _open_shop(client, consented, db_factory, days_open=95)
    with db_factory() as db:
        first = scheduler.run_day(db, clock.today())
        second = scheduler.run_day(db, clock.today())
    assert first["shops"] == 1 and first["reviews_created"] == 1 and first["errors"] == 0
    assert second["reviews_created"] == 0 and second["alerts_raised"] == 0


def test_advance_time_is_refused_outside_dev_mode(client, consented, monkeypatch):
    assert client.post("/api/dev/advance-time", json={"days": 1}).status_code == 401
    assert client.post("/api/dev/advance-time", headers=consented, json={"days": 0}).status_code == 422
    assert client.post("/api/dev/advance-time", headers=consented, json={"days": 401}).status_code == 422
    off = get_settings().model_copy(update={"dev_mode": False})
    monkeypatch.setattr(dev_api, "get_settings", lambda: off)       # only the dev router sees DEV_MODE off
    before = clock.today()
    r = client.post("/api/dev/advance-time", headers=consented, json={"days": 5})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"       # DEC-91: looks like no route
    assert clock.today() == before


def test_scheduler_starts_only_when_enabled(monkeypatch):
    assert scheduler.start() is None                                             # the tests switch it off
    monkeypatch.setattr(get_settings(), "scheduler_enabled", True)
    try:
        s = scheduler.start()
        assert s is not None and s.running and s.get_job(scheduler.JOB_ID) is not None
        assert scheduler.start() is s                                            # second start: the same scheduler
    finally:
        scheduler.stop()
    assert scheduler._scheduler is None
