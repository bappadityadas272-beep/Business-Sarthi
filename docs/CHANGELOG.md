# CHANGELOG

Newest first. Format: date, checkpoint IDs, what changed, notes for the next person.

## 2026-11-17: M-09 alert engine (ML6) with evaluation on injected dips

- **Checkpoint:** M-09 DONE. On synthetic test shops: recall 95.3% on injected dips of 35% or deeper within 14 days
  (632 dips), 0 false alarms in about 3,970 shop-months. Target **met on synthetic data**; see the honest notes in
  `docs/EVAL_REPORT.md`, section "ML6 alerts" (zero false alarms reflects the clean generator, not real shops).
- `backend/app/ml/alerts.py`: pure functions `sales_dip`, `low_stock`, `dead_stock`, `emi_due`, `data_gap`, `evaluate`.
  An alert is `{kind, severity, message_key, params}`; numbers travel only in `params`, never in text.
- `app/rules.py`: loading fails if `alert_rules.yaml` and `stock.yaml` disagree on the dead-stock day count.
- `eval/alert_eval.py` (`make eval-alerts`, about a minute) and `eval/alert_notes.md`.
- Tests: `tests/test_alerts.py` (17), thresholds tested exactly on the boundary.
- **Not done here:** the engine is not yet called from the API. Storing and resolving alerts is B-08, the daily job
  B-09. The EMI alert needs opening cash (M-08) and stays silent without it (DEC-62).
- **Next person:** DEC-63 lists details the assistant chose; the human has not yet confirmed them.

## 2026-11-17: M-07 stock advice (ML4) with simulation

- **Checkpoint:** M-07 DONE. Acceptance (hand-calculated cases) passes. ML4 target **met on synthetic shops only after
  DEC-59**; the first version missed the stock limit. See `docs/EVAL_REPORT.md`, section "ML4 stock advice".
- `backend/app/ml/reorder.py`: `ewm_mean`, `demand_stats`, `reorder_point`, `reorder_quantity`, `abc_tags`, `advise`
  (reorder list, dead stock, overstock, ABC, stock-out days). New items (under 14 days) use the category average.
- `GET /api/shops/{id}/stock/advice` (needs consent; computed on request, nothing stored). Returns the settings used and
  `is_estimate: true`.
- `data/rules/stock.yaml` (new, all assumptions) and the `Stock` model in `app/rules.py`; `get_rules().stock`.
- `eval/stock_eval.py` (`make eval-stock`, under a minute): rule against "reorder when empty", half-life 7 against 14
  chosen on the calibration shops, reported on test shops, plus the sensitivity to DEC-59.
- Tests: `tests/test_reorder.py` (17), all expected numbers worked out by hand in comments.
- **Honest findings:** the rule still ends about 4 item-days in 30 with an empty shelf (6% of demand lost) on synthetic
  shops; the baseline is a strawman; the app does not know what is on order.
- **Next person:** DEC-60 (and DEC-56) list details the assistant chose and the human has not yet confirmed.

## 2026-11-16: M-06 re-forecast (ML3) with rolling-origin backtest

- **Checkpoint:** M-06 DONE. Target (blend beats prior-only after 2 months) **met on synthetic shops**; see the honest
  notes in `docs/EVAL_REPORT.md`, section "ML3 re-forecast".
- `backend/app/ml/reforecast.py`: `prepare` (one ETS fit on daily totals, damped trend + weekly seasonality, level only
  below 28 logged days) and `combine` (blend weight w = n_days / (n_days + k), band, confidence). Missing days stay
  missing. Nothing after the origin is read. More than 30% of days missing gives confidence `low` with the reason.
- `POST /api/shops/{id}/reforecast`: uses the latest set-up forecast and logs up to yesterday (app clock); stores a
  `forecast` row with kind `reforecast`. Errors: 409 `setup_forecast_missing`, 422 `not_enough_days_logged`,
  422 `forecast_horizon_over`.
- `eval/reforecast_eval.py` (`make eval-reforecast`; slow, see the last bullet; `--reuse` rescoring takes seconds): blend vs prior
  only vs ETS only vs last-week naive at 1, 2 and 3 months of history, k chosen on training shops with out-of-fold
  priors, sensitivity to k, and 0/10/30/50% missing days.
- `eval/parts.py`: `docs/EVAL_REPORT.md` is now the ML2 text plus one part per later model (`eval/report_parts/`), so
  `make eval` no longer wipes the other sections.
