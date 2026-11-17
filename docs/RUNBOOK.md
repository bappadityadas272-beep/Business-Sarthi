# RUNBOOK: running the backend

`docker compose up` is the one supported way to run the backend (DEC-82). Every command below runs from the
repository root. You need Docker Desktop (or Docker Engine with Compose v2) and git. You do not need Python, make or
Node on the host. This is a **prototype**: the demo shops and the training data are SYNTHETIC.

## 1. First start (fresh clone)

```sh
git clone https://github.com/bappadityadas272-beep/Business-Sarthi.git
cd Business-Sarthi
cp .env.example .env            # Windows PowerShell: Copy-Item .env.example .env
docker compose up               # add -d to run in the background
```

On start, `backend/docker/start.sh` does the following:

1. applies the database migrations (`alembic upgrade head`), which creates `backend/data/sarthi.db`;
2. on the first start only, generates the SYNTHETIC data and trains the forecast model (a few minutes);
3. loads the two SYNTHETIC demo shops if they are missing (`SEED_DEMO=1`, the default);
4. starts the API at <http://localhost:8000>, with interactive docs at <http://localhost:8000/docs>.

The API is up when `docker compose ps` shows `healthy`, or when <http://localhost:8000/api/health> answers. It is
**ready** for the demo when <http://localhost:8000/api/ready> answers 200; a 503 lists what is missing (database
not migrated, forecast model missing or stale, LLM key missing) and the command that fixes it.
<http://localhost:8000/api/about> shows the model card (trained on SYNTHETIC data) and which rule files are
assumptions.

With the `.env` copied unchanged, the chatbot uses the `stub` provider: no key and no network. To use Gemini, set
`LLM_PROVIDER=gemini` and `LLM_API_KEY=...` in `.env`, then run `docker compose up -d --force-recreate`. Never
commit `.env`, and never paste the key into an issue or a log.

## 2. Check the demo path

Run this with the API up:

```sh
docker compose exec backend make demo
```

It drives ARCHITECTURE §12 steps 1 to 8 over HTTP and prints PASS, FAIL or MISSED per step. MISSED marks a recorded
gap, not a bug: for example, the scheme answer has nothing to cite until the team writes `data/kb/schemes.json`
(DEC-74). The run exits 1 if any step FAILED; `--strict` (`python ../scripts/demo_run.py --strict`) also fails on
MISSED. The demo needs `DEV_MODE=1` (the default), because it uses the mock-OTP echo and the advance-time route.

## 3. Everyday commands

