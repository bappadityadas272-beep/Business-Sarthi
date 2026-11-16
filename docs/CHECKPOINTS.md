# CHECKPOINTS: the live status tracker

> **This is the file that tells any new session where the project stands.** Update it whenever a checkpoint changes. `python tools/status.py` reads it and prints a summary.

```yaml
project_status:
  phase: "1 - backend core in progress"
  last_updated: "2026-11-16"
  current_focus: "B-03"
  blockers: []
  demo_path_ready: false
  notes: "Done in the order set by the human: S-01, S-02, B-01, D-04, D-01. Next order set by the human: M-03, M-04, B-02, B-03, B-04, M-01 (mock OSM), M-05."
```

**Status values:** `TODO` · `IN_PROGRESS` · `DONE` · `BLOCKED` · `DROPPED`
**Priority:** P0 demo path · P1 important · P2 nice to have
**Build order (vertical slices):** S (setup) → B-01..B-05 + D-01 + M-01..M-05 (first working forecast) → F-01..F-04 (first visible slice) → daily logs, stock, alerts → review loop → chatbot and schemes → polish and release.

Column key: **Feat** = feature from `SPEC.md`; **Depends** = checkpoint IDs that must be `DONE` first; **Acceptance** = the test that must pass before marking `DONE`.

## S: Setup

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| S-01 | Repo scaffold: folders from ARCHITECTURE section 9, `.gitignore` (db, `.env`, models, node_modules), MIT `LICENSE`, `.env.example` | all | P0 | - | DONE | Tree matches layout; `git status` clean of secrets | LICENSE deferred pending team approval (DEC-17); AGENTS.md moved back to root (DEC-16) |
| S-02 | Backend skeleton: FastAPI app, config loader, `/api/health`, pyproject with pinned deps | all | P0 | S-01 | DONE | `pytest` passes a health test; `uvicorn` serves `/docs` | Runs in Docker (DEC-20): `docker compose run --rm backend pytest` |
| S-03 | Frontend skeleton: Vite + React + TS + Tailwind, router, empty pages | all | P0 | S-01 | TODO | `npm run build` succeeds; home page renders | |
| S-04 | Makefile (`setup`, `dev`, `test`, `lint`, `train`, `seed`) | all | P1 | S-02, S-03 | TODO | `make test` runs both test suites | |
| S-05 | GitHub Actions CI (lint, type check, tests) | all | P1 | S-04 | TODO | CI green on a pull request | |

## D: Data and knowledge

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| D-01 | Synthetic data generator per ML_PLAN section 2 (config.yaml, seed, `--demo`) | F1 | P0 | S-01 | DONE | Generates 1,000 shops x 24 months (DEC-39; was 200); two runs with same seed are identical; every file has `is_synthetic` metadata | v1.1 after human review: floor 2,000 (0.5% of shops at it), per-shop +/-10% effect strength, festival uplift per category, 2 demo shops; 11 tests in tests/test_synthetic.py; DEC-23 to DEC-30 |
| D-02 | Pick and **licence-check** one public retail dataset; document in `data/PUBLIC_DATA.md` (name, URL, licence, date checked) | F1 | P1 | S-01 | TODO | Licence permits our use, or dataset replaced | Do not commit the raw data if the licence forbids |
| D-03 | Scheme KB v0: 5 to 8 entries from official pages, `verified:false`, with source URL and `last_verified` | F4 | P1 | S-01 | TODO | JSON validates against schema; every entry has a source URL | Human verification is R-04 |
| D-04 | Rule files: `review_rules.yaml`, `alert_rules.yaml`, `location_weights.yaml`, `product_mix.yaml`, `blend.yaml`, `actions.yaml`, `expansion.yaml` | F1,F2,F5,F6,F8 | P0 | S-01 | DONE | Loader validates every file with Pydantic | Loader `app/rules.py`; 8th file `investment_split.yaml` added (DEC-22); drafted values approved as assumptions (DEC-21) |
| D-05 | Demo seed: Ramesh Kirana with 3 months of logs, a dip month and an EMI squeeze | all | P0 | D-01, B-01 | TODO | `make seed` creates the demo user and shop; demo script step 4 works | |

