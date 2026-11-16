"""M-01: OSM client. No test touches the network: live mode runs against httpx.MockTransport."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.config import get_settings
from app.models import OsmCache
from app.rules import get_rules
from app.services import osm

PIN = (28.6321, 77.2194)
COUNTS = {"competitors": 3, "homes": 180, "schools": 2, "transit": 5, "banks_atms": 2}
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)


def overpass_json(counts=COUNTS):
    return {"version": 0.6, "elements": [{"type": "count", "id": 0, "tags": {"total": str(counts[k])}}
                                         for k in osm.FEATURES]}


class FakeOverpass:
    def __init__(self, response=None, status=200):
        self.calls, self.response, self.status = [], response or overpass_json(), status
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request):
        self.calls.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        if isinstance(self.response, str):
            return httpx.Response(self.status, text=self.response)
        return httpx.Response(self.status, json=self.response)


@pytest.fixture
def db(db_factory):
    with db_factory() as s:
        yield s


@pytest.fixture
def card_dir(tmp_path):
    stats = {k: {"min": 0, "median": m, "max": 99} for k, m in
             {"competitors": 4.0, "homes": 88.5, "schools": 1.0, "transit": 4.0, "banks_atms": 2.0}.items()}
    (tmp_path / "model_card.json").write_text(json.dumps({"feature_stats": stats}), encoding="utf-8")
    return tmp_path


def live(db, fake, pin=PIN, now=NOW, **kw):
    return osm.location_counts(db, *pin, mode="live", client=fake.client, now=now, **kw)


def test_pin_returns_counts_for_every_feature(db):
    fake = FakeOverpass()
    got = live(db, fake)
    assert got.counts == COUNTS and got.source == "live" and got.is_measured
    assert got.radius_m == 500 and got.cell == (28.632, 77.219) and got.fetched_at == NOW
    assert "OpenStreetMap" in got.attribution


def test_second_call_hits_cache(db):
    fake = FakeOverpass()
    live(db, fake)
    again = live(db, fake, now=NOW + timedelta(days=29))
    assert len(fake.calls) == 1
    assert again.source == "cache" and again.counts == COUNTS and again.fetched_at == NOW and again.is_measured


def test_user_agent_is_set_and_query_is_built_from_the_rules(db):
    fake = FakeOverpass()
    live(db, fake)
    req = fake.calls[0]
    assert req.headers["user-agent"] == get_settings().app_user_agent
    assert "BusinessSarthi" in req.headers["user-agent"]
    q = httpx.QueryParams(req.content.decode())["data"]
    assert q.count("out count;") == 5 and "around:500,28.632,77.219" in q          # centred on the cell
    assert '["shop"~"^(convenience|general|grocery|supermarket|kiosk)$"]' in q
    assert '["amenity"~"^(bank|atm)$"]' in q and '["highway"~"^(bus_stop)$"]' in q
    assert q.index('"shop"') < q.index('"building"') < q.index("school") < q.index("bus_stop") < q.index("bank")


def test_pins_in_the_same_cell_share_one_call_and_other_cells_do_not(db):
    fake = FakeOverpass()
    live(db, fake)
    assert live(db, fake, pin=(28.6324, 77.2191)).source == "cache"                  # same ~110 m cell
    assert live(db, fake, pin=(28.6400, 77.2194)).source == "live"
    assert len(fake.calls) == 2 and db.query(OsmCache).count() == 2


def test_cache_expires_after_30_days_and_is_refreshed(db):
    fake = FakeOverpass()
    live(db, fake)
    fake.response = overpass_json({**COUNTS, "competitors": 6})
    later = live(db, fake, now=NOW + timedelta(days=31))
    assert later.source == "live" and later.counts["competitors"] == 6 and len(fake.calls) == 2
    assert db.query(OsmCache).count() == 1                                          # row updated, not duplicated


@pytest.mark.parametrize("response,status", [
    (httpx.ConnectError("no network"), 200), ("busy", 504), ("<html>not json</html>", 200),
    ({"elements": []}, 200), ({"elements": [{"type": "count", "tags": {}}] * 5}, 200),
])
def test_failure_falls_back_to_labelled_typical_counts_and_is_not_cached(db, card_dir, response, status):
    got = live(db, FakeOverpass(response, status), model_dir=card_dir)
    assert got.source == "fallback_assumed" and not got.is_measured
    assert got.counts == {"competitors": 4, "homes": 88, "schools": 1, "transit": 4, "banks_atms": 2}
    assert got.fetched_at is None and got.attribution is None
    assert db.query(OsmCache).count() == 0


def test_failure_uses_fresh_cache_if_present_and_errors_without_a_model_card(db, tmp_path):
    live(db, FakeOverpass())
    assert live(db, FakeOverpass(httpx.ConnectError("down"))).source == "cache"
    with pytest.raises(osm.OsmError, match="make train"):
        live(db, FakeOverpass(httpx.ConnectError("down")), pin=(19.0, 72.8), model_dir=tmp_path)


def test_mock_mode_is_the_default_reads_fixtures_and_never_calls_or_caches(db, monkeypatch):
    assert get_settings().osm_mode == "mock"
    monkeypatch.setattr(osm, "_fetch_live", lambda *a: pytest.fail("network used in mock mode"))
    got = osm.location_counts(db, *PIN)
    assert got.source == "mock" and not got.is_measured and got.attribution is None
    assert set(got.counts) == set(osm.FEATURES) and all(isinstance(v, int) for v in got.counts.values())
    assert db.query(OsmCache).count() == 0


def test_mock_mode_prefers_a_pin_specific_fixture(db, tmp_path, monkeypatch):
    monkeypatch.setattr(osm, "MOCK_DIR", tmp_path)
    (tmp_path / "overpass_default.json").write_text(json.dumps(overpass_json({**COUNTS, "homes": 1})))
    (tmp_path / "overpass_28.632_77.219.json").write_text(json.dumps(overpass_json()))
    assert osm.location_counts(db, *PIN, mode="mock").counts["homes"] == 180
    assert osm.location_counts(db, 12.97, 77.59, mode="mock").counts["homes"] == 1


def test_mock_fixtures_are_labelled():
    for f in osm.MOCK_DIR.glob("*.json"):
        assert json.loads(f.read_text(encoding="utf-8"))["is_mock"] is True, f.name


def test_tag_rules_cover_every_feature():
    tags = get_rules().osm
    assert set(tags.features) == set(osm.FEATURES) and tags.cache_days == 30 and tags.cell_decimals == 3


def test_place_search_sets_user_agent_and_waits_one_second_between_calls(monkeypatch):
    calls, slept, t = [], [], [100.0]

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=[{"display_name": "Somewhere", "lat": "28.6", "lon": "77.2"}])

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(osm, "_last_nominatim", 0.0)
    kw = {"mode": "live", "client": client, "clock": lambda: t[0], "sleep": slept.append}
    assert osm.search_place("Connaught Place", **kw) == [
        {"display_name": "Somewhere", "lat": 28.6, "lon": 77.2, "source": "live"}]
    t[0] += 0.25
    osm.search_place("Karol Bagh", **kw)
    assert slept == [pytest.approx(0.75)]
    assert calls[0].headers["user-agent"] == get_settings().app_user_agent
    assert calls[0].url.path.endswith("/search") and calls[0].url.params["q"] == "Connaught Place"


def test_place_search_mock_and_failure():
    got = osm.search_place("anything", mode="mock")
    assert got and all(r["source"] == "mock" for r in got)
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(osm.OsmError):
        osm.search_place("x", mode="live", client=bad, clock=lambda: 1e9, sleep=lambda s: None)
