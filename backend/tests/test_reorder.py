"""M-07 stock advice: every expected number below is worked out by hand in the comment beside it."""
import math
from datetime import timedelta

import pytest

from app.ml import reorder
from app.rules import get_rules
from app.services import clock
from tests.conftest import SHOP, login

RULE = get_rules().stock.model_copy(update={"demand_halflife_days": 7.0})      # tests do not depend on the tuned value
T = clock.today()


def item(i, category="staples", cost=10.0, price=12.0):
    return {"id": i, "name": f"item{i}", "category": category, "unit": "kg", "cost": cost, "price": price}


def opening(i, days_ago, qty):
    return {"item_id": i, "day": T - timedelta(days=days_ago), "qty": qty, "kind": "adjust"}


def sales(i, first_days_ago, last_days_ago, per_day):
    return [{"item_id": i, "day": T - timedelta(days=d), "qty": -per_day, "kind": "sale"}
            for d in range(first_days_ago, last_days_ago - 1, -1)]


def by_id(out):
    return {o["item_id"]: o for o in out["items"]}


def test_weighted_mean_by_hand():
    assert reorder.ewm_mean([0, 10], halflife=1) == pytest.approx(10 / 1.5)     # weights 0.5 and 1
    assert reorder.ewm_mean([4, 4, 4, 4], halflife=7) == pytest.approx(4)
    assert reorder.ewm_mean([], halflife=7) == 0.0
    # weights 0.25, 0.5, 1 on 8, 0, 2: (2 + 0 + 2) / 1.75
    assert reorder.ewm_mean([8, 0, 2], halflife=1) == pytest.approx(4 / 1.75)


def test_reorder_point_and_quantity_by_hand():
    # 10 x 2 + 1.28 x 2 x sqrt(2) = 20 + 3.6204
    assert reorder.reorder_point(10, 2, RULE) == pytest.approx(23.6204, abs=1e-4)
    assert reorder.reorder_point(10, 0, RULE) == 20
    assert reorder.reorder_point(10, 2, RULE, lead_time_days=4) == pytest.approx(40 + 1.28 * 2 * 2)
    assert reorder.reorder_quantity(10, 15, RULE) == 55                          # 7 x 10 - 15
    assert reorder.reorder_quantity(10, 80, RULE) == 0                           # never negative


def test_spread_uses_the_last_28_days():
    units = [100] * 10 + [8, 12] * 14                                            # the first 10 days must be ignored
    mean, std = reorder.demand_stats(units, RULE)
    assert std == pytest.approx(math.sqrt(28 * 4 / 27))                          # 2.0367
    weights = [0.5 ** ((len(units) - 1 - i) / 7) for i in range(len(units))]     # the mean uses every day, weighted
    assert mean == pytest.approx(sum(w * u for w, u in zip(weights, units, strict=True)) / sum(weights))
    assert 10 < mean < 20                                                        # the old 100s still count a little


def test_abc_tags_by_hand():
    rev = {i: float(110 - 10 * i) for i in range(1, 11)}                         # ten items: 100, 90, ... 10
    tags = reorder.abc_tags(rev, RULE)
    assert [tags[i] for i in range(1, 11)] == ["A", "A", "B", "B", "B", "C", "C", "C", "C", "C"]
    assert reorder.abc_tags({1: 5.0, 2: 9.0, 3: 1.0}, RULE) == {2: "A", 1: "B", 3: "C"}     # ceil(0.6) = 1, ceil(1.5) = 2
    assert reorder.abc_tags({1: 0.0, 2: 0.0}, RULE) == {1: "C", 2: "C"}          # nothing sold: never A
    assert reorder.abc_tags({7: 3.0}, RULE) == {7: "A"}
    assert reorder.abc_tags({1: 5.0, 2: 5.0, 3: 5.0, 4: 5.0, 5: 5.0}, RULE)[1] == "A"       # ties: lower id first


