"""C-03: scheme matcher, GET /api/schemes/match and the chat answer. TEST ONLY KB fixture (made-up schemes)."""
from datetime import date
from pathlib import Path

import pytest

from app.config import get_settings
from app.models import Shop
from app.rag import index as ixmod
from app.rag.embed import HashEmbedder
from app.services import schemes as svc
from tests.conftest import SHOP, login
from tests.test_chat_api import ask

FIX = Path(__file__).parent / "fixtures" / "kb" / "schemes_test_only.json"
TODAY = date(2026, 11, 17)


@pytest.fixture(scope="module")
def ix():
    return ixmod.build(FIX, HashEmbedder())


@pytest.fixture
def kb_env(monkeypatch):
    """Point the app at the TEST ONLY KB with the fallback embedder."""
    monkeypatch.setenv("KB_PATH", FIX.as_posix())
    monkeypatch.setenv("KB_EMBEDDER", "fallback")
    monkeypatch.setenv("KB_INDEX_DIR", (Path(__file__).parent / "fixtures" / "kb" / "no_index").as_posix())
    get_settings.cache_clear()
    ixmod._current.clear()
    yield
    ixmod._current.clear()
    get_settings.cache_clear()


def shop(budget=300000.0, shop_type="kirana") -> Shop:
    return Shop(id=1, user_id=1, shop_type=shop_type, budget=budget, lat=0, lon=0, monthly_rent=0)


# C-03 acceptance: 20 profiles (TEST ONLY), the expected scheme must be in the top 3 in at least 80%.
PROFILES = [
    # (budget, profile, expected id)
    (300000, {"need": "loan for shop stock"}, "test-shop-loan"),
    (300000, {"need": "working capital loan"}, "test-shop-loan"),
    (500000, {"need": "दुकान के माल के लिए ऋण"}, "test-shop-loan"),
    (200000, {"need": "small loan without collateral", "age": 30}, "test-shop-loan"),
    (800000, {"categories": ["women"], "need": "subsidy for women entrepreneurs"}, "test-women-grant"),
    (800000, {"categories": ["women", "obc"], "age": 35, "need": "women business subsidy"}, "test-women-grant"),
    (1500000, {"categories": ["women"], "need": "महिला उद्यमी अनुदान"}, "test-women-grant"),
    (2000000, {"need": "credit guarantee without collateral"}, "test-credit-guarantee"),
    (5000000, {"need": "bank needs collateral security, guarantee cover"}, "test-credit-guarantee"),
    (3000000, {"need": "बिना जमानत गारंटी"}, "test-credit-guarantee"),
    (1500000, {"categories": ["sc"], "need": "loan for scheduled caste founder"}, "test-sc-st-startup"),
    (2500000, {"categories": ["st"], "age": 28, "need": "new enterprise loan"}, "test-sc-st-startup"),
    (1200000, {"categories": ["sc"], "need": "अनुसूचित जाति उद्यम ऋण"}, "test-sc-st-startup"),
    (300000, {"state": "Uttar Pradesh", "need": "UPI QR code for payments"}, "test-state-digital-kit"),
    (300000, {"state": "uttar pradesh", "need": "digital payments kit"}, "test-state-digital-kit"),
    (300000, {"state": "Uttar Pradesh", "need": "यूपीआई क्यूआर कोड"}, "test-state-digital-kit"),
    (300000, {"need": "business registration certificate"}, "test-udyam-registration"),
    (300000, {"need": "व्यवसाय पंजीकरण"}, "test-udyam-registration"),
    (300000, {}, "test-shop-loan"),                          # no question: ranked by "kirana shop"
    (20000000, {"need": "loan for my shop"}, "test-credit-guarantee"),   # above the shop loan limit
]


