# CHANGELOG

Newest first. Format: date, checkpoint IDs, what changed, notes for the next person.

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
