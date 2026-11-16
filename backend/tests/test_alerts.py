"""M-09 alert engine: every expected number below is worked out by hand in the comment beside it."""
from datetime import date, timedelta

import pytest

from app.ml import alerts, reorder
from app.rules import get_rules

R = get_rules().alerts.rules
T = date(2026, 6, 1)
HALF = [90.0] * 14 + [110.0] * 14            # 28 base days: mean 100, median 100, MAD 10 -> sigma 14.826


def days(base, short, today=T):
    """Sales per day: `base` covers the 28 days before the last 7, `short` the last 7 days up to yesterday.
    None = no log that day."""
    vals = [*base, *short]
    out = {today - timedelta(days=len(vals) - i): v for i, v in enumerate(vals)}
    return {d: v for d, v in out.items() if v is not None}


def test_thresholds_are_the_documented_ones():
    assert (R.sales_dip.short_window_days, R.sales_dip.long_window_days) == (7, 28)
    assert (R.sales_dip.ratio_below, R.sales_dip.robust_z_below) == (0.70, -2.0)
    assert (R.emi_due.days_before_due, R.dead_stock.no_sale_days, R.data_gap.no_log_days) == (5, 30, 3)
    assert R.dead_stock.no_sale_days == get_rules().stock.dead_no_sale_days       # one number in two files


def test_robust_z_by_hand():
    import numpy as np
    assert alerts.robust_z(np.array([60.0] * 7), np.array(HALF)) == pytest.approx(-40 / 14.826)      # -2.698
    assert alerts.robust_z(np.array([100.0] * 7), np.array(HALF)) == 0
    assert alerts.robust_z(np.array([60.0]), np.array([100.0] * 28)) == float("-inf")               # no spread
    assert alerts.robust_z(np.array([100.0]), np.array([100.0] * 28)) == 0


def test_sales_dip_fires_with_hand_numbers():
    a = alerts.sales_dip(days(HALF, [60.0] * 7), T, R)
    assert (a["kind"], a["severity"], a["message_key"]) == ("sales_dip", "warn", "alert.sales_dip")
    p = a["params"]
    assert (p["ratio"], p["drop_percent"], p["short_avg"], p["base_avg"]) == (0.6, 40.0, 60.0, 100.0)
    assert p["robust_z"] == -2.7 and (p["short_days_logged"], p["base_days_logged"]) == (7, 28)


def test_ratio_exactly_on_the_threshold_is_not_a_dip():
    assert alerts.sales_dip(days(HALF, [70.0] * 7), T, R) is None                 # ratio 0.70 is not below 0.70; z -2.02
    assert alerts.sales_dip(days(HALF, [69.0] * 7), T, R) is not None             # ratio 0.69, z -2.09


def test_both_conditions_are_needed():
    assert alerts.is_dip({"ratio": 0.5, "z": -2.0}, R.sales_dip) is False         # z exactly -2 is not below -2
    assert alerts.is_dip({"ratio": 0.5, "z": -2.01}, R.sales_dip) is True
    assert alerts.is_dip({"ratio": 0.70, "z": -5.0}, R.sales_dip) is False
    assert alerts.is_dip(None, R.sales_dip) is False
    noisy = [40.0] * 14 + [160.0] * 14                                            # mean 100, MAD 60 -> z = -40/88.96 = -0.45
    assert alerts.sales_dip(days(noisy, [60.0] * 7), T, R) is None                # ratio 0.6 but within the usual spread
    # three zero days pull the average to 57 but the typical day (median 100) is unchanged: z = 0
    assert alerts.sales_dip(days(HALF, [100.0] * 4 + [0.0] * 3), T, R) is None


def test_flat_base_gives_a_dip_without_a_z_value():
    a = alerts.sales_dip(days([100.0] * 28, [60.0] * 7), T, R)
    assert a["params"]["robust_z"] is None and a["params"]["ratio"] == 0.6