| Task | Command |
|---|---|
| Start (foreground / background) | `docker compose up` / `docker compose up -d` |
| Stop (keeps the database) | `docker compose down` |
| Restart after an `.env` change | `docker compose up -d --force-recreate` |
| View logs | `docker compose logs -f backend` |
| Shell in the container | `docker compose exec backend sh` |
| Tests | `docker compose run --rm backend make test` |
| Lint (ruff) | `docker compose run --rm backend make lint` |
| Type check (mypy, DEC-93) | `docker compose run --rm backend make typecheck` |
| Tests with coverage (fails below 70% on services and ml) | `docker compose run --rm backend make cov` |
| API end-to-end demo on a fresh throw-away database (what CI runs) | `docker compose run --rm -e LLM_PROVIDER=stub backend make demo-e2e` |
| All evaluations (rewrites docs/EVAL_REPORT.md) | `docker compose run --rm backend make eval` |
| Chatbot evaluation (the team's questions) | `docker compose run --rm backend make eval-chat` |
| Live LLM check (uses the key in `.env`; prints no key) | `docker compose run --rm backend make chat-live` |
| Retrain the model | `docker compose run --rm backend make train` |
| Check the scheme KB (`data/kb/schemes.json`) | `docker compose run --rm backend make kb-check` |
| Build the scheme index | `docker compose run --rm backend make kb-index` |
| Use real multilingual embeddings (DEC-85, about 1 GB more) | `EMBED=1 docker compose build`, then `make kb-index` |
| List every target | `docker compose run --rm backend make help` |

On a host that has `make` (Linux, macOS, Git Bash with make), `make test` hands itself to Docker, so it is the same as
the `docker compose run` form.

The full test suite takes about 9 minutes on a laptop.

## 4. Database

The database is the file `backend/data/sarthi.db`, in the bind-mounted repo. It is git-ignored and survives
`docker compose down`.

| Task | Command |
|---|---|
| Reload the demo shops (replaces only the two demo owners) | `docker compose run --rm backend make seed` |
| Reset (delete the database, migrate, seed) | `docker compose down`, then `docker compose run --rm backend make reset-db` |
| Back up (safe while the API runs) | `docker compose run --rm backend make backup` → `backend/data/backups/sarthi-<time>.db` |
| Restore | `docker compose down`, then `docker compose run --rm backend make restore FILE=backend/data/backups/<file>.db` |
| Start without the demo shops | `SEED_DEMO=0 docker compose up` (PowerShell: `$env:SEED_DEMO=0; docker compose up`) |

Backups hold owner data once real owners exist. They are git-ignored (`*.db`) and must be deleted along with the
data when an owner asks for deletion (B-11). A restore checks the file with SQLite's `integrity_check` first, then
applies any newer migrations.

**Delete-my-data (B-11, DEC-84).** `DELETE /api/me/data` removes the account and every row tied to it (shops,
logs, stock, loans, forecasts, reviews, alerts, notifications, chat, consents and consent history) and answers
with the row count per table. It does **not** touch files in `backend/data/backups/`: the operator deletes every
backup made before the request (or restores none of them) by hand. Restoring an old backup brings deleted owners
back, so do not restore one after a deletion request without removing that owner again.

## 5. Common errors

| Symptom | Cause and fix |
|---|---|
| `/api/ready` 503, model `model_stale_config_changed` or `model_file_changed` | The SYNTHETIC config or the model file changed after training. Run `docker compose run --rm backend make train`, then restart. Forecasts answer 503 `model_not_ready` until then. |
| 429 `rate_limited` | Too many OTP requests (3 per phone per 10 min, 20 per address per hour) or chat messages (20 per user per minute). Wait `retry_after` seconds. A restart clears the counters. |
| 404 on `/api/dev/...` | `DEV_MODE` is off; the demo clock is switched off on purpose (DEC-91). |
| `port is already allocated` / `bind: address already in use` | Another program or a second clone is using port 8000. Stop it, or run `API_PORT=8001 docker compose up`, then open port 8001. |
| The first start takes minutes, and `docker compose ps` shows `starting` | Normal: the SYNTHETIC data is generated and the model trained once. Watch with `docker compose logs -f backend`. |
| `start.sh: not found` or `$'\r': command not found` | The script was checked out with Windows line endings. `.gitattributes` forces LF for `*.sh`; check the file out again with `git checkout -- backend/docker/start.sh`. |
| `make demo` → `no dev_otp echo` | `DEV_MODE=0` in `.env`. The demo needs `DEV_MODE=1`. |
| `make demo` → `demo owner has no shop` | The demo seed did not run (`SEED_DEMO=0`). Run `docker compose run --rm backend make seed`. |
| Chat answers are templates, and logs show `llm fallback` or `llm_unavailable` | The Gemini model is overloaded or the key is wrong. The owner still gets a template answer made by code (DEC-73). Check the key, `LLM_MODEL` and `LLM_FALLBACK_MODEL` (DEC-81) with `make chat-live`. |
| HTTP 404 from Gemini | That model is not available to your key. Set `LLM_MODEL` to one your key can use. |
| `database is locked` | A long write is running, such as a restore with the API up. Stop the API (`docker compose down`) and retry. |
| Changes to `pyproject.toml` are not picked up | Rebuild the image: `docker compose build backend`. |