## B: Backend

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| B-01 | SQLAlchemy models and Alembic migration for ARCHITECTURE section 7 | all | P0 | S-02 | DONE | `alembic upgrade head` creates all tables; model tests pass | 13 tables; migration 0001; FK pragma on; unique (shop, day, category) on daily_log for B-05 |
| B-02 | Mock OTP auth + JWT | all | P0 | B-01 | DONE | Request and verify OTP returns JWT; wrong OTP is rejected; protected route needs token | OTP printed to server log in DEV_MODE and returned as dev_otp (DEC-40); JWT 7 days (DEC-41) |
| B-03 | Profile, language, consent endpoints | all | P0 | B-02 | TODO | Shop creation refused (403) without consent record | |
| B-04 | Shops create and read | F1 | P0 | B-03 | TODO | Owner can create and read only own shops | |
| B-05 | Daily logs bulk create and range read | F3,F5 | P0 | B-04 | TODO | Duplicate (shop, day, category) updates not duplicates; range query correct | |
| B-06 | Stock items, moves and assets | F3 | P0 | B-04 | TODO | On-hand stock equals sum of moves | |
| B-07 | Loans and EMI schedule | F6 | P0 | B-04 | TODO | Next due date computed correctly across month ends | |
| B-08 | Alerts store, resolve, notifications | F6 | P0 | B-04 | TODO | Alert create, list, resolve works; notifications unread count | |
| B-09 | APScheduler jobs and `POST /api/dev/advance-time` | F5,F6 | P0 | B-05, M-08, M-09 | TODO | Advancing 90 days triggers a review and stores it | Only when `DEV_MODE=1` |
| B-10 | SOS summary endpoint | F6 | P1 | B-08 | TODO | Returns a shareable summary of alerts and EMI status | |
| B-11 | Delete-my-data endpoint | all | P1 | B-04 | TODO | After delete, no rows remain for the user | |

## M: Machine learning and engines

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| M-01 | OSM client (Overpass + Nominatim), cache table, feature extractor | F2 | P0 | B-04 | TODO | Given a pin, returns counts of competitors, homes, schools, transit; second call hits cache; User-Agent set | Mock responses in tests |
| M-02 | Location score (ML1) + starter product mix | F2 | P1 | M-01, D-04 | TODO | Score and top drivers returned; scenario tests pass | |
| M-03 | Train ML2 quantile models | F1 | P0 | D-01 | DONE | Model files and `model_card.json` written; `make train` reproducible | make train in Docker; LightGBM Huber P50 + ratio band (DEC-31 to DEC-36); reproducible SHA-256 |
| M-04 | Conformal calibration + evaluation report | F1 | P0 | M-03 | DONE | `eval/forecast_eval.py` prints WAPE vs baseline, pinball loss, coverage; coverage within 75% to 85% | SYNTHETIC, 200 test shops: WAPE 0.197 vs peer median 0.313 (37% lower); coverage 80.5%; 0 monotone breaks. First run on 200 shops missed coverage (94.0%), data grown to 1,000 shops (DEC-39); see EVAL_REPORT. Public-data run waits for D-02 |
| M-05 | Forecast service + endpoint + investment split | F1,F8 | P0 | M-04, M-01, B-04, D-04 | TODO | `POST /forecast` returns P10/P50/P90 for 12 months, break-even, payback range, drivers, confidence | |
| M-06 | Re-forecast (ML3) | F5 | P0 | M-05, B-05 | TODO | Backtest shows blend beats prior-only after 2 months; handles gaps | |
| M-07 | Stock advice (ML4) | F3 | P0 | B-06 | TODO | ROP, reorder qty, dead and overstock flags match hand-calculated cases | |
| M-08 | Review engine (ML5) + endpoint | F5 | P0 | M-06, M-07, B-07, D-04 | TODO | 20 labelled scenarios all give the expected decision | |
| M-09 | Alert engine (ML6) | F6 | P0 | B-05, B-07, M-07, D-04 | TODO | Injected dips detected (recall at least 90%); false alarms under 1 per shop per month | |
| M-10 | Expansion simulator (ML9) | F8 | P2 | M-06 | TODO | Returns payback range and P(payback<12m) for 3 options | Assumptions flagged in output |
| M-11 | Pricing helper (ML10) | F9 | P2 | B-06 | TODO | Flags categories below target margin | |