def test_missing_days_are_not_zero_sales_and_too_few_days_means_no_alert():
    four = alerts.sales_dip(days(HALF, [None, None, None, 60.0, 60.0, 60.0, 60.0]), T, R)
    assert four["params"]["short_days_logged"] == 4 and four["params"]["short_avg"] == 60.0
    assert alerts.sales_dip(days(HALF, [None] * 4 + [60.0] * 3), T, R) is None    # 3 logged days: below MIN_SHORT
    base14 = [None] * 14 + [90.0] * 7 + [110.0] * 7
    assert alerts.sales_dip(days(base14, [60.0] * 7), T, R)["params"]["base_days_logged"] == 14
    base13 = [None] * 15 + [90.0] * 6 + [110.0] * 7
    assert alerts.sales_dip(days(base13, [60.0] * 7), T, R) is None               # below MIN_BASE
    assert alerts.sales_dip({}, T, R) is None


def test_today_is_not_used():
    d = days(HALF, [100.0] * 7)
    d[T] = 0.0                                                                    # today so far: nothing sold yet
    assert alerts.sales_dip(d, T, R) is None
    d = days(HALF, [60.0] * 7)
    d[T] = 500.0
    assert alerts.sales_dip(d, T, R)["params"]["short_avg"] == 60.0


def _item(i):
    return {"id": i, "name": f"item{i}", "category": "staples", "unit": "kg", "cost": 10.0, "price": 12.0}


def test_stock_alerts_from_real_advice():
    # item 1: 215 in, sells 10 a day for 20 days -> 15 left, reorder point 10 x 2 = 20 -> low.
    # item 2: 50 put on the shelf 40 days ago, never sold -> dead, value 50 x 10 = 500.
    moves = [{"item_id": 1, "day": T - timedelta(days=20), "qty": 215, "kind": "adjust"},
             *[{"item_id": 1, "day": T - timedelta(days=k), "qty": -10, "kind": "sale"} for k in range(20, 0, -1)],
             {"item_id": 2, "day": T - timedelta(days=40), "qty": 50, "kind": "adjust"}]
    advice = reorder.advise([_item(1), _item(2)], moves, T, get_rules().stock)
    low = alerts.low_stock(advice, R)
    assert low["params"] == {"count": 1, "items": [{"item_id": 1, "name": "item1"}]}
    assert (low["severity"], low["message_key"]) == ("warn", "alert.low_stock")
    dead = alerts.dead_stock(advice, R)
    assert dead["params"] == {"count": 1, "items": [{"item_id": 2, "name": "item2"}], "value": 500.0, "no_sale_days": 30}
    assert (dead["severity"], dead["message_key"]) == ("info", "alert.dead_stock")


def test_stock_alerts_list_at_most_five_items_and_none_when_nothing_is_wrong():
    items = [{"item_id": i, "name": f"n{i}", "dead_stock": True, "stock_value": 10.0 * i} for i in range(1, 8)]
    advice = {"items": items, "reorder_list": [7, 6, 5, 4, 3, 2, 1], "dead_stock_value": 280.0}
    low = alerts.low_stock(advice, R)["params"]
    assert low["count"] == 7 and [i["item_id"] for i in low["items"]] == [7, 6, 5, 4, 3]     # reorder-list order
    dead = alerts.dead_stock(advice, R)["params"]
    assert dead["count"] == 7 and [i["item_id"] for i in dead["items"]] == [7, 6, 5, 4, 3]   # largest value first
    empty = {"items": [], "reorder_list": [], "dead_stock_value": 0.0}
    assert alerts.low_stock(empty, R) is None and alerts.dead_stock(empty, R) is None


def flow(per_day, n=28):
    return {T - timedelta(days=k): per_day for k in range(1, n + 1)}


def loan(i, in_days, emi=5000.0):
    return {"loan_id": i, "emi": emi, "next_due_date": None if in_days is None else T + timedelta(days=in_days)}


