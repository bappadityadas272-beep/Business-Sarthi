# DECISIONS: choices already made

> Rule: do not silently change a decision. Add a new row (next ID) that supersedes the old one and update the old row's status to `SUPERSEDED by DEC-xx`.

| ID | Date | Decision | Why | Alternatives rejected | Status |
|---|---|---|---|---|---|
| DEC-01 | 2026-11-16 | Doc pack: small docs plus one generated `MASTER.md` | Small files for focused work and evaluation; one file for a model with a single paste | One giant hand-edited file (drifts), small files only (no single handoff) | ACTIVE |
| DEC-02 | 2026-11-16 | Scope: all 8 pitch features in the prototype, built as vertical slices by priority (P0 first) | Team wants every feature shown; slices keep a working demo at each step | Hero feature only | ACTIVE |
| DEC-03 | 2026-11-16 | Stack: React + TypeScript + Vite + Tailwind; FastAPI; SQLite via SQLAlchemy | Team familiarity with the popular stack, strong ML ecosystem in Python, zero-setup database | Flask, Django, Node backend, PostgreSQL now | ACTIVE |
| DEC-04 | 2026-11-16 | Data: synthetic generator plus one licence-checked public dataset for method validation | No real shop data exists; being explicit avoids false accuracy claims | Scraping, buying data, fabricating "real" results | ACTIVE |
| DEC-05 | 2026-11-16 | Forecasts are quantile ranges (P10/P50/P90) with conformal calibration | Honest uncertainty; small-business decisions need a range | Point forecasts | ACTIVE |
| DEC-06 | 2026-11-16 | The LLM explains but never decides or invents numbers; a guard enforces it | Trust and safety for financial guidance | LLM-only advisor | ACTIVE |
| DEC-07 | 2026-11-16 | Review decisions come from a transparent rule table (`review_rules.yaml`) | No labelled outcomes exist; rules are auditable | Learned classifier | ACTIVE |
| DEC-08 | 2026-11-16 | Location score is a transparent weighted score over OSM features | Same reason as DEC-07 | Learned model on synthetic labels (circular) | ACTIVE |
| DEC-09 | 2026-11-16 | Embeddings: `intfloat/multilingual-e5-small`; vector store: NumPy or FAISS | Small, multilingual (Hindi and English), runs on CPU | Hosted embedding API (cost, dependency) | ACTIVE |
| DEC-10 | 2026-11-16 | Auth: mock phone OTP in the prototype | Real SMS needs a provider and cost; prototype only | Real SMS, email login | ACTIVE |
| DEC-11 | 2026-11-16 | Scheme KB entries are `verified:false` until a human checks the official page (R-04) | Avoid giving wrong eligibility guidance | Trusting memory or web summaries | ACTIVE |
| DEC-12 | 2026-11-16 | Impact figures (10%, 40%, 81%) are scenario assumptions, labelled so everywhere | Not measured; honesty with judges and users | Presenting as results | ACTIVE |
| DEC-13 | 2026-11-16 | Business models (freemium, quarterly plan, loan referrals, supplier tie-ups, institutional licence) are proposals, out of prototype scope; referral revenue must never influence advice rules | Keep the prototype focused; avoid conflicts of interest | Building billing now | ACTIVE |
| DEC-14 | 2026-11-16 | Branch and commit convention: one checkpoint per commit group, message `CP-<ID>: summary` | Makes progress traceable | Free-form commits | ACTIVE |
| DEC-15 | 2026-11-16 | Voice: browser Web Speech API with text fallback | Free and no server cost; works for Hindi on supported browsers | Paid speech APIs | ACTIVE |
| DEC-16 | 2026-11-16 | `AGENTS.md` lives at the repo root (moved back from `docs/`) | Matches ARCHITECTURE section 9; `tools/build_master.py` expects it there | Keep in `docs/` and change the script | ACTIVE |
| DEC-17 | 2026-11-16 | No `LICENSE` file yet; add one after team approval | The team has not approved a licence | MIT, Apache-2.0 now | ACTIVE |
| DEC-18 | 2026-11-16 | Backend runs on Python 3.14 in `backend/.venv`; `requires-python >=3.11` | 3.14 is installed on the dev machine; 3.11+ stays supported for teammates | Install 3.12 | SUPERSEDED by DEC-20 |
| DEC-19 | 2026-11-16 | Dependencies: pip + venv with exact `==` pins in `backend/pyproject.toml` | No extra tooling needed | uv, Poetry | ACTIVE |
| DEC-20 | 2026-11-16 | Backend dev, tests and scripts run in Docker (`python:3.14-slim`, `docker-compose.yml`), not a Windows venv | Windows Smart App Control blocked the compiled DLLs of numpy, pandas, SQLAlchemy, scikit-learn and LightGBM; Linux containers are not affected, and the security setting stays on | Pin older wheels, turn off Smart App Control (cannot be re-enabled), WSL distro | ACTIVE |
