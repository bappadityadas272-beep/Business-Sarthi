# CHANGELOG

Newest first. Format: date, checkpoint IDs, what changed, notes for the next person.

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