- `data/rules/blend.yaml`: k 60 -> 10 and band multiplier 3.7 (DEC-55); new fields `min_days`, `damped_trend`,
  `error_rescale_min/max`, `interval_scale` (DEC-56).
- Tests: `tests/test_reforecast.py` (18: gaps at 0/10/30/50%, leakage, ordering, level-only, hand-checked spread, endpoint).
- **Honest findings:** the set-up forecast adds little once sales exist (ETS alone is nearly as good as the blend); the
  band needed a large multiplier and is hardly narrower than the set-up band; it is too wide when days are missing.
- **Next person:** the full backtest took about 12 minutes in one run and was stopped after 38 minutes in another on
  the same machine (12 workers, `OMP_NUM_THREADS=1`, set in the Makefile target); the cause of the difference was not
  found. The numbers in the report come from the completed run; the report was written from its cached cases with
  `--reuse` (`data/synthetic/out/reforecast_cases.joblib`, not in git). DEC-56 awaits the human's confirmation.

## 2026-11-16: B-05, B-06, B-07 daily logs, stock and assets, loans with EMI schedule

- **Checkpoints:** B-05, B-06, B-07 DONE.
- `POST /api/shops/{id}/logs` (bulk; same shop, day and category updates, never duplicates) and `GET .../logs?from&to`
  (both ends included, with per-day totals). A day never sent stays missing: it is not stored as zero.
- `GET/POST /api/shops/{id}/stock`, `POST .../stock/moves` (bulk, all or nothing), `GET/POST .../assets`. On-hand is never
  stored; it is always the sum of the moves.
- `GET/POST /api/shops/{id}/loans` with next due date, days to it, instalments left and the remaining schedule
  (`app/services/loans.py`). Migration `0004` adds `loan.start_date` and `loan.tenure_months` (DEC-53).
- Reads need ownership; writes need ownership and `shop_data` consent. All dates use the app clock (`services/clock.py`).
- Tests: `tests/test_records.py` (11, including hand-calculated due dates across month ends and a leap year).
- **Next person:** DEC-54 lists input defaults the assistant took without asking; the human still has to confirm them.

## 2026-11-16: M-05 set-up forecast service and endpoint

- **Checkpoint:** M-05 DONE.
- `POST /api/shops/{id}/forecast` (login, `shop_data` consent, own shop). Returns P10/P50/P90 revenue for 12 months with gross
  and operating profit, break-even revenue, payback range (fastest/typical/slowest), investment split (DEC-22, with
  `budget_too_low` and shortfall), up to 3 drivers (message key, params, English text), confidence with reason keys, the
  location counts and their source, and the assumptions used. Stores a `forecasts` row (`kind=setup`).
- New: `backend/app/ml/forecast.py` (pure functions), `backend/app/api/forecast.py`, `backend/app/schemas/forecast.py`,
  `backend/app/services/clock.py` (app clock, for the later advance-time endpoint), `data/rules/forecast_assumptions.yaml`.
- Decisions DEC-48 to DEC-52. Margin, wage and the payback extension are **assumptions**, labelled in the response.
- 503 `model_not_ready` if the ML2 files are missing (run `make train`); 503 `location_data_unavailable` if OSM and its
  fallback both fail.
- Tests: `tests/test_forecast.py` (15: hand-calculated payback, split, break-even; small trained model; endpoint). Suite 107 passed.
- **Next person:** with the default `OSM_MODE=mock` every forecast has confidence `low` by design. Tests share a
  session-scoped small model (`model_small` in `conftest.py`).

## 2026-11-16: M-01 OSM client with cache and mock answers

- `backend/app/services/osm.py`: `location_counts(db, lat, lon)` returns counts of competitors, homes, schools, transit and banks/ATMs within 500 m, with a `source` of `live`, `cache`, `mock` or `fallback_assumed` (only the first two are measured OSM data and carry the ODbL attribution). `search_place(query)` is the Nominatim search, throttled to one request per second. Every request sends the app User-Agent.
- New table `osm_cache` (migration `0003`), new rule file `data/rules/osm_tags.yaml` (validated by `app/rules.py`), new setting `OSM_MODE` (default `mock`), fixtures in `data/osm_mock/`. Decisions DEC-44 to DEC-47.
- `app/ml/train.py` now writes `feature_stats` (min, median, max of each shop-level input over the training shops) into the model card; the model itself is unchanged. **Run `make train` once** so the card has it.
- Tests: `tests/test_osm.py` (17), all against `httpx.MockTransport`; no test uses the network.
- **Not verified:** the live Overpass answer format for `out count;` (one `count` element per statement with `tags.total`) is written from the Overpass documentation as remembered. Two live test calls on 2026-11-16 were refused by the public server (at capacity), so live mode has **not** been run end to end. TODO: run one live query with `OSM_MODE=live` and confirm before relying on it; a wrong format degrades to `fallback_assumed`, not to wrong counts.
- No API endpoint yet: `location-score` is M-02 and the forecast (M-05) calls the client directly.

