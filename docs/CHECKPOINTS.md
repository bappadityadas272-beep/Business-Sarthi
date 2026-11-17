# CHECKPOINTS: the live status tracker

> **This is the file that tells any new session where the project stands.** Update it whenever a checkpoint changes. `python tools/status.py` reads it and prints a summary.

```yaml
project_status:
  phase: "1 - backend core done (hero loop + grounded chatbot API: C-01, C-04 to C-07); frontend not started"
  last_updated: "2026-11-17"
  current_focus: "backend session goal: C-08 smoke, M-10, M-11, hardening, demo_run in CI, S-04/S-05, Q-01/Q-02/Q-05, audit"
  blockers:
    - "C-08: needs the 30 questions in eval/chat_eval.jsonl (written by the team, DEC-80) and a live LLM key"
    - "Live provider check of C-07 not run: no .env with LLM_PROVIDER and LLM_API_KEY yet"
  demo_path_ready: false
  notes: "Backend works end to end on synthetic demo data (make synth, make train, make seed, advance time); POST /api/chat answers demo step 7 'Is mahine ka profit kitna hai?' in Hinglish, Hindi and English with the stub, guard first, then SSE (DEC-73, DEC-79). Missed targets: scheme half of step 7 has the matcher (C-02, C-03 DONE) but no real scheme until the team writes data/kb/schemes.json (D-03); live Gemini check (make chat-live) not run; tests run only in Docker (Smart App Control blocks host DLLs). Live Overpass answer format is unverified. app_help.yaml is a draft until the frontend exists (DEC-78)."
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
| D-05 | Demo seed: Ramesh Kirana with 3 months of logs, a dip month and an EMI squeeze | all | P0 | D-01, B-01 | DONE | `make seed` creates the demo user and shop; demo script step 4 works | make seed loads Ramesh Kirana (review: pivot) and Sunita General Store (review: grow), dates shifted to the seed day (DEC-70); 6 tests. Dip deepened to 50% so the sales-dip alert shows (DEC-72). DEC-71 details await confirmation |

## B: Backend

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| B-01 | SQLAlchemy models and Alembic migration for ARCHITECTURE section 7 | all | P0 | S-02 | DONE | `alembic upgrade head` creates all tables; model tests pass | 13 tables; migration 0001; FK pragma on; unique (shop, day, category) on daily_log for B-05 |
| B-02 | Mock OTP auth + JWT | all | P0 | B-01 | DONE | Request and verify OTP returns JWT; wrong OTP is rejected; protected route needs token | OTP printed to server log in DEV_MODE and returned as dev_otp (DEC-40); JWT 7 days (DEC-41) |
| B-03 | Profile, language, consent endpoints | all | P0 | B-02 | DONE | Shop creation refused (403) without consent record | Purposes shop_data (required) and benchmarking (optional), DEC-43 |
| B-04 | Shops create and read | F1 | P0 | B-03 | DONE | Owner can create and read only own shops | Adds name, size_sqft, city_tier (DEC-42); other owners get 404 |
| B-05 | Daily logs bulk create and range read | F3,F5 | P0 | B-04 | DONE | Duplicate (shop, day, category) updates not duplicates; range query correct | Upsert on (shop, day, category); range read with daily totals; missing days stay missing |
| B-06 | Stock items, moves and assets | F3 | P0 | B-04 | DONE | On-hand stock equals sum of moves | On-hand = sum of moves (never stored); bulk moves all-or-nothing; input defaults in DEC-54 await confirmation |
| B-07 | Loans and EMI schedule | F6 | P0 | B-04 | DONE | Next due date computed correctly across month ends | start_date + tenure_months (DEC-53, migration 0004); schedule is dates and EMI only |
| B-08 | Alerts store, resolve, notifications | F6 | P0 | B-04 | DONE | Alert create, list, resolve works; notifications unread count | Alert create, list, resolve (with mute) and notifications unread count work; 6 tests. Refresh is on request until B-09 adds the daily job. DEC-68 details await confirmation |
| B-09 | APScheduler jobs and `POST /api/dev/advance-time` | F5,F6 | P0 | B-05, M-08, M-09 | DONE | Advancing 90 days triggers a review and stores it | Only when `DEV_MODE=1`. Advancing 90 days stores a review and a review_ready notification; 6 tests. Demo clock is in memory (resets on restart). DEC-69 details await confirmation |
| B-10 | SOS summary endpoint | F6 | P1 | B-08 | DONE | Returns a shareable summary of alerts and EMI status | 2026-11-17, DEC-83. `POST /api/sos` {shop_id, language?} (own shop, consent): open alerts, EMI status (next due, instalments left), last-30-days sales/purchases/expenses/profit (same code as the chat tools), a checklist picked by fixed rules (EMI within 7 days, loss, sales dip, low/dead stock, few logged days; then share and check-the-official-page) and `share_text` in hi, hinglish or en. Nothing is stored; no helpline numbers (none verified). The 7-day and two-thirds thresholds are assumptions. `test_sos.py` (6 tests). |
| B-11 | Delete-my-data endpoint | all | P1 | B-04 | DONE | After delete, no rows remain for the user | 2026-11-17, DEC-84. `DELETE /api/me/data` (login only, works after consent is withdrawn): user row and every row tied to it via the ORM cascades, consent history included; answer cache entries and a pending OTP also go. `test_privacy.py` fills one row in every owned table for two owners, deletes one, proves zero rows remain for it and the other is untouched. Tokens now carry an account stamp (creation time, microseconds) so a token of a deleted owner cannot open a new account that reuses the id. Backups are not touched (RUNBOOK section 4). |

## M: Machine learning and engines

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| M-01 | OSM client (Overpass + Nominatim), cache table, feature extractor | F2 | P0 | B-04 | DONE | Given a pin, returns counts of competitors, homes, schools, transit; second call hits cache; User-Agent set | Mock responses in tests; live Overpass format NOT verified (server busy 2026-11-16), see CHANGELOG |
| M-02 | Location score (ML1) + starter product mix | F2 | P1 | M-01, D-04 | DONE | Score and top drivers returned; scenario tests pass | `app/ml/location.py`, `GET /api/shops/{id}/location-score`; 10 tests in `test_location.py` (hand-worked values from the rule files). Weights and mix are assumptions (DEC-21), labelled in the response. The `manual sanity check on 5 real localities` (ML_PLAN section 3) needs `OSM_MODE=live` and a human: not done |
| M-03 | Train ML2 quantile models | F1 | P0 | D-01 | DONE | Model files and `model_card.json` written; `make train` reproducible | make train in Docker; LightGBM Huber P50 + ratio band (DEC-31 to DEC-36); reproducible SHA-256 |
| M-04 | Conformal calibration + evaluation report | F1 | P0 | M-03 | DONE | `eval/forecast_eval.py` prints WAPE vs baseline, pinball loss, coverage; coverage within 75% to 85% | SYNTHETIC, 200 test shops: WAPE 0.197 vs peer median 0.313 (37% lower); coverage 80.5%; 0 monotone breaks. First run on 200 shops missed coverage (94.0%), data grown to 1,000 shops (DEC-39); see EVAL_REPORT. Public-data run waits for D-02 |
| M-05 | Forecast service + endpoint + investment split | F1,F8 | P0 | M-04, M-01, B-04, D-04 | DONE | `POST /forecast` returns P10/P50/P90 for 12 months, break-even, payback range, drivers, confidence | Endpoint + service; margin, wage and payback extension are labelled assumptions (DEC-48 to DEC-52); confidence low under mock OSM by design |
| M-06 | Re-forecast (ML3) | F5 | P0 | M-05, B-05 | DONE | Backtest shows blend beats prior-only after 2 months; handles gaps | Met on synthetic shops: blend WAPE 8.8% vs prior-only 19.5% at 2 months (k = 10, DEC-55). Honest notes in EVAL_REPORT |
| M-07 | Stock advice (ML4) | F3 | P0 | B-06 | DONE | ROP, reorder qty, dead and overstock flags match hand-calculated cases | Hand-calculated cases pass (17 tests). Simulation on synthetic shops: 4.05 vs 9.57 stock-out days per 30 at 0.95x stock, met only after DEC-59 (first version 1.44x, missed) |
| M-08 | Review engine (ML5) + endpoint | F5 | P0 | M-06, M-07, B-07, D-04 | DONE | 20 labelled scenarios all give the expected decision | All 20 hand-labelled scenarios give the expected decision; no threshold changed. 30 tests. Thresholds are untested assumptions; DEC-66 details await confirmation |
| M-09 | Alert engine (ML6) | F6 | P0 | B-05, B-07, M-07, D-04 | DONE | Injected dips detected (recall at least 90%); false alarms under 1 per shop per month | Synthetic test shops: recall 95.3% on dips of 35% or deeper within 14 days, 0 false alarms (clean generator; see EVAL_REPORT notes). 17 tests. Not yet wired to the API (B-08, B-09) |
| M-10 | Expansion simulator (ML9) | F8 | P2 | M-06 | DONE | Returns payback range and P(payback<12m) for 3 options | Assumptions flagged in output. `app/ml/simulate.py` + `POST /api/shops/{id}/simulate` (DEC-88): 1,000 draws per option over the latest forecast band, payback P10/P50/P90, P(payback < 12 months), extra revenue and profit bands, `assumption: true`, the yaml ranges, margin source. `tests/test_simulate.py` 12 tests, including a hand check against the assumed extremes. Every range is a proposed assumption (DEC-21), not measured; extend_hours has no one-time cost, so its payback is 0 whenever it adds profit (flagged `no_upfront_cost`) |
| M-11 | Pricing helper (ML10) | F9 | P2 | B-06 | TODO | Flags categories below target margin | |

## C: Chatbot and schemes

| ID | Title | Feat | Pri | Depends | Status | Acceptance | Notes |
|---|---|---|---|---|---|---|---|
| C-01 | `LLMClient` interface + providers (gemini, claude, stub) | F7 | P0 | S-02 | DONE | Stub returns deterministic text; provider chosen by env var | `app/llm/client.py`, `stub.py`, `gemini.py`, `claude.py` over httpx; retry 1/2/4 s with jitter, 20 s timeout, fallback, daily answer cache (DEC-75); 11 tests, network mocked. Live providers not yet run |
| C-02 | KB loader + embedding index build | F4,F7 | P1 | D-03 | DONE | `python -m app.rag.build_index` writes index; top-1 retrieval correct on 10 test queries (Hindi and English) | Built ahead of D-03 against a **TEST ONLY** fixture (`backend/tests/fixtures/kb/`, made-up schemes, `test_only:true`; the loader refuses such a file under `data/`). `app/rag/kb.py` validates (`make kb-check`: fails on a missing file, a missing or non-https `source_url`, a missing or future `last_verified`, bad or missing eligibility keys, duplicate ids) and generates `data/kb/schemes.schema.json`. `app/rag/index.py` + `make kb-index`. Embedder per DEC-85; the acceptance ran with the **fallback** embedder: 10/10 top-1 (5 English, 5 Hindi) in `tests/test_kb.py`. e5 retrieval not measured (extra not installed). Real-KB run waits for D-03 |
| C-03 | Scheme matcher (ML7) + endpoint | F4 | P1 | C-02, B-04 | DONE | 20 profile tests; top-3 contains expected scheme in at least 80% | `app/services/schemes.py`, `GET /api/schemes/match?shop_id=&state=&category=&age=&need=&language=` (login, consent, own shop; profile fields never stored, DEC-86). Hard checks then rank (DEC-87); each result has why it may fit, missing requirements, please-confirm items, source URL, `last_verified`, an `unverified` label and the notice. Chat `match_schemes` uses it; scheme answers are templates with no LLM call (DEC-87), with source links in `sources`. **20/20** in `tests/test_schemes.py`, but on the TEST ONLY fixture with profiles written by the same session, fallback embedder: this proves the code path, not real-world quality. Re-run on the team's KB after D-03 |
| C-04 | Chat tools (`get_forecast`, `get_latest_review`, ...) | F7 | P0 | M-05, M-08, M-07, M-09 | DONE | Each tool returns structured JSON for the demo shop | `app/llm/tools.py`: six tools; each output has `source` {id,label}, `as_of`, `note` and flat `facts` {key,value,unit,period}; profit periods and EMI shown apart per DEC-77; `match_schemes` returns `[]` with `no_verified_source` (DEC-74); `run()` checks owner and consent (one `shop_not_found` error); 8 tests on both demo shops |
| C-05 | Router + prompt builder + language handling | F7 | P0 | C-01, C-04 | DONE | Intent routing correct on 20 sample questions; reply language matches | `app/llm/router.py` (rules first, `<classify>` LLM fallback limited to the 5 labels), `language.py` (hi / hinglish / en), `prompts/system.md`, `prompts/classify.md`, builder in `prompts/__init__.py`, `templates.py` (3 languages, Indian ₹ grouping), `app_help.yaml` (draft); 46 tests: 20 routes, 10 languages, 7 refusals (DEC-78 proposed) |
| C-06 | Guard (number and citation check) + fallback template | F7 | P0 | C-05 | DONE | Injected wrong number is caught and replaced by the template | `app/llm/guard.py` (DEC-76); `tests/test_guard.py` 19 tests: wrong number, swapped ₹/lakh, Devanagari, other-month number, invented scheme, tool-output injection, "ignore your rules", guarantee/link/script; forced bad stub answer gives the template; every demo template answer passes. Question numbers count as plain only |
| C-07 | `POST /api/chat` with streaming | F7 | P0 | C-06, C-03, B-03 | DONE | Demo script step 7 works with stub and with a real provider | Built before C-03 (DEC-74). `app/services/chat.py` + `app/api/chat.py`: SSE meta/delta/done after the guard (DEC-73, DEC-79); both turns stored with sources; login + consent + own shop. `tests/test_chat_api.py`: profit question in Hinglish, Hindi and English passes the guard with the code's number. **Missed:** scheme half of step 7 (template only, until D-03, C-02, C-03); live check run 2026-11-17 (`make chat-live`): the old default model was retired (404); with DEC-81 all 6 LLM answers in Hinglish, Hindi and English passed the guard, all via the fallback `gemini-3.5-flash-lite` because `gemini-3.8-flash` was overloaded (503) |
| C-08 | Chat evaluation set (30 questions) and runner | F7 | P1 | C-07 | BLOCKED | `eval/chat_eval.py` reports groundedness at least 90% | Runner done (`make eval-chat`, DEC-80; `tests/test_chat_eval.py` 12 tests); exits 1 below the 90% target, 2 for a bad file. Smoke: `eval/chat_eval_smoke.jsonl`, 8 questions written by the coding model and labelled `smoke: true` (`make eval-chat-smoke`; the real set may not contain smoke lines). Smoke run 2026-11-17 with Gemini: grounded 7/8 (88%, below target; the miss was a provider outage, 503/429 on both models, not a guard failure), refusals 8/8, intent 8/8. This is not the C-08 result. Blocked on: the 30 questions in `eval/chat_eval.jsonl` (team writes them, not the model) (the live key now works, DEC-81) |

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