def test_emi_alert_by_hand():
    # cash 4000 + 5 days x 100 = 4500 < 5000 -> alert, short by 500
    (a,) = alerts.emi_due([loan(1, 5)], 4000.0, flow(100.0), T, R)
    assert (a["severity"], a["message_key"]) == ("critical", "alert.emi_due")
    assert a["params"] == {"loan_id": 1, "emi": 5000.0, "due_date": "2026-06-06", "days_to_due": 5, "cash_today": 4000.0,
                           "projected_cash": 4500.0, "avg_daily_net_flow": 100.0, "shortfall": 500.0}
    assert alerts.emi_due([loan(1, 5)], 4500.0, flow(100.0), T, R) == []          # projected 5000 is not below 5000
    assert alerts.emi_due([loan(1, 6)], 0.0, flow(100.0), T, R) == []             # due in 6 days: outside the window
    assert alerts.emi_due([loan(1, None)], 0.0, flow(100.0), T, R) == []          # loan finished
    (b,) = alerts.emi_due([loan(1, 0)], 4999.0, flow(100.0), T, R)                # due today: no days of flow added
    assert b["params"]["projected_cash"] == 4999.0 and b["params"]["shortfall"] == 1.0
    (c,) = alerts.emi_due([loan(1, 5)], 5500.0, flow(-200.0), T, R)               # 5500 - 1000 = 4500
    assert c["params"]["projected_cash"] == 4500.0
    assert alerts.emi_due([loan(1, 5)], 5000.0, {}, T, R) == []                   # no logs: flow taken as zero


def test_emi_alert_never_guesses_when_cash_is_unknown():
    assert alerts.emi_due([loan(1, 1)], None, flow(-9999.0), T, R) == []


def test_two_instalments_are_added_up():
    # cash 4000, no flow. First 3000 is covered; the second needs 6000 in all -> short by 2000.
    out = alerts.emi_due([loan(2, 4, 3000.0), loan(1, 2, 3000.0)], 4000.0, {}, T, R)
    assert [(a["params"]["loan_id"], a["params"]["shortfall"]) for a in out] == [(2, 2000.0)]


def test_cash_flow_uses_only_the_last_28_finished_days():
    net = {**flow(100.0), T - timedelta(days=29): -99999.0, T: -99999.0}
    assert alerts.projected_cash(1000.0, net, T, 5) == (1500.0, 100.0)


def test_data_gap_by_hand():
    a = alerts.data_gap(T - timedelta(days=4), None, T, R)                        # missing: T-3, T-2, T-1
    assert a["params"] == {"days_without_log": 3, "last_log_day": "2026-05-28"}
    assert (a["severity"], a["message_key"]) == ("info", "alert.data_gap")
    assert alerts.data_gap(T - timedelta(days=3), None, T, R) is None             # 2 missing days
    assert alerts.data_gap(T, None, T, R) is None
    assert alerts.data_gap(None, T - timedelta(days=3), T, R)["params"] == {"days_without_log": 3, "last_log_day": None}
    assert alerts.data_gap(None, T - timedelta(days=2), T, R) is None
    assert alerts.data_gap(None, None, T, R) is None                              # no launch date: nothing to expect
    assert alerts.data_gap(None, T + timedelta(days=10), T, R) is None            # not launched yet


def _plain(value):
    """True when a parameter is a number, a date string, a name or a list of such: never a sentence."""
    if isinstance(value, list):
        return all(_plain(v) for v in value)
    if isinstance(value, dict):
        return all(_plain(v) for v in value.values())
    return value is None or isinstance(value, (int, float)) or (isinstance(value, str) and " " not in value)


def test_evaluate_orders_by_severity_and_carries_keys_not_sentences():
    sales = days(HALF, [60.0] * 4 + [None] * 3)                                   # dip, then 3 days without a log
    advice = {"items": [{"item_id": 1, "name": "atta", "dead_stock": True, "stock_value": 90.0}], "reorder_list": [1],
              "dead_stock_value": 90.0}
    out = alerts.evaluate(today=T, rules=R, sales_by_day=sales, net_by_day={}, advice=advice, loans=[loan(1, 2)],
                          cash=100.0, launch_date=T - timedelta(days=60))
    assert [a["kind"] for a in out] == ["emi_due", "sales_dip", "low_stock", "dead_stock", "data_gap"]
    assert [a["severity"] for a in out] == ["critical", "warn", "warn", "info", "info"]
    for a in out:
        assert set(a) == {"kind", "severity", "message_key", "params"}
        assert a["message_key"] == f"alert.{a['kind']}" and _plain(a["params"])


def test_evaluate_with_nothing_wrong_and_without_stock_records():
    out = alerts.evaluate(today=T, rules=R, sales_by_day=days(HALF, [100.0] * 7), net_by_day=flow(100.0), advice=None,
                          loans=[], cash=None, launch_date=T - timedelta(days=60))
    assert out == []
