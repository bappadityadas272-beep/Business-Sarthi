"""M-11 pricing helper (ML10, DEC-89). Targets are the assumed midpoints in data/rules/pricing.yaml."""
from datetime import date, timedelta

import pytest

from app.ml import pricing as ml10
from app.rules import get_rules
from app.services import clock
from tests.conftest import SHOP, login

RULE = get_rules().pricing
TODAY = date(2026, 11, 17)


def test_targets_are_the_midpoints_of_the_assumed_ranges():
    assert RULE.assumption is True and RULE.window_days == 90
    assert RULE.target_margins == {"staples": 0.10, "dairy": 0.08, "snacks_beverages": 0.185, "household": 0.15,
                                   "personal_care": 0.175}


def test_hand_checked_category_margin_and_price_rise():
    items = [{"id": 1, "name": "Atta 5kg", "category": "staples", "cost": 95.0, "price": 100.0},
             {"id": 2, "name": "Rice 1kg", "category": "staples", "cost": 45.0, "price": 50.0},
             {"id": 3, "name": "Soap", "category": "personal_care", "cost": 30.0, "price": 40.0}]
    moves = [{"item_id": 1, "day": TODAY - timedelta(days=5), "qty": -10, "kind": "sale"},
             {"item_id": 2, "day": TODAY - timedelta(days=5), "qty": -20, "kind": "sale"},
             {"item_id": 1, "day": TODAY - timedelta(days=200), "qty": -999, "kind": "sale"},   # outside the window
             {"item_id": 1, "day": TODAY - timedelta(days=3), "qty": 50, "kind": "purchase"},
             {"item_id": 3, "day": TODAY - timedelta(days=2), "qty": -4, "kind": "sale"}]
    out = {c["category"]: c for c in ml10.analyse(items, moves, TODAY, RULE)}
    st = out["staples"]
    # revenue 10 x 100 + 20 x 50 = 2000; cost 950 + 900 = 1850; margin 7.5% < 10%
    assert st["margin"] == 0.075 and st["basis"] == "sales" and st["revenue"] == 2000 and st["below_target"]
    assert st["gap_points"] == 2.5
    assert st["price_rise_pct"] == pytest.approx(round((1850 / 0.9 / 2000 - 1) * 100, 1))   # 2.8%
    assert [i["name"] for i in st["items_below_target"]] == ["Atta 5kg"]      # Rice is exactly at 10%: not below
    assert st["items_below_target"][0]["target_price"] == round(95 / 0.9, 2)
    pc = out["personal_care"]                                    # 25% margin, target 17.5%
    assert not pc["below_target"] and pc["price_rise_pct"] == 0 and pc["items_below_target"] == []
    assert set(out) == {"staples", "personal_care"}             # no items: no row


def test_items_below_target_most_sold_first():
    items = [{"id": 1, "name": "Dal", "category": "staples", "cost": 96.0, "price": 100.0},
             {"id": 2, "name": "Sugar", "category": "staples", "cost": 47.0, "price": 50.0}]
    moves = [{"item_id": 1, "day": TODAY - timedelta(days=1), "qty": -2, "kind": "sale"},
             {"item_id": 2, "day": TODAY - timedelta(days=1), "qty": -9, "kind": "sale"}]
    st = ml10.analyse(items, moves, TODAY, RULE)[0]
    assert [i["name"] for i in st["items_below_target"]] == ["Sugar", "Dal"]
    assert [i["sold_qty"] for i in st["items_below_target"]] == [9, 2]


def test_category_without_sales_uses_list_prices():
    items = [{"id": 1, "name": "Milk", "category": "dairy", "cost": 50.0, "price": 52.0},
             {"id": 2, "name": "Curd", "category": "dairy", "cost": 40.0, "price": 50.0}]
    d = ml10.analyse(items, [], TODAY, RULE)[0]
    assert d["basis"] == "list_prices" and d["margin"] == round((2 / 52 + 10 / 50) / 2, 4) and not d["below_target"]
    assert [i["name"] for i in d["items_below_target"]] == ["Milk"]   # the category is fine, one item is not


def test_price_below_cost_is_flagged():
    items = [{"id": 1, "name": "Chips", "category": "snacks_beverages", "cost": 12.0, "price": 10.0}]
    s = ml10.analyse(items, [], TODAY, RULE)[0]
    assert s["below_target"] and s["margin"] == -0.2 and s["items_below_target"][0]["target_price"] == round(12 / 0.815, 2)


# ---- endpoint ----
def test_endpoint_flags_low_margin_categories(client, consented):
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    day = (clock.today() - timedelta(days=3)).isoformat()
    a = client.post(f"/api/shops/{shop_id}/stock", headers=consented, json={
        "name": "Atta 5kg", "category": "staples", "unit": "bag", "cost": 95, "price": 100, "opening_qty": 50,
        "opening_day": day}).json()["id"]
    b = client.post(f"/api/shops/{shop_id}/stock", headers=consented, json={
        "name": "Soap", "category": "personal_care", "unit": "pc", "cost": 30, "price": 40, "opening_qty": 50,
        "opening_day": day}).json()["id"]
    r = client.post(f"/api/shops/{shop_id}/stock/moves", headers=consented, json={"moves": [
        {"item_id": a, "day": day, "kind": "sale", "qty": 10}, {"item_id": b, "day": day, "kind": "sale", "qty": 5}]})
    assert r.status_code == 201, r.text
    out = client.get(f"/api/shops/{shop_id}/pricing", headers=consented).json()
    assert out["flagged"] == ["staples"] and out["targets_are_assumptions"] is True
    assert "pricing.demand_may_react" in out["notes"]
    st = next(c for c in out["categories"] if c["category"] == "staples")
    assert st["margin"] == 0.05 and st["revenue"] == 1000


def test_endpoint_access(client, consented):
    shop_id = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    assert client.get(f"/api/shops/{shop_id}/pricing").status_code == 401
    other = login(client, "+919800000002")
    assert client.get(f"/api/shops/{shop_id}/pricing", headers=other).status_code == 403
    client.post("/api/consents", headers=other, json={"purpose": "shop_data"})
    assert client.get(f"/api/shops/{shop_id}/pricing", headers=other).status_code == 404
    empty = client.get(f"/api/shops/{shop_id}/pricing", headers=consented).json()
    assert empty["categories"] == [] and empty["flagged"] == []