## 2026-11-16: B-03 profile and consent, B-04 shops

- Built and committed together because B-03's acceptance test ("shop creation refused (403) without consent") needs the B-04 endpoint.
- B-03: `PUT /api/me` (language `hi` or `en`), `GET/POST/DELETE /api/consents`, `GET /api/consents/history`; `app/services/consent.py` (DEC-43). New dependencies in `app/api/deps.py`: `ConsentedUser`, `OwnShop` (read: own shop or 404) and `OwnShopConsented` (write or compute: own shop and active consent). **Use `OwnShopConsented` for every later endpoint that stores or uses shop data.**
- B-04: `POST /api/shops`, `GET /api/shops`, `GET /api/shops/{id}`; `shop` gains `name`, `size_sqft`, `city_tier` (DEC-42, migration `0002`). Another owner's shop answers 404, the same as a missing one.
- API times are always UTC with an offset (`app/schemas/common.py: UtcDatetime`); SQLite returns naive datetimes, which a test caught.
- Tests: `tests/test_profile_consent.py` (7), `tests/test_shops.py` (6, including migration upgrade and downgrade). Shared fixtures `SHOP` and `consented` in `tests/conftest.py`.
- Next person: `GET /api/shops` and `GET /api/consents` are additions to the ARCHITECTURE section 8 list (now updated there).

## 2026-11-16: B-02 mock OTP login and JWT

- `backend/app/services/auth.py`: mock OTP store (DEC-40) and JWT helpers (DEC-41). `backend/app/api/auth.py`: `POST /api/auth/otp/request`, `POST /api/auth/otp/verify`. `backend/app/api/deps.py`: `CurrentUser` dependency (401 with a `code` when the token is missing, bad, expired or its user is gone). `GET /api/me` is the first protected route.
- Phone numbers are normalised (a bare 10-digit number is taken as +91). Errors carry stable codes (`otp_wrong`, `otp_expired`, `otp_not_requested`, `otp_too_many_tries`, `invalid_phone`) so the UI can localise them.
- Tests: `tests/test_auth.py` (10) and shared fixtures in `tests/conftest.py` (`client`, `login`, `auth_headers`; a fresh SQLite file per test).
- Next person: the OTP store is in memory, so it works with one server process only. No SMS is ever sent.

## 2026-11-16: M-04 conformal calibration and evaluation report

- `backend/app/ml/calibrate.py`: split conformal on actual / P50 using only the calibration shops, one ratio pair per forecast month, finite-sample ranks, pooling when a month has under 20 rows (DEC-38). Result is written into `model_card.json` under `calibration`; `predict_quantiles` now takes either band and `active_band(card)` picks the calibrated one. `make train` runs training then calibration.
- `eval/forecast_eval.py` (`make eval`): the only code that reads the test shops. Peer-median baseline (DEC-37), WAPE, pinball at 0.1 / 0.5 / 0.9, coverage overall and by month, city tier and size bucket, interval width, monotone probe. Writes `docs/EVAL_REPORT.md`; hand-written notes come from `eval/forecast_notes.md`.
- **First result was a miss:** with 200 shops (40 test) coverage was 94.0% against a 75% to 85% target. 30 random re-splits showed mean 80.0%, SD 7 points: too few shops to measure it. The human chose to grow the synthetic set to 1,000 shops (DEC-39; 600 / 200 / 200). No model setting, target or method changed. This history is in the report.
- Result on the 200 test shops (SYNTHETIC): WAPE 0.197 vs peer median 0.313 (37.0% lower, target 10%); coverage 80.5% (target 75% to 85%); pinball P10 / P50 / P90 7,407 / 21,067 / 10,631; 0 monotone breaks in 302,400 checks; band always ordered and positive. Leaf CV now picks 20.
- Honest caveats (in the report): tails are uneven (about 6% below P10, 14% above P90); small shops are over-covered (87.7%) while medium and large sit at 77%; month 1 is weakest.
- Tests: `tests/test_calibrate.py` (9). `tests/test_synthetic.py` generates 200 shops for speed and checks the config asks for 1,000.
- Next person: `make synth` now takes about a minute and writes about 180 MB (git-ignored). The public-data method check (D-02) is still open.

