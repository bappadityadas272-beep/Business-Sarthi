#!/bin/sh
# API end-to-end test (demo path steps 1 to 8 over HTTP) on a FRESH throw-away database, in one container:
#   docker compose run --rm backend make demo-e2e                          # provider from .env
#   docker compose run --rm -e LLM_PROVIDER=stub backend make demo-e2e     # offline, no key (CI)
# Starts the API with the normal start-up (migrations, model if missing, SYNTHETIC demo seed) on a database under
# /tmp, runs scripts/demo_run.py against it, stops the API and returns the driver's exit code. The real
# backend/data/sarthi.db is not touched. DEV_MODE is forced on: the demo needs the mock OTP echo and advance-time.
# Nothing here prints .env or a key.
set -e
DB=/tmp/sarthi-demo-e2e.db
rm -f "$DB"
export DATABASE_URL="sqlite:///$DB" DEV_MODE=1 SEED_DEMO=1 UVICORN_RELOAD=0
PORT=${DEMO_PORT:-8765}
LOG=/tmp/sarthi-demo-e2e-api.log

# start.sh always binds port 8000; run its steps here so the port can differ from a running dev API
cd /repo/backend
alembic upgrade head >/dev/null
if [ ! -f data/models/ml2/ml2_p50.joblib ] || [ ! -f /repo/data/synthetic/out/daily.csv ]; then
  echo "[e2e] SYNTHETIC data or model missing: make train (a few minutes)"
  make -C /repo train >/dev/null
fi
python -m app.seed --if-missing >/dev/null
uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --no-access-log >"$LOG" 2>&1 &
API=$!
trap 'kill $API 2>/dev/null || true; rm -f "$DB"' EXIT

set +e
python /repo/scripts/demo_run.py --url "http://127.0.0.1:$PORT" --wait "${DEMO_WAIT:-120}" "$@"
RC=$?
if [ $RC -ne 0 ]; then
  echo "[e2e] driver exit $RC; last API log lines (JSON, phones masked):"
  tail -20 "$LOG"
fi
exit $RC
