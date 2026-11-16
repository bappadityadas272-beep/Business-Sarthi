"""B-08: alerts store (dedupe, resolve, reminder, mute, cleared) and notifications."""
from datetime import timedelta

from app.models import DailyLog
from app.services import clock
from tests.conftest import SHOP, login


def _shop(client, headers) -> int:
    return client.post("/api/shops", headers=headers, json=SHOP).json()["id"]


def _log_sales(db_factory, shop_id: int, levels: list[tuple[int, int, float]]) -> None:
    """`levels`: (first days-ago, last days-ago, sales per day), both ends included."""
    with db_factory() as s:
        for far, near, sales in levels:
            for ago in range(near, far + 1):
                day = clock.today() - timedelta(days=ago)
                row = s.query(DailyLog).filter_by(shop_id=shop_id, day=day, category="all").first()
                if row is None:
                    row = DailyLog(shop_id=shop_id, day=day, category="all", purchases=0.0, expenses=0.0)
                    s.add(row)
                row.sales = sales + (ago % 3) * 10          # small spread, so the robust z is finite
        s.commit()


def _dip(db_factory, shop_id):                              # 28 normal days, then 7 days at half the sales
    _log_sales(db_factory, shop_id, [(35, 8, 1000.0), (7, 1, 500.0)])


def _recover(db_factory, shop_id):
    _log_sales(db_factory, shop_id, [(35, 1, 1000.0)])


def test_refresh_raises_once_and_notifies(client, consented, db_factory):
    shop_id = _shop(client, consented)
    url = f"/api/shops/{shop_id}/alerts"
    assert client.get(url, headers=consented).json() == []
    _dip(db_factory, shop_id)

    r = client.post(f"{url}/refresh", headers=consented)
    assert r.status_code == 200 and r.json()["raised"] == 1, r.text
    alerts = client.get(url, headers=consented).json()
    assert [a["kind"] for a in alerts] == ["sales_dip"]
    a = alerts[0]
    assert a["severity"] == "warn" and a["message_key"] == "alert.sales_dip" and a["still_active"] and not a["resolved"]
    assert a["params"]["ratio"] < 0.7 and a["raised_on"] == clock.today().isoformat() and a["rules_are_assumptions"]

    again = client.post(f"{url}/refresh", headers=consented).json()            # same problem: no second alert
    assert again["raised"] == 0 and again["refreshed"] == 1
    assert len(client.get(url, headers=consented, params={"status": "all"}).json()) == 1

    n = client.get("/api/notifications", headers=consented).json()
    assert n["unread"] == 1 and n["items"][0]["kind"] == "alert"
    assert n["items"][0]["payload"]["alert_id"] == a["id"] and n["items"][0]["payload"]["is_reminder"] is False


def test_resolved_alert_is_raised_again_unless_muted(client, consented, db_factory):
    shop_id = _shop(client, consented)
    url = f"/api/shops/{shop_id}/alerts"
    _dip(db_factory, shop_id)
    client.post(f"{url}/refresh", headers=consented)
    first = client.get(url, headers=consented).json()[0]

    r = client.post(f"{url}/{first['id']}/resolve", headers=consented)
    assert r.status_code == 200 and r.json()["resolved"] and r.json()["resolved_on"] == clock.today().isoformat()
    assert client.get(url, headers=consented).json() == []

    # the problem is still there: the owner is reminded with a NEW alert and a notification marked as a reminder
    assert client.post(f"{url}/refresh", headers=consented).json()["raised"] == 1
    second = client.get(url, headers=consented).json()[0]
    assert second["id"] != first["id"]
    notes = client.get("/api/notifications", headers=consented).json()
    assert notes["unread"] == 2 and notes["items"][0]["payload"]["is_reminder"] is True

    # resolve with mute: quiet while the same problem continues
    assert client.post(f"{url}/{second['id']}/resolve", headers=consented, json={"mute": True}).json()["muted"]
    quiet = client.post(f"{url}/refresh", headers=consented).json()
    assert quiet["raised"] == 0 and quiet["muted_quiet"] == 1
    assert client.get(url, headers=consented).json() == []
    assert client.get("/api/notifications", headers=consented).json()["unread"] == 2

    # the problem goes away, then comes back: that is a new alert, the mute has ended
    _recover(db_factory, shop_id)
    assert client.post(f"{url}/refresh", headers=consented).json()["cleared"] == 1
    _dip(db_factory, shop_id)
    assert client.post(f"{url}/refresh", headers=consented).json()["raised"] == 1
    third = client.get(url, headers=consented).json()[0]
    assert third["id"] not in (first["id"], second["id"]) and not third["muted"]