## 2026-11-16: M-03 ML2 training

- `backend/app/ml/features.py`: one row per shop x month k (k = 1-12, counted from the launch day), the DEC-33 features, monotone vector; shared by training, M-04 and M-05.
- `backend/app/ml/train.py` (`make train`, DEC-31): seeded 120/40/40 shop split (DEC-32), leaf size by shop-grouped 5-fold CV on training shops (DEC-36), LightGBM Huber P50 with monotone constraints and a ratio band (DEC-35). Writes `backend/data/models/ml2/ml2_p50.joblib`, `split.json`, `model_card.json` (git-ignored; data hash, generator version, params, CV scores, band ratios, metrics, `is_synthetic: true`). `predict_quantiles()` and `load()` are the API for M-04/M-05.
- Result (40 calibration shops, before conformal): leaf 60 chosen; r10 0.710, r90 1.423; WAPE 0.247; pinball P10/P50/P90 10,763 / 24,731 / 11,136; P10-P90 coverage 68.8% (M-04 must widen it to 75-85%).
- Path to this design: LightGBM quantile refuses monotone constraints; sklearn HistGB quantile accepted them but broke them in up to 9.7% of steps; 20-row leaves memorised single shops (lines crossed in 24-30% of new-shop rows). Now 0 rule breaks in 90,720 probe checks and the band never crosses.
- Make: `make` added to `backend/Dockerfile`; root `Makefile` with `synth`, `train`, `test`, `lint`. Two `make train` runs give the same model SHA-256, split and card. Tests: `tests/test_train.py` (5); full suite 42 passed.
- Next person: M-04 should re-set r10/r90 on the calibration shops and report on the test shops; the band is a fixed share of P50, so check coverage per month k too.

## 2026-11-16: D-01 review changes (generator v1.1)

- Human review of the 3 sample charts accepted D-01 with changes, all in `data/synthetic/config.yaml`:
  - Revenue floor INR 4,000 -> 2,000 a day: shops on the floor went from 31 (16%) to 1 (0.5%) (DEC-27).
  - Per-shop strength factor 0.9 to 1.1 for the weekday, ramp-up and festival effects, stored as `latent_var_*` columns; weekend/weekday now ranges about 1.14 to 1.19 across shops (DEC-28).
  - Festival uplift differs by category (`festival_category`); Diwali 2023 lift: household x2.04, snacks x1.93, dairy x1.83, personal care x1.70, staples x1.51 (DEC-29).
  - Second demo shop Sunita General Store (DEMO-002) meant for a "grow" review; `demo:` became `demos:` (a list) and `out/demo/` now holds 2 shops (DEC-30).
- Tests: 11 in `tests/test_synthetic.py` (floor share, variation range, category festival lift, Ramesh squeeze, Sunita grow conditions); full suite 37 passed.
- Next person: `revenue_vs_p50 >= 1.0` for Sunita can only be checked after M-02 exists; check it in D-05.

## 2026-11-16: D-01 synthetic data generator

- `data/synthetic/config.yaml` (all values are assumptions, DEC-23) and `data/synthetic/generate.py` with `--seed`, `--config`, `--out`, `--n-shops` and `--demo`.
- Output (git-ignored, DEC-26) in `data/synthetic/out/`: `shops.csv` (200 shops; columns prefixed `latent_` are generator internals, **never use them as model features**), `daily.csv` (730,820 rows: shop x day x 5 categories, sales and lumpy restock purchases), `labels.csv` (revenue months 1-3 and 1-12 for ML2), `metadata.json`. `--demo` adds `out/demo/` for Ramesh Kirana (DEC-25).
- Every CSV row has `is_synthetic=true`; `metadata.json` too (DEC-24). Same seed gives byte-identical files (checked by SHA-256).
- Measured: weekend/weekday about 1.17, month 1 about 0.65 of month 6 (ramp-up), Diwali day about 1.5x a normal day, purchases about 0.89 of sales, 24 shops with a shock. 31 of 200 shops hit the lower steady-revenue clip (INR 4,000/day).
- Tests `tests/test_synthetic.py` (7). Festival dates are from memory: `verified: false`.
- Next person: the demo profile gives DSCR about 0.3 in August, below 0 in the dip month and about 1.5 in October (Diwali build-up), so the review may read as "pivot". Tune in D-05 if needed.

