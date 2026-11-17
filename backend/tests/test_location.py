"""M-02: ML1 location score and starter product mix (ML_PLAN section 3). Hand-made scenarios on the real rule files.

The expected values are worked out by hand from data/rules/location_weights.yaml and product_mix.yaml (themselves
assumptions, DEC-21); if those files change, these numbers change with them.
"""
import pytest

from app.ml import location as ml1
from app.rules import get_rules
from tests.conftest import SHOP, login

W, MIX = get_rules().location, get_rules().product_mix
EMPTY = {"competitors": 0, "residential": 0, "schools": 0, "transit": 0, "banks_atms": 0}
DEFAULT_MOCK = {"competitors": 4, "residential": 120, "schools": 2, "transit": 4, "banks_atms": 2}


def s(**kw):
    return ml1.score({**EMPTY, **kw}, W)


def test_empty_area_scores_zero_with_no_drivers():
    out = s()
    assert out["score"] == 0 and out["positive_drivers"] == [] and out["negative_drivers"] == []


def test_everything_at_its_cap_and_few_competitors_scores_100():
    assert s(residential=300, schools=5, transit=10, banks_atms=5, competitors=2)["score"] == 100
    assert s(residential=9000, schools=50, transit=99, banks_atms=40)["score"] == 100        # caps saturate


def test_the_default_mock_area_by_hand():
    # 0.40*120/300 + 0.20*2/5 + 0.25*4/10 + 0.15*2/5 - 0.30*(4-2)/10 = 0.16+0.08+0.10+0.06-0.06 = 0.34
    out = ml1.score(DEFAULT_MOCK, W)
    assert out["score"] == 34 and out["raw"] == pytest.approx(0.34)
    assert [d["feature"] for d in out["positive_drivers"]] == ["residential", "transit", "schools"]   # top 3 only
    assert out["negative_drivers"] == [{"feature": "competitors", "count": 4, "points": -6.0, "direction": "down"}]


def test_a_few_competitors_are_neutral_many_saturate():
    base = s(residential=300)["score"]                                  # 40
    assert s(residential=300, competitors=2)["score"] == base           # free_count: demand signal, no penalty
    assert s(residential=300, competitors=7)["score"] == base - 15      # 5 extra of cap 10 -> half of 30 points
    assert s(residential=300, competitors=12)["score"] == base - 30
    assert s(residential=300, competitors=500)["score"] == base - 30    # saturates
    assert s(competitors=50)["score"] == 0                              # clipped at 0, never negative


def test_more_of_a_good_feature_never_lowers_the_score():
    scores = [s(schools=n, residential=100)["score"] for n in range(9)]
    assert scores == sorted(scores) and scores[-1] == scores[5]        # rises, then flat past the cap


def test_starter_mix_base_when_no_profile_applies():
    mix = ml1.starter_mix(EMPTY, MIX)
    assert {x["category"]: x["share"] for x in mix["lines"]} == dict(MIX.shop_types["kirana"].base)
    assert mix["profiles_applied"] == [] and mix["suggest_items"] == []


def test_starter_mix_near_schools_and_transit_by_hand():
    mix = ml1.starter_mix(DEFAULT_MOCK, MIX)
    assert [p["profile"] for p in mix["profiles_applied"]] == ["near_schools", "near_transit"]   # 120 < 150 homes
    assert [(x["category"], x["share"]) for x in mix["lines"]] == [
        ("staples", 0.35), ("snacks_beverages", 0.30), ("dairy", 0.15), ("household", 0.10), ("personal_care", 0.10)]
    assert "stationery" in mix["suggest_items"]                        # the school example of ML_PLAN section 3
    assert sum(x["share"] for x in mix["lines"]) == pytest.approx(1.0)


def test_starter_mix_all_profiles_still_sums_to_one_and_stays_non_negative():
    mix = ml1.starter_mix({**EMPTY, "schools": 9, "transit": 9, "residential": 999}, MIX)
    assert len(mix["profiles_applied"]) == 3
    assert sum(x["share"] for x in mix["lines"]) == pytest.approx(1.0) and all(x["share"] >= 0 for x in mix["lines"])


def test_endpoint_returns_score_drivers_mix_and_labels(client, consented):
    sid = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    r = client.get(f"/api/shops/{sid}/location-score", headers=consented)
    assert r.status_code == 200, r.text
    out = r.json()
    assert 0 <= out["score"] <= 100 and out["weights_are_assumptions"] and out["is_estimate"]
    assert out["starter_mix"]["is_assumption"] and out["weights_version"] == W.version
    assert out["location"]["source"] == "mock" and out["location"]["is_measured"] is False
    assert out["score"] == ml1.score(out["location"]["counts"], W)["score"]


def test_endpoint_owner_only_and_needs_consent(client, consented):
    sid = client.post("/api/shops", headers=consented, json=SHOP).json()["id"]
    other = login(client, "+919800000077")
    client.post("/api/consents", headers=other, json={"purpose": "shop_data"})       # consent is checked first
    assert client.get(f"/api/shops/{sid}/location-score", headers=other).status_code == 404
    assert client.get(f"/api/shops/{sid}/location-score").status_code == 401
    assert client.delete("/api/consents", params={"purpose": "shop_data"}, headers=consented).status_code == 200
    r = client.get(f"/api/shops/{sid}/location-score", headers=consented)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"
