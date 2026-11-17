"""B-05 daily logs, B-06 stock, moves and assets, B-07 loans and EMI schedule."""
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.models import DailyLog, StockMove
from app.services import clock, loans
from tests.conftest import SHOP, login


@pytest.fixture
def shop_id(client, consented):
    return client.post("/api/shops", headers=consented, json=SHOP).json()["id"]


def entry(day, category="staples", sales=1000, purchases=0, expenses=0):
    return {"day": str(day), "category": category, "sales": sales, "purchases": purchases, "expenses": expenses}


# ---- B-05 ----
def test_same_shop_day_category_updates_instead_of_duplicating(client, consented, shop_id, db_factory):
    d = clock.today() - timedelta(days=3)
    url = f"/api/shops/{shop_id}/logs"
    r = client.post(url, headers=consented, json={"entries": [entry(d), entry(d, "dairy", 400)]})
    assert r.status_code == 200 and r.json() == {"created": 2, "updated": 0}
    r = client.post(url, headers=consented, json={"entries": [entry(d, sales=1500, expenses=50), entry(d, "snacks_beverages", 300)]})
    assert r.json() == {"created": 1, "updated": 1}
    # repeated inside one request: the last one wins, still one row
    r = client.post(url, headers=consented, json={"entries": [entry(d, "dairy", 1), entry(d, "dairy", 450)]})
    assert r.json() == {"created": 0, "updated": 1}
    with db_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyLog)) == 3
    out = client.get(url, headers=consented).json()
    assert {(e["category"], e["sales"]) for e in out["entries"]} == {("staples", 1500), ("dairy", 450), ("snacks_beverages", 300)}
    assert out["daily_totals"] == [{"day": str(d), "sales": 2250, "purchases": 0, "expenses": 50}]


def test_range_read_includes_both_ends_and_missing_days_stay_missing(client, consented, shop_id):
    t = clock.today()
    days = [t - timedelta(days=n) for n in (10, 9, 7, 5, 0)]            # days 8 and 6 are never logged
    url = f"/api/shops/{shop_id}/logs"
    client.post(url, headers=consented, json={"entries": [entry(d, sales=100 + i) for i, d in enumerate(days)]})
    out = client.get(url, headers=consented, params={"from": str(days[1]), "to": str(days[3])}).json()
    assert [e["day"] for e in out["entries"]] == [str(days[1]), str(days[2]), str(days[3])]
    assert out["days_logged"] == 3 and len(out["daily_totals"]) == 3
    assert len(client.get(url, headers=consented, params={"from": str(days[3])}).json()["entries"]) == 2
    assert len(client.get(url, headers=consented, params={"to": str(days[0])}).json()["entries"]) == 1
    assert client.get(url, headers=consented).json()["days_logged"] == 5
    r = client.get(url, headers=consented, params={"from": str(t), "to": str(days[0])})
    assert r.status_code == 422 and r.json()["error"]["code"] == "from_after_to"