def test_twenty_profiles_top3(ix):
    hits, misses = 0, []
    for budget, profile, want in PROFILES:
        got = [s["id"] for s in svc.match(shop(budget), TODAY, profile, "en", ix=ix)["schemes"]]
        if want in got:
            hits += 1
        else:
            misses.append((profile, want, got))
    print(f"C-03 top-3 hit rate {hits}/{len(PROFILES)}; misses {misses}")
    assert hits / len(PROFILES) >= 0.8, misses


def ids(m):
    return [s["id"] for s in m["schemes"]] + [x["id"] for x in m["excluded"]]


def test_hard_filters_exclude(ix):
    def excluded(budget, profile):
        m = svc.match(shop(budget), TODAY, profile, "en", k=10, ix=ix)
        assert sorted(ids(m)) == sorted(s.id for s in ix.kb.schemes)       # every scheme is shown or excluded
        return {x["id"]: x["failed"] for x in m["excluded"]}

    assert excluded(300000, {"categories": ["general"]})["test-women-grant"] == ["category"]
    assert excluded(300000, {"age": 65})["test-women-grant"] == ["age"]
    assert excluded(300000, {"state": "Bihar"})["test-state-digital-kit"] == ["state"]
    assert excluded(2000000, {})["test-shop-loan"] == ["investment"]
    assert excluded(300000, {})["test-sc-st-startup"] == ["investment"]          # below its minimum
    salon = svc.match(shop(300000, "salon"), TODAY, {}, "en", k=10, ix=ix)      # shop type the code cannot map
    loan = next(s for s in salon["schemes"] if s["id"] == "test-shop-loan")
    assert loan["checks"]["sector"] == "unknown"
    assert "whether your type of business is covered" in loan["missing_requirements"]


def test_unknown_fields_go_to_missing(ix):
    m = svc.match(shop(800000), TODAY, {"need": "subsidy for women entrepreneurs"}, "en", ix=ix)
    w = next(s for s in m["schemes"] if s["id"] == "test-women-grant")
    assert w["checks"]["category"] == "unknown" and w["checks"]["age"] == "unknown"
    assert any("women" in x for x in w["missing_requirements"]) and any("18-60" in x for x in w["missing_requirements"])
    assert m["profile_stored"] is False


def test_result_fields_and_labels(ix):
    m = svc.match(shop(1500000), TODAY, {"categories": ["sc"], "need": "scheduled caste loan"}, "hi", ix=ix)
    s = next(s for s in m["schemes"] if s["id"] == "test-sc-st-startup")
    assert s["verified"] is False and s["label"] == "unverified" and "जाँचा" in s["label_text"]
    assert s["source_url"] == "https://example.org/test-only/sc-st-startup" and s["last_verified"] == "2026-01-01"
    assert s["why_it_may_fit"] and "आधिकारिक पेज" in m["notice"]
    assert m["kb"]["test_only"] is True and m["kb"]["embedder_is_fallback"] is True
    loan = svc.match(shop(), TODAY, {"need": "shop loan"}, "en", ix=ix)["schemes"][0]
    assert loan["label"] is None and loan["please_confirm"] == ["TEST ONLY: a bank account in the owner's name"]
    assert "₹3,00,000" in " ".join(loan["why_it_may_fit"])


def test_no_kb_gives_no_schemes(monkeypatch, tmp_path):
    monkeypatch.setenv("KB_PATH", (tmp_path / "missing.json").as_posix())
    get_settings.cache_clear()
    ixmod._current.clear()
    m = svc.match(shop(), TODAY, {}, "en")
    assert m["schemes"] == [] and m["note"] == "no_verified_source"
    bad = tmp_path / "bad.json"
    bad.write_text('{"version": 1, "schemes": [{"id": "x"}]}', encoding="utf-8")
    monkeypatch.setenv("KB_PATH", bad.as_posix())
    get_settings.cache_clear()
    assert svc.match(shop(), TODAY, {}, "en")["note"] == "kb_invalid"
    get_settings.cache_clear()
    ixmod._current.clear()


# ------------------------------------------------------------------ API and chat