def shop():
    items = [item(1), item(2, "household", cost=90, price=100), item(3, "personal_care", cost=20, price=25),
             item(4, "dairy"), item(5, "household", cost=50, price=60), item(6, "snacks_beverages"), item(7), item(8)]
    moves = (
        [opening(1, 30, 400)] + sales(1, 30, 1, 10)        # sells 10 a day for 30 days: 100 left
        + [opening(2, 20, 40)] + sales(2, 20, 1, 2)        # sells 2 a day for 20 days: 0 left since yesterday
        + [opening(3, 45, 12)] + sales(3, 40, 40, 1)       # one sale 40 days ago: 11 left, dead
        + [opening(4, 20, 500)] + sales(4, 20, 1, 5)       # 400 left = 80 days of cover
        + [opening(5, 5, 30)] + sales(5, 5, 1, 3)          # 5 days old: new, uses the household average (item 2)
        + [opening(6, 5, 9)]                               # new, and alone in its category
        + [opening(7, 31, 6)]                              # never sold, on the shelf for 31 days: dead
        + [opening(8, 10, 6)]                              # never sold, only 10 days: not dead yet
    )
    return items, moves


def test_advice_matches_hand_calculation():
    out = reorder.advise(*shop(), T, RULE)
    it = by_id(out)

    a = it[1]
    assert (a["on_hand"], a["mean_daily_demand"], a["std_daily_demand"], a["reorder_point"]) == (100, 10, 0, 20)
    assert (a["reorder_qty"], a["reorder_now"], a["cover_days"], a["demand_source"]) == (0, False, 10, "own_sales")
    assert not a["dead_stock"] and not a["overstock"] and a["stockout_days"] == 0

    b = it[2]                                              # ROP = 2 x 2 = 4, on hand 0, quantity = 7 x 2 - 0 = 14
    assert (b["on_hand"], b["mean_daily_demand"], b["reorder_point"], b["reorder_qty"]) == (0, 2, 4, 14)
    assert b["reorder_now"] and b["stockout_days"] == 1 and b["days_since_last_sale"] == 1 and b["cover_days"] == 0

    c = it[3]
    assert c["dead_stock"] and not c["reorder_now"] and not c["overstock"]
    assert (c["on_hand"], c["stock_value"], c["days_since_last_sale"]) == (11, 220, 40)

    d = it[4]                                              # 400 on hand > 21 x 5 = 105
    assert d["overstock"] and not d["dead_stock"] and d["cover_days"] == 80 and not d["reorder_now"]

    e = it[5]                                              # household average = item 2: mean 2, spread 0
    assert (e["demand_source"], e["mean_daily_demand"], e["reorder_point"], e["on_hand"]) == ("category_average", 2, 4, 15)
    assert e["cover_days"] == 7.5 and not e["reorder_now"] and e["history_days"] == 5

    f = it[6]
    assert f["demand_source"] == "none" and f["mean_daily_demand"] is None and f["reorder_point"] is None
    assert f["reorder_qty"] is None and not f["reorder_now"] and not f["dead_stock"] and not f["overstock"]

    assert it[7]["dead_stock"] and it[7]["days_since_last_sale"] is None and it[7]["mean_daily_demand"] == 0

    g = it[8]                                              # new: staples average of items 1 and 7 = (10 + 0) / 2
    assert (g["demand_source"], g["mean_daily_demand"], g["reorder_point"]) == ("category_average", 5, 10)
    assert not g["dead_stock"] and g["reorder_now"] and g["reorder_qty"] == 29               # 7 x 5 - 6

    assert out["reorder_list"] == [2, 8]                   # the A item first, then the C item
    assert out["dead_stock_value"] == 220 + 60             # 11 x 20 + 6 x 10
    assert out["overstock_value"] == 4000                  # 400 x 10
    assert out["stockout_days"] == 1 and out["window_days"] == 90 and out["as_of"] == T
    # revenue: item 1 = 300 x 12 = 3600, item 4 = 100 x 12 = 1200, item 2 = 40 x 100 = 4000, item 5 = 15 x 60 = 900,
    # item 3 = 25; eight items -> A: ceil(1.6) = 2 (items 2, 1), B: up to ceil(4) = 4 (items 4, 5), rest C
    assert {i: it[i]["abc"] for i in it} == {2: "A", 1: "A", 4: "B", 5: "B", 3: "C", 6: "C", 7: "C", 8: "C"}


