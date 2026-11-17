# AUDIT: backend audit rounds (session goal, 2026-11-17 to 2026-11-18)

Each round runs the same list on a **fresh clone** of `main` from GitHub, so nothing local (a `.env`, a trained model,
a database) can hide a problem. The loop stops when a round finds nothing new (at most 3 rounds).
This is an engineering self-audit by the coding model, not an external security review.

**Checks in every round**

1. Fresh clone, image built from it, then `make lint`, `make typecheck`, `make train`, `make test`, `make eval`,
   `make demo-e2e` (stub LLM, no `.env`).
2. Security:
   - secrets in the tracked tree and the whole git history (`git log -p --all`) for Gemini, Anthropic, GitHub,
     Slack and private-key patterns and `LLM_API_KEY=<value>`;
   - files that must never be committed (`.env`, `*.db`, `*.joblib`, generated data, the KB index);
   - `bandit -r backend/app -ll` (medium and high severity), `pip-audit` on the backend dependencies, ruff;
   - the app started with `DEV_MODE=0`;
   - login, ownership and consent on every route (`tests/test_access_sweep.py`, built from the OpenAPI schema).
3. Targets in `docs/EVAL_REPORT.md` against a fresh `make eval` run.
4. Docs drift: status lines, the stack, the API list in ARCHITECTURE against the real OpenAPI paths, documented
   `make` targets against the Makefile.
5. Failure injection:
   - a bad API key;
   - a deleted model;
   - malformed input;
   - a Hindi prompt injection;
   - the same daily log posted twice;
   - advance time twice.

## Round 1 (2026-11-18, commit `c72f3c9`)

### Results

| Check | Result |
|---|---|
| Fresh clone: lint, mypy (82 files), train, tests | clean; **546 passed** |
| `make eval` | runs; output equal to the committed `docs/EVAL_REPORT.md` and report parts (only line endings differ on Windows) |
| `make demo-e2e` | 7 PASS, 0 FAIL, 1 MISSED (step 7 scheme half: no `data/kb/schemes.json`, team item D-03) |
| CI on `c72f3c9` | run 44146733888, all steps green |
| Secrets: tracked tree / git history | 0 / 0 hits; no forbidden file ever committed; `.env` ignored |
| bandit (medium and high) | 0 issues |
| pip-audit | no known vulnerabilities |
| `DEV_MODE=0` (real process, not a monkeypatch) | `/api/dev/*` answer 404 and are absent from OpenAPI; OTP response has `dev_otp: null`; `/docs` still served |
| Access sweep | every non-public operation 401 without a token; another owner's shop 404 like a missing id (26 operations); 403 without consent |
| Targets | summary table in EVAL_REPORT matches the fresh run: 7 MET (SYNTHETIC or hand-written cases), ML2 pinball PARTLY, ML7, ML8, public-data check NOT MEASURED |

### Failure injection

| Injection | Result | Proof |
|---|---|---|
| Bad API key (provider answers 400 "API key not valid") | chat answers with the code-made template; the key is in no log line | `test_chat_api.py::test_a_bad_api_key_gives_the_template_and_never_logs_the_key` (**new**), `test_llm_client.py::test_client_error_is_not_retried_and_empty_answer_falls_back` |
| Deleted model | forecast answers 503 `model_not_ready`; startup logs a clear error; `/api/ready` 503 with the fix | `test_forecast.py::test_endpoint_says_503_when_the_model_is_missing`, `test_hardening.py::test_startup_logs_a_clear_error_for_a_missing_model` |
| Malformed input | 422 with the one error shape; nothing saved from a rejected request; 413 above the body limit | `test_records.py::test_logs_reject_future_days_negative_values_and_unknown_categories`, `test_hardening.py` |
| Hindi prompt injection that the LLM obeys (invented ₹10,00,000, "guarantee") | never shown; the guard fails it and the template is shown | `test_chat_api.py::test_a_prompt_injection_the_llm_obeys_is_never_shown` (**new**, Hindi and Hinglish), `test_guard.py` |
| Same daily log twice | upsert: one row per shop, day and category (`uq_daily_log_shop_day_cat`), the later value wins | `test_records.py` (created 0, updated 1) |
| Advance time twice, and a restart | no duplicate reviews or alerts | `test_seed.py::test_advance_twice_and_a_restart_never_duplicate_reviews_or_alerts` |

### Findings

| # | Finding | Severity | Action |
|---|---|---|---|
| A1-1 | README stack table listed tools that were never chosen (Node.js, Flask, Firebase, MongoDB, XGBoost, LangChain, Vercel); badge, roadmap and forecast text still said "concept" / "planned" | docs drift | **fixed**: table follows DECISIONS, backend rows marked built, frontend marked planned |
| A1-2 | README pictures (`assets/tech-stack.png`, `assets/request-flow.png`) show concept-stage tools | docs drift | **open, team**: redraw; the README now says the table is current and the pictures may be older |
| A1-3 | `AGENTS.md` said "no application code exists yet"; `SPEC.md` said "implementation not started" | docs drift | **fixed** |
| A1-4 | `GET /api/consents/history` missing from the ARCHITECTURE API list (every other one of the 45 operations is listed) | docs drift | **fixed** |
| A1-5 | No end-to-end test of a bad key or an obeyed Hindi injection through `chat.answer` (only unit level) | test gap | **fixed**: 3 new tests |
| A1-6 | Running the audit image build and a test container at the same time crashed Docker Desktop on the laptop (engine 500, "EOF") | environment | no code change; run heavy Docker jobs one at a time on this machine |

No security finding in round 1.

## Round 2 (2026-11-18, commit `d45608d`)

### Results

| Check | Result |
|---|---|
| Fresh clone: lint, mypy, train, tests | clean; **549 passed** (546 + the 3 round-1 tests) |
| `make eval` | equal to the committed report (no change apart from line endings) |
| `make demo-e2e` | 7 PASS, 0 FAIL, 1 MISSED (same known gap) |
| Secrets, forbidden files | 0 hits (unchanged) |
| pip-audit | no known vulnerabilities |
| bandit, medium and high | 0 |
| bandit, low (reviewed one by one this round) | 5: 2× B105 in `app/errors.py` are message texts ("invalid_token", "token_expired"), false positives; 1× B105 `DEV_JWT_SECRET` in `app/config.py` is the labelled dev placeholder, refused outside dev mode (but see A2-2); 2× B101 `assert` used as data-leakage guards in `app/ml/train.py` and `app/ml/calibrate.py` (A2-1) |
| `DEV_MODE=0` with **no** `JWT_SECRET`, real process | see A2-2 |

### Findings

| # | Finding | Severity | Action |
|---|---|---|---|
| A2-1 | The two training leakage guards (calibration shops disjoint from train/test; no `latent_` column in the features) were `assert`s, which `python -O` removes | low | **fixed**: explicit `ValueError` with the fix |
| A2-2 | With `DEV_MODE=0` and `JWT_SECRET` unset (or empty), `/api/ready` answered **200 "ready"** while every login failed with a generic **500**; an empty or short secret was not checked at all | medium (operability; no secret leaked, the placeholder was already refused) | **fixed (DEC-97, chosen by the human)**: `/api/ready` has an `auth` check (503 with the fix); OTP request, verify and token reads answer 503 `auth_not_configured`, checked before an OTP is made or used; startup logs the error; under 32 characters counts as not set (RFC 7518 section 3.2). Tests in `test_hardening.py`; RUNBOOK symptom row; `.env.example` comment |

Round 2 found something new, so round 3 runs.