## 2026-11-16: D-04 rule files and validated loader

- `data/rules/`: `review_rules.yaml`, `alert_rules.yaml`, `blend.yaml` (values from ML_PLAN sections 5 to 7), plus `actions.yaml`, `location_weights.yaml`, `product_mix.yaml`, `expansion.yaml` and a new `investment_split.yaml` (drafted values, approved, DEC-21 and DEC-22). Every file has `version`, `source` and `assumption: true`.
- `backend/app/rules.py`: strict Pydantic models (extra keys forbidden, weights must sum to 1, mix adjustments must net to 0, review table must end with the `hold` fallback, and so on). `load_rules()` / `get_rules()`; `python -m app.rules` prints a validation summary.
- Tests `tests/test_rules.py`: all files valid, plus 13 deliberately broken files that must be rejected with the file name.
- Next person: tune values only with a new DECISIONS row; the UI must label these numbers as assumptions.

## 2026-11-16: B-01 SQLAlchemy models and Alembic migration

- `app/db.py` (engine, session, `Base`; SQLite foreign keys switched on with a pragma) and `app/models/__init__.py` with all 13 tables from ARCHITECTURE section 7.
- Alembic set up in `backend/alembic/`; `env.py` reads `DATABASE_URL` from app settings (the `alembic.ini` URL is unused). First migration `0001`. Batch mode on for SQLite ALTERs.
- Constraints: unique `user.phone`; unique `(shop_id, day, category)` on `daily_log` (B-05 upsert relies on it); every child row cascades on delete (B-11 relies on it).
- Tests `tests/test_models.py`: `alembic upgrade head` creates every table, round trip, unique constraint, FK enforcement, cascade delete.
- Not included: the OSM cache table (added by M-01 in its own migration).
- Run: `docker compose run --rm backend alembic upgrade head`.

## 2026-11-16: S-02 backend skeleton

- `backend/pyproject.toml` with exact pins (DEC-19); FastAPI app `app/main.py`, settings loader `app/config.py` (reads repo-root `.env`, empty values fall back to defaults, `LLM_PROVIDER` defaults to `stub`), `GET /api/health`.
- Tests: `tests/test_health.py` (health, `/docs`, config defaults).
- **How to run:** `docker compose run --rm backend pytest` for tests; `docker compose up backend` serves http://localhost:8000/docs. In Git Bash, set `MSYS_NO_PATHCONV=1` first.
- Why Docker: Windows Smart App Control blocks numpy/pandas/SQLAlchemy/LightGBM DLLs on the dev machine (DEC-20, supersedes DEC-18). The image installs `libgomp1` for LightGBM.
- Ruff `EXE` rules are ignored because Windows bind mounts show every file as executable.
- Known harmless warning: Starlette deprecation about `httpx` in the test client (upstream).

## 2026-11-16: S-01 repo scaffold

- Moved `AGENTS.md` back to the repo root so `tools/build_master.py` works again (it was broken by the rename into `docs/`). DEC-16.
- Created the ARCHITECTURE section 9 folder tree (`backend/`, `frontend/`, `data/`, `eval/`) with `.gitkeep` placeholders.
- Added `.gitignore` (`.env`, `*.db`, `backend/data/models`, `node_modules`, `__pycache__`, `.venv`, plus `data/synthetic/out/` for generated data) and `.env.example` with empty values only.
- No `LICENSE` yet; waiting for team approval (DEC-17). Python and dependency decisions recorded as DEC-18 and DEC-19.

## 2026-11-16: documentation pack created (no checkpoint)

- Added `AGENTS.md`, `docs/SPEC.md`, `ARCHITECTURE.md`, `ML_PLAN.md`, `CHECKPOINTS.md`, `DECISIONS.md`, `CHANGELOG.md`, generated `MASTER.md`, and `tools/` scripts.
- Decisions DEC-01 to DEC-15 recorded.
- No application code exists. Start with checkpoint S-01.
- Open items for the team: choose a licence (S-01), choose the public dataset (D-02), pick the LLM provider and get an API key (C-01).

## History before the doc pack (context, not code)

- 2026-11: Screening deck (8 slides) submitted on Unstop for The Corporate Glitch '26. Finals on 21 Nov; demo optional.
- 2026-11: Public repository created with README, banner and vector-art assets.