@pytest.mark.parametrize(("idle", "dead"), [(29, False), (30, True), (31, True)])
def test_dead_stock_threshold(idle, dead):
    out = reorder.advise([item(1)], [opening(1, 60, 50), *sales(1, 60, idle, 1)], T, RULE)
    assert by_id(out)[1]["dead_stock"] is dead


def test_overstock_only_above_21_days_of_cover():
    def run(open_qty):                                     # sells 2 a day for 28 days = 56 sold
        return by_id(reorder.advise([item(1)], [opening(1, 28, open_qty), *sales(1, 28, 1, 2)], T, RULE))[1]
    assert run(56 + 42)["cover_days"] == 21 and not run(56 + 42)["overstock"]    # exactly 21 days: not above
    assert run(56 + 43)["overstock"]


def test_reorder_when_on_hand_is_at_or_below_the_reorder_point():
    def run(open_qty):                                     # sells 5 a day for 28 days = 140 sold; ROP = 10
        return by_id(reorder.advise([item(1)], [opening(1, 28, open_qty), *sales(1, 28, 1, 5)], T, RULE))[1]
    at, above = run(150), run(151)
    assert at["reorder_point"] == 10 and at["reorder_now"] and at["reorder_qty"] == 25       # 7 x 5 - 10
    assert not above["reorder_now"] and above["reorder_qty"] == 24                # shown, but not due yet


def test_reorder_list_puts_a_items_first_then_least_cover():
    items = [item(i, price=p) for i, p in ((1, 10), (2, 10), (3, 10), (4, 10), (5, 1000))]
    moves = []
    for i, left in ((1, 3), (2, 1), (3, 2), (4, 0), (5, 4)):                     # each sells 5 a day for 28 days
        moves += [opening(i, 28, 140 + left), *sales(i, 28, 1, 5)]
    out = reorder.advise(items, moves, T, RULE)
    assert by_id(out)[5]["abc"] == "A"                                           # highest revenue by far
    # A = 1 item (5). B = ceil(2.5) - 1 = 2 items: equal revenue, so the lower ids 1 and 2. C = items 3 and 4.
    # Inside a class the item with the least cover comes first: B -> 2 (1 left), 1 (3 left); C -> 4 (0), 3 (2).
    assert out["reorder_list"] == [5, 2, 1, 4, 3]


def test_moves_after_today_are_ignored_and_todays_sales_do_not_move_demand():
    base = [opening(1, 28, 400), *sales(1, 28, 1, 10)]
    a = by_id(reorder.advise([item(1)], base, T, RULE))[1]
    later = {"item_id": 1, "day": T + timedelta(days=1), "qty": -100, "kind": "sale"}
    today = {"item_id": 1, "day": T, "qty": -50, "kind": "sale"}
    b = by_id(reorder.advise([item(1)], [*base, later, today], T, RULE))[1]
    assert b["mean_daily_demand"] == a["mean_daily_demand"] == 10                # today is not a finished day
    assert b["on_hand"] == a["on_hand"] - 50                                     # but on hand is current


def test_waste_reduces_stock_but_is_not_demand():
    waste = {"item_id": 1, "day": T - timedelta(days=2), "qty": -30, "kind": "waste"}
    out = by_id(reorder.advise([item(1)], [opening(1, 28, 400), *sales(1, 28, 1, 10), waste], T, RULE))[1]
    assert out["on_hand"] == 90 and out["mean_daily_demand"] == 10