def test_alert_stays_open_after_the_problem_clears(client, consented, db_factory):
    shop_id = _shop(client, consented)
    url = f"/api/shops/{shop_id}/alerts"
    _dip(db_factory, shop_id)
    client.post(f"{url}/refresh", headers=consented)
    _recover(db_factory, shop_id)
    assert client.post(f"{url}/refresh", headers=consented).json() == {
        "as_of": clock.today().isoformat(), "raised": 0, "refreshed": 0, "muted_quiet": 0, "cleared": 1}
    a = client.get(url, headers=consented).json()[0]                           # still open: only the owner resolves
    assert not a["resolved"] and a["still_active"] is False and a["cleared_on"] == clock.today().isoformat()
    _dip(db_factory, shop_id)                                                  # back again while still open: same alert
    assert client.post(f"{url}/refresh", headers=consented).json()["refreshed"] == 1
    again = client.get(url, headers=consented).json()
    assert len(again) == 1 and again[0]["id"] == a["id"] and again[0]["still_active"]


def test_info_alert_creates_no_notification(client, consented, db_factory):
    shop_id = _shop(client, consented)
    _log_sales(db_factory, shop_id, [(40, 6, 1000.0)])                         # nothing logged for 5 finished days
    client.post(f"/api/shops/{shop_id}/alerts/refresh", headers=consented)
    alerts = client.get(f"/api/shops/{shop_id}/alerts", headers=consented).json()
    assert [(a["kind"], a["severity"]) for a in alerts] == [("data_gap", "info")]
    assert alerts[0]["params"]["days_without_log"] == 5
    assert client.get("/api/notifications", headers=consented).json() == {"unread": 0, "items": []}


def test_emi_alert_needs_opening_cash_and_orders_first(client, consented, db_factory):
    shop_id = _shop(client, consented)
    url = f"/api/shops/{shop_id}/alerts"
    _log_sales(db_factory, shop_id, [(40, 6, 1000.0)])
    due = clock.today() + timedelta(days=3)
    loan = {"principal": 100000, "emi": 5000000, "due_day": due.day, "tenure_months": 12,
            "start_date": (clock.today() - timedelta(days=1)).isoformat()}
    loan_id = client.post(f"/api/shops/{shop_id}/loans", headers=consented, json=loan).json()["id"]

    client.post(f"{url}/refresh", headers=consented)                            # cash unknown: no EMI alert (DEC-62)
    assert [a["kind"] for a in client.get(url, headers=consented).json()] == ["data_gap"]

    client.patch(f"/api/shops/{shop_id}", headers=consented, json={"opening_cash": 1000})
    assert client.post(f"{url}/refresh", headers=consented).json()["raised"] == 1
    alerts = client.get(url, headers=consented).json()
    assert [a["kind"] for a in alerts] == ["emi_due", "data_gap"]               # critical first
    p = alerts[0]["params"]
    assert p["loan_id"] == loan_id and p["due_date"] == due.isoformat() and p["days_to_due"] == 3
    assert p["cash_today"] == 1000 + sum(1000.0 + (ago % 3) * 10 for ago in range(6, 41))
    assert client.get("/api/notifications", headers=consented).json()["items"][0]["payload"]["severity"] == "critical"


def test_notifications_read_and_ownership(client, consented, db_factory):
    shop_id = _shop(client, consented)
    _dip(db_factory, shop_id)
    client.post(f"/api/shops/{shop_id}/alerts/refresh", headers=consented)
    alert_id = client.get(f"/api/shops/{shop_id}/alerts", headers=consented).json()[0]["id"]
    nid = client.get("/api/notifications", headers=consented).json()["items"][0]["id"]

    other = login(client, "+919800000002")
    assert client.get("/api/notifications", headers=other).json() == {"unread": 0, "items": []}
    assert client.post(f"/api/notifications/{nid}/read", headers=other).status_code == 404
    assert client.get(f"/api/shops/{shop_id}/alerts", headers=other).status_code in (403, 404)
    assert client.post(f"/api/shops/{shop_id}/alerts/{alert_id}/resolve", headers=other).status_code in (403, 404)
    assert client.post(f"/api/shops/{shop_id}/alerts/refresh", headers=other).status_code in (403, 404)
    assert client.get("/api/notifications").status_code == 401

    assert client.post(f"/api/notifications/{nid}/read", headers=consented).json()["read"] is True
    assert client.get("/api/notifications", headers=consented).json()["unread"] == 0
    assert client.get("/api/notifications", headers=consented, params={"unread_only": True}).json()["items"] == []
    assert client.post("/api/notifications/read-all", headers=consented).json() == {"marked_read": 0}
    assert client.post(f"/api/shops/{shop_id}/alerts/999/resolve", headers=consented).json()["detail"]["code"] == "alert_missing"
