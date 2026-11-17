"""OpenStreetMap client (M-01): nearby counts from Overpass with a 30-day cache, and Nominatim place search.

Modes (DEC-47): `mock` (default) answers from hand-made fixture files in data/osm_mock/ and never touches the
network; `live` calls the real services. If live Overpass fails and the cell is not cached, the counts fall back
to the median of the synthetic training shops, labelled `fallback_assumed` (DEC-45): never presented as measured.

Usage policies: every request carries the app User-Agent; one Overpass call per uncached cell; Nominatim is
throttled to one request per second and is never used in bulk.
"""
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, REPO_ROOT, get_settings
from app.models import OsmCache
from app.rules import OsmTags, get_rules

log = logging.getLogger("sarthi.osm")
MOCK_DIR = REPO_ROOT / "data" / "osm_mock"
MODEL_DIR = BACKEND_DIR / "data" / "models" / "ml2"
ATTRIBUTION = "Map data from OpenStreetMap contributors (ODbL)"
Feature = Literal["competitors", "homes", "schools", "transit", "banks_atms"]
FEATURES: tuple[Feature, ...] = ("competitors", "homes", "schools", "transit", "banks_atms")
Source = Literal["live", "cache", "mock", "fallback_assumed"]
NOMINATIM_MIN_GAP_S = 1.0
_last_nominatim = 0.0


class OsmError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocationCounts:
    counts: dict[str, int]
    source: Source
    radius_m: int
    cell: tuple[float, float]              # centre of the cache cell the query was run for
    fetched_at: datetime | None            # when the OSM answer was fetched; None for mock and fallback
    attribution: str | None                # required wherever OSM-derived data is shown

    @property
    def is_measured(self) -> bool:
        """True only for real OSM answers (fresh or cached)."""
        return self.source in ("live", "cache")


def cell_of(lat: float, lon: float, decimals: int) -> tuple[float, float]:
    return round(lat, decimals), round(lon, decimals)


def cell_key(cell: tuple[float, float], decimals: int) -> str:
    return f"{cell[0]:.{decimals}f},{cell[1]:.{decimals}f}"


def build_query(lat: float, lon: float, tags: OsmTags) -> str:
    """One Overpass QL query: for each feature (in FEATURES order) a union of tag filters, then `out count;`."""
    parts = ["[out:json][timeout:25];"]
    for name in FEATURES:
        filters = "".join(
            f'nwr(around:{tags.radius_m},{lat},{lon})["{f.key}"~"^({"|".join(f.values)})$"];'
            for f in tags.features[name]
        )
        parts.append(f"({filters});out count;")
    return "".join(parts)


def parse_counts(payload: dict) -> dict[str, int]:
    """Overpass answers `out count;` with one element of type `count` per statement, in query order."""
    totals = [e for e in payload.get("elements", []) if e.get("type") == "count"]
    if len(totals) != len(FEATURES):
        raise OsmError(f"expected {len(FEATURES)} count elements, got {len(totals)}")
    try:
        return {name: int(e["tags"]["total"]) for name, e in zip(FEATURES, totals, strict=True)}
    except (KeyError, TypeError, ValueError) as e:
        raise OsmError(f"malformed count element: {e}") from e


def _headers() -> dict[str, str]:
    return {"User-Agent": get_settings().app_user_agent}


def _fetch_live(query: str, client: httpx.Client | None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        r = client.post(get_settings().overpass_url, data={"data": query}, headers=_headers())
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise OsmError(f"Overpass request failed: {type(e).__name__}") from e
    finally:
        if own:
            client.close()


def _mock_payload(key: str) -> dict:
    """Fixture for this cell if one exists (demo shops), else the default fixture."""
    path = MOCK_DIR / f"overpass_{key.replace(',', '_')}.json"
    if not path.exists():
        path = MOCK_DIR / "overpass_default.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fallback_counts(model_dir: Path = MODEL_DIR) -> dict[str, int]:
    """Median counts of the synthetic training shops, from the ML2 model card (DEC-45)."""
    try:
        stats = json.loads((model_dir / "model_card.json").read_text(encoding="utf-8"))["feature_stats"]
        return {name: round(stats[name]["median"]) for name in FEATURES}
    except (OSError, KeyError, ValueError) as e:
        raise OsmError("no location data and no model card to fall back on; run `make train`") from e


def location_counts(db: Session, lat: float, lon: float, *, mode: Literal["mock", "live"] | None = None,
                    client: httpx.Client | None = None, now: datetime | None = None,
                    model_dir: Path = MODEL_DIR) -> LocationCounts:
    """Counts of competitors, homes, schools, transit and banks/ATMs around the pin."""
    tags = get_rules().osm
    mode = mode or get_settings().osm_mode
    now = now or datetime.now(UTC)
    cell = cell_of(lat, lon, tags.cell_decimals)
    key = cell_key(cell, tags.cell_decimals)

    if mode == "mock":
        return LocationCounts(parse_counts(_mock_payload(key)), "mock", tags.radius_m, cell, None, None)

    where = (OsmCache.cell == key, OsmCache.radius_m == tags.radius_m, OsmCache.tags_version == tags.version)
    row = db.scalars(select(OsmCache).where(*where)).first()
    if row is not None:
        fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=UTC)
        if now - fetched <= timedelta(days=tags.cache_days):
            return LocationCounts(dict(row.counts), "cache", tags.radius_m, cell, fetched, ATTRIBUTION)

    try:
        counts = parse_counts(_fetch_live(build_query(cell[0], cell[1], tags), client))
    except OsmError as e:
        log.warning("OSM unavailable for cell %s (%s); using assumed typical counts", key, e)
        return LocationCounts(fallback_counts(model_dir), "fallback_assumed", tags.radius_m, cell, None, None)

    if row is None:
        row = OsmCache(cell=key, radius_m=tags.radius_m, tags_version=tags.version)
        db.add(row)
    row.counts, row.fetched_at = counts, now
    db.commit()
    return LocationCounts(counts, "live", tags.radius_m, cell, now, ATTRIBUTION)


def search_place(query: str, *, mode: Literal["mock", "live"] | None = None, client: httpx.Client | None = None,
                 limit: int = 5, clock=time.monotonic, sleep=time.sleep) -> list[dict]:
    """Nominatim search for the pin picker: [{display_name, lat, lon, source}]. One request per second at most."""
    global _last_nominatim
    mode = mode or get_settings().osm_mode
    if mode == "mock":
        rows = json.loads((MOCK_DIR / "nominatim_search.json").read_text(encoding="utf-8"))["results"]
        return [{**r, "source": "mock"} for r in rows[:limit]]
    wait = NOMINATIM_MIN_GAP_S - (clock() - _last_nominatim)
    if wait > 0:
        sleep(wait)
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        r = client.get(f"{get_settings().nominatim_url}/search", headers=_headers(),
                       params={"q": query, "format": "jsonv2", "limit": limit, "countrycodes": "in"})
        r.raise_for_status()
        rows = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise OsmError(f"Nominatim request failed: {type(e).__name__}") from e
    finally:
        _last_nominatim = clock()
        if own:
            client.close()
    return [{"display_name": x["display_name"], "lat": float(x["lat"]), "lon": float(x["lon"]), "source": "live"}
            for x in rows]