def make_shop(client, h, **kw):
    r = client.post("/api/shops", headers=h, json={**SHOP, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_endpoint(client, consented, kb_env, db_factory):
    sid = make_shop(client, consented)
    r = client.get("/api/schemes/match", headers=consented,
                   params={"shop_id": sid, "state": "Uttar Pradesh", "category": ["women", "obc"], "age": 34,
                           "need": "UPI QR code kit", "language": "en"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schemes"][0]["id"] == "test-state-digital-kit" and body["decided_by_code"] and body["not_advice"]
    assert body["profile_used"] == {"state": "Uttar Pradesh", "categories": ["women", "obc"], "age": 34,
                                    "need": "UPI QR code kit"} and body["profile_stored"] is False
    assert all(s["source_url"] and s["last_verified"] for s in body["schemes"])
    with db_factory() as db:                                    # nothing from the request was saved
        from app.models import User
        u = db.query(User).one()
        assert "Uttar Pradesh" not in repr(vars(u))


def test_endpoint_access_and_validation(client, consented, kb_env):
    sid = make_shop(client, consented)
    assert client.get("/api/schemes/match", params={"shop_id": sid}).status_code == 401
    other = login(client, "+919800000099")
    assert client.post("/api/consents", headers=other, json={"purpose": "shop_data"}).status_code == 201
    assert client.get("/api/schemes/match", headers=other, params={"shop_id": sid}).status_code == 404
    assert client.get("/api/schemes/match", headers=consented,
                      params={"shop_id": sid, "category": "rich"}).status_code == 422
    assert client.get("/api/schemes/match", headers=consented, params={"shop_id": sid, "age": 7}).status_code == 422
    no_consent = login(client, "+919800000098")
    assert client.get("/api/schemes/match", headers=no_consent, params={"shop_id": sid}).status_code == 403


def test_endpoint_without_kb(client, consented, monkeypatch, tmp_path):
    monkeypatch.setenv("KB_PATH", (tmp_path / "none.json").as_posix())
    get_settings.cache_clear()
    ixmod._current.clear()
    sid = make_shop(client, consented)
    body = client.get("/api/schemes/match", headers=consented, params={"shop_id": sid}).json()
    assert body["schemes"] == [] and body["note"] == "no_verified_source"


@pytest.mark.parametrize(("question", "lang", "words"), [
    ("Dukaan ke maal ke liye loan ki koi yojana hai?", "hinglish", ["Official page", "TEST ONLY"]),
    ("दुकान के माल के लिए ऋण की कोई योजना है?", "hi", ["आधिकारिक पेज", "टेस्ट"]),
    ("Is there a scheme for a shop working capital loan?", "en", ["Official page", "not financial advice"]),
])
def test_chat_names_schemes_with_sources(client, consented, kb_env, question, lang, words):
    sid = make_shop(client, consented)
    r, ev = ask(client, consented, sid, question)
    assert r.status_code == 200, r.text
    assert ev["meta"] == {"language": lang, "intent": "schemes"} and ev["done"]["guard"] == "template"
    text = ev["text"]
    assert "[test-shop-loan]" in text and "https://example.org/test-only/shop-loan" in text
    assert all(w in text for w in words), text
    links = [link for s in ev["done"]["sources"] if s["tool"] == "match_schemes" for link in s.get("links", [])]
    assert {"id": "test-shop-loan", "url": "https://example.org/test-only/shop-loan",
            "last_verified": "2026-01-01", "verified": True} in links


def test_chat_without_kb_still_refuses_to_name(client, consented, monkeypatch, tmp_path):
    monkeypatch.setenv("KB_PATH", (tmp_path / "none.json").as_posix())
    get_settings.cache_clear()
    ixmod._current.clear()
    sid = make_shop(client, consented)
    _, ev = ask(client, consented, sid, "Koi sarkari yojana hai?")
    assert ev["meta"]["intent"] == "schemes" and "verified" in ev["text"] and "[" not in ev["text"]