def test_days_with_an_empty_shelf_do_not_pull_the_demand_estimate_down():
    # 100 in stock, sells 10 a day for 10 days (empty at the end of day 10), nothing to sell for 5 days,
    # then 300 arrive and it sells 10 a day for 13 days: 170 left. Counted days all show 10 a day.
    refill = {"item_id": 1, "day": T - timedelta(days=13), "qty": 300, "kind": "purchase"}
    moves = [opening(1, 28, 100), *sales(1, 28, 19, 10), refill, *sales(1, 13, 1, 10)]
    out = reorder.advise([item(1)], moves, T, RULE)
    a = by_id(out)[1]
    assert (a["on_hand"], a["mean_daily_demand"], a["std_daily_demand"], a["reorder_point"]) == (170, 10, 0, 20)
    assert a["stockout_days"] == 6 and out["stockout_days"] == 6                # days 10 to 15 ended at zero
    old = by_id(reorder.advise([item(1)], moves, T, RULE.model_copy(update={"ignore_empty_shelf_days": False})))[1]
    assert old["mean_daily_demand"] < 10 and old["std_daily_demand"] > 0         # the five empty days counted as zero


def test_empty_shop():
    out = reorder.advise([], [], T, RULE)
    assert out["items"] == [] and out["reorder_list"] == [] and out["stockout_days"] == 0


# ---------- endpoint ----------
@pytest.fixture
def shop_id(client, consented):
    return client.post("/api/shops", headers=consented, json=SHOP).json()["id"]


def test_endpoint_returns_reorder_list_and_dead_stock(client, consented, shop_id):
    t = clock.today()
    base = f"/api/shops/{shop_id}/stock"

    def add(name, category, qty, days_ago, cost=10, price=12):
        body = {"name": name, "category": category, "unit": "kg", "cost": cost, "price": price, "opening_qty": qty,
                "opening_day": str(t - timedelta(days=days_ago))}
        r = client.post(base, headers=consented, json=body)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    oil, soap = add("Oil", "household", 40, 20), add("Soap", "personal_care", 12, 45, cost=20, price=25)
    moves = [{"item_id": oil, "day": str(t - timedelta(days=d)), "qty": 2, "kind": "sale"} for d in range(20, 0, -1)]
    moves.append({"item_id": soap, "day": str(t - timedelta(days=40)), "qty": 1, "kind": "sale"})
    assert client.post(f"{base}/moves", headers=consented, json={"moves": moves}).status_code == 201

    r = client.get(f"{base}/advice", headers=consented)
    assert r.status_code == 200, r.text
    out = r.json()
    rows = {o["item_id"]: o for o in out["items"]}
    assert out["reorder_list"] == [oil] and rows[oil]["reorder_qty"] == 14 and rows[oil]["reorder_point"] == 4
    assert rows[soap]["dead_stock"] and out["dead_stock_value"] == 220
    assert out["is_estimate"] is True and out["as_of"] == str(t)
    assert out["settings"]["lead_time_days"] == 2 and out["settings"]["cover_days"] == 7 and out["settings"]["z"] == 1.28

    clock.advance(1)                                       # a day later with no new sale: 2 days at zero
    assert client.get(f"{base}/advice", headers=consented).json()["stockout_days"] == 2


def test_endpoint_needs_login_ownership_and_consent(client, consented, shop_id):
    url = f"/api/shops/{shop_id}/stock/advice"
    assert client.get(url).status_code == 401
    other = login(client, "+919800000002")
    assert client.get(url, headers=other).status_code == 403                   # no consent yet: nothing is computed
    client.post("/api/consents", headers=other, json={"purpose": "shop_data"})
    assert client.get(url, headers=other).status_code == 404                   # another owner cannot see this shop
    assert client.get(url, headers=consented).status_code == 200