## C: Chatbot and schemes

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| C-01 | `LLMClient` interface + providers (gemini, claude, stub) | F7 | P0 | S-02 | TODO | Stub returns deterministic text; provider chosen by env var | |
| C-02 | KB loader + embedding index build | F4,F7 | P1 | D-03 | TODO | `python -m app.rag.build_index` writes index; top-1 retrieval correct on 10 test queries (Hindi and English) | |
| C-03 | Scheme matcher (ML7) + endpoint | F4 | P1 | C-02, B-04 | TODO | 20 profile tests; top-3 contains expected scheme in at least 80% | |
| C-04 | Chat tools (`get_forecast`, `get_latest_review`, ...) | F7 | P0 | M-05, M-08, M-07, M-09 | TODO | Each tool returns structured JSON for the demo shop | |
| C-05 | Router + prompt builder + language handling | F7 | P0 | C-01, C-04 | TODO | Intent routing correct on 20 sample questions; reply language matches | |
| C-06 | Guard (number and citation check) + fallback template | F7 | P0 | C-05 | TODO | Injected wrong number is caught and replaced by the template | |
| C-07 | `POST /api/chat` with streaming | F7 | P0 | C-06, C-03, B-03 | TODO | Demo script step 7 works with stub and with a real provider | |
| C-08 | Chat evaluation set (30 questions) and runner | F7 | P1 | C-07 | TODO | `eval/chat_eval.py` reports groundedness at least 90% | |

## F: Frontend

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| F-01 | Layout, theme, i18n (en, hi), API client from OpenAPI | all | P0 | S-03, S-02 | TODO | Language switch changes all visible strings | Mobile-first, large touch targets |
| F-02 | Login (mock OTP), language and consent screens | all | P0 | F-01, B-03 | TODO | New user reaches the idea screen only after consent | |
| F-03 | Idea intake + map pin (Leaflet) + location score card | F1,F2 | P0 | F-02, B-04, M-02 | TODO | Pin drop shows score, drivers and OSM attribution | |
| F-04 | Forecast page: range chart, break-even, payback, investment split | F1,F8 | P0 | F-03, M-05 | TODO | Demo script step 3 renders | Label "estimate, trained on synthetic data" |
| F-05 | Daily entry: big-button sales by category, stock in and out, expenses | F3 | P0 | F-02, B-05, B-06 | TODO | An entry takes under 30 seconds with taps; works offline then syncs (see F-13) | |
| F-06 | Dashboard: snapshot, alerts, next review, EMI countdown | F6 | P0 | F-05, B-08, M-09 | TODO | Seeded alerts appear in Hindi and English | |
| F-07 | Stock and assets pages with reorder list | F3 | P0 | F-05, M-07 | TODO | Reorder list matches API | |
| F-08 | Review page: decision, reasons, actions, re-forecast chart | F5 | P0 | F-06, M-08, B-09 | TODO | After "advance time", review appears with reasons | |
| F-09 | Schemes page with sources and notice | F4 | P1 | F-02, C-03 | TODO | Each card shows source link and last-verified date | |
| F-10 | Chat UI with voice input (Web Speech API) and source chips | F7 | P0 | F-02, C-07 | TODO | Hindi voice question returns a cited answer; works with text fallback | |
| F-11 | SOS screen | F6 | P1 | F-06, B-10 | TODO | Produces a shareable summary | |
| F-12 | Expansion simulator and pricing helper screens | F8,F9 | P2 | F-08, M-10, M-11 | TODO | Payback range chart renders | |
| F-13 | PWA install and offline queue for daily logs | F3 | P1 | F-05 | TODO | Entries made offline sync on reconnect with no duplicates | |

## Q: Quality

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| Q-01 | Backend test coverage at least 70% on services and ml | all | P1 | M-09, B-11 | TODO | Coverage report in CI | |
| Q-02 | ML evaluation report committed to `docs/EVAL_REPORT.md` | F1,F5 | P1 | M-04, M-06, M-08, M-09 | TODO | All section 8 targets reported honestly, including misses | |
| Q-03 | End-to-end demo test (Playwright) for demo script steps 1 to 8 | all | P1 | F-04, F-08, F-10 | TODO | Passes headless in CI | |
| Q-04 | Low-end phone and accessibility check (Lighthouse, 360 px width, font sizes) | all | P2 | F-06 | TODO | Lighthouse accessibility at least 90 | |
| Q-05 | Privacy self-review against ARCHITECTURE section 11 | all | P1 | B-11 | TODO | Checklist in `docs/PRIVACY_CHECK.md` all ticked | Not legal advice |

## R: Release

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| R-01 | README "Getting started" and screenshots of real UI | all | P1 | F-04 | TODO | A new developer runs the app in under 15 minutes following the README | README must only claim what exists |
| R-02 | Record the demo run (screen recording) | all | P1 | Q-03 | TODO | Video covers demo script steps 1 to 8 | |
| R-03 | Deploy (frontend static host + backend host) | all | P2 | Q-03 | TODO | Public URL runs the demo path | |
| R-04 | Verify every scheme KB entry against its official page; set `verified:true` | F4 | P1 | D-03 | TODO | No entry shown to users with `verified:false` unless labelled | |