def test_logs_reject_future_days_negative_values_and_unknown_categories(client, consented, shop_id):
    url, t = f"/api/shops/{shop_id}/logs", clock.today()
    r = client.post(url, headers=consented, json={"entries": [entry(t), entry(t + timedelta(days=1))]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "day_in_future"
    assert client.get(url, headers=consented).json()["entries"] == []       # nothing saved from a rejected request
    assert client.post(url, headers=consented, json={"entries": [entry(t, sales=-1)]}).status_code == 422
    assert client.post(url, headers=consented, json={"entries": [entry(t, "toys")]}).status_code == 422
    assert client.post(url, headers=consented, json={"entries": []}).status_code == 422


def test_logs_need_consent_to_write_and_ownership_to_read(client, consented, shop_id):
    url, t = f"/api/shops/{shop_id}/logs", clock.today()
    client.post(url, headers=consented, json={"entries": [entry(t)]})
    other = login(client, "+919800000002")
    assert client.get(url, headers=other).status_code == 404
    assert client.post(url, headers=other, json={"entries": [entry(t)]}).status_code == 403
    client.delete("/api/consents", headers=consented, params={"purpose": "shop_data"})
    assert client.post(url, headers=consented, json={"entries": [entry(t)]}).status_code == 403
    assert client.get(url).status_code == 401


# ---- B-06 ----
ITEM = {"name": "Toor dal 1 kg", "category": "staples", "unit": "pack", "cost": 120, "price": 135}


def test_on_hand_equals_the_sum_of_moves(client, consented, shop_id, db_factory):
    t = clock.today()
    base = f"/api/shops/{shop_id}/stock"
    item = client.post(base, headers=consented, json={**ITEM, "opening_qty": 20}).json()
    assert item["on_hand"] == 20 and item["stock_value"] == 2400
    empty = client.post(base, headers=consented, json={**ITEM, "name": "Salt 1 kg", "cost": 18, "price": 22}).json()
    assert empty["on_hand"] == 0
    moves = [{"item_id": item["id"], "day": str(t), "qty": q, "kind": k}
             for q, k in ((30, "purchase"), (12, "sale"), (2.5, "waste"), (-1, "adjust"), (4, "adjust"), (7, "sale"))]
    r = client.post(f"{base}/moves", headers=consented, json={"moves": moves})
    assert r.status_code == 201 and r.json()["saved"] == 6
    expected = 20 + 30 - 12 - 2.5 - 1 + 4 - 7                      # 31.5
    assert r.json()["items"][0]["on_hand"] == expected == 31.5
    listed = {i["id"]: i for i in client.get(base, headers=consented).json()}
    assert listed[item["id"]]["on_hand"] == 31.5 and listed[item["id"]]["stock_value"] == 31.5 * 120
    assert listed[empty["id"]]["on_hand"] == 0
    with db_factory() as db:
        assert db.scalar(select(func.sum(StockMove.qty)).where(StockMove.item_id == item["id"])) == 31.5
        assert db.scalar(select(func.count()).select_from(StockMove).where(StockMove.qty < 0)) == 4


def test_moves_are_all_or_nothing_and_checked(client, consented, shop_id):
    t = clock.today()
    base = f"/api/shops/{shop_id}/stock"
    item = client.post(base, headers=consented, json={**ITEM, "opening_qty": 5}).json()
    ok = {"item_id": item["id"], "day": str(t), "qty": 3, "kind": "purchase"}
    for bad, status, code in (({**ok, "item_id": 9999}, 404, "item_not_found"), ({**ok, "qty": -2, "kind": "sale"}, 422, "bad_quantity"),
                              ({**ok, "qty": 0}, 422, "bad_quantity"), ({**ok, "day": str(t + timedelta(days=1))}, 422, "day_in_future")):
        r = client.post(f"{base}/moves", headers=consented, json={"moves": [ok, bad]})
        assert r.status_code == status and r.json()["error"]["code"] == code
    assert client.post(f"{base}/moves", headers=consented, json={"moves": [{**ok, "kind": "gift"}]}).status_code == 422
    assert client.get(base, headers=consented).json()[0]["on_hand"] == 5     # none of the rejected batches was saved
    r = client.post(base, headers=consented, json={**ITEM, "name": "toor DAL 1 kg"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "item_exists" and r.json()["error"]["details"] == {"item_id": item["id"]}


def test_stock_and_assets_belong_to_one_owner(client, consented, shop_id):
    base = f"/api/shops/{shop_id}"
    item = client.post(f"{base}/stock", headers=consented, json=ITEM).json()
    a = client.post(f"{base}/assets", headers=consented, json={"name": "Deep freezer", "cost": 22000, "bought_on": "2026-08-02"})
    assert a.status_code == 201 and a.json()["cost"] == 22000
    assert [x["name"] for x in client.get(f"{base}/assets", headers=consented).json()] == ["Deep freezer"]
    other = login(client, "+919800000002")
    assert client.get(f"{base}/stock", headers=other).status_code == 404
    assert client.get(f"{base}/assets", headers=other).status_code == 404
    client.post("/api/consents", headers=other, json={"purpose": "shop_data"})
    theirs = client.post("/api/shops", headers=other, json=SHOP).json()["id"]
    move = {"item_id": item["id"], "day": str(clock.today()), "qty": 1, "kind": "sale"}
    r = client.post(f"/api/shops/{theirs}/stock/moves", headers=other, json={"moves": [move]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "item_not_found"     # an item of another shop
    assert client.get(f"/api/shops/{theirs}/stock", headers=other).json() == []


# ---- B-07 ----
def test_due_dates_across_month_ends_by_hand():
    assert loans.due_in_month(2027, 2, 31) == date(2027, 2, 28)
    assert loans.due_in_month(2028, 2, 30) == date(2028, 2, 29)            # leap year
    assert loans.due_in_month(2027, 4, 31) == date(2027, 4, 30)
    assert loans.schedule(date(2026, 11, 20), 31, 5) == [date(2026, 11, 30), date(2026, 12, 31), date(2027, 1, 31),
                                                          date(2027, 2, 28), date(2027, 3, 31)]
    # start on the due day: the first instalment is next month; December rolls into January
    assert loans.schedule(date(2026, 12, 5), 5, 3) == [date(2027, 1, 5), date(2027, 2, 5), date(2027, 3, 5)]
    assert loans.schedule(date(2026, 12, 4), 5, 2) == [date(2026, 12, 5), date(2027, 1, 5)]
    assert loans.schedule(date(2027, 1, 31), 31, 2) == [date(2027, 2, 28), date(2027, 3, 31)]


def test_next_due_and_instalments_left_by_hand():
    kw = {"start_date": date(2026, 8, 10), "due_day": 31, "tenure_months": 6, "emi": 4500.0}
    # schedule: 31 Aug, 30 Sep, 31 Oct, 30 Nov, 31 Dec, 31 Jan
    s = loans.status(today=date(2026, 11, 16), **kw)
    assert s["next_due_date"] == date(2026, 11, 30) and s["days_to_next_due"] == 14
    assert (s["instalments_due_so_far"], s["instalments_left"], s["last_due_date"]) == (3, 3, date(2027, 1, 31))
    assert s["schedule"] == [{"n": 4, "due_date": date(2026, 11, 30), "emi": 4500.0}, {"n": 5, "due_date": date(2026, 12, 31), "emi": 4500.0},
                             {"n": 6, "due_date": date(2027, 1, 31), "emi": 4500.0}]
    assert loans.status(today=date(2026, 11, 30), **kw)["days_to_next_due"] == 0            # due today is still due
    assert loans.status(today=date(2026, 12, 1), **kw)["next_due_date"] == date(2026, 12, 31)
    done = loans.status(today=date(2027, 2, 1), **kw)
    assert done["next_due_date"] is None and done["instalments_left"] == 0 and done["schedule"] == []
    old = loans.status(None, 5, None, 4500.0, date(2026, 11, 16))
    assert old["next_due_date"] is None and old["instalments_left"] is None


def test_loans_endpoint_follows_the_app_clock(client, consented, shop_id):
    url = f"/api/shops/{shop_id}/loans"
    start = clock.today()
    body = {"principal": 100000, "emi": 9000, "due_day": 31, "start_date": str(start), "tenure_months": 12}
    r = client.post(url, headers=consented, json=body)
    assert r.status_code == 201, r.text
    first = loans.schedule(start, 31, 12)
    assert r.json()["next_due_date"] == str(first[0]) and r.json()["instalments_left"] == 12 and len(r.json()["schedule"]) == 12
    clock.advance((first[0] - start).days + 1)                    # the day after the first instalment
    out = client.get(url, headers=consented).json()[0]
    assert out["next_due_date"] == str(first[1]) and out["instalments_left"] == 11 and out["instalments_due_so_far"] == 1
    for bad in ({**body, "due_day": 0}, {**body, "due_day": 32}, {**body, "tenure_months": 0}, {**body, "emi": 0},
                {k: v for k, v in body.items() if k != "start_date"}):
        assert client.post(url, headers=consented, json=bad).status_code == 422
    other = login(client, "+919800000002")
    assert client.get(url, headers=other).status_code == 404 and client.post(url, headers=other, json=body).status_code == 403
