# data/osm_mock

Hand-made **mock** answers for `OSM_MODE=mock` (the default, DEC-47). They are **not** OpenStreetMap data and do not
describe real places; the API labels anything built from them `source: "mock"` and the forecast confidence is `low`.

- `overpass_default.json`: used for any pin without its own file.
- `overpass_<lat>_<lon>.json` (cell rounded to 3 decimals, for example `overpass_28.610_77.210.json`): a pin-specific answer, used by the demo shops.
- `nominatim_search.json`: place-search answer.
