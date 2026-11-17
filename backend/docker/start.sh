#!/bin/sh
# Backend start-up for `docker compose up` (DEC-82): one command from a fresh clone to a running API.
#   1. database migrations (creates backend/data/sarthi.db if missing)
#   2. SYNTHETIC data and the ML2 forecast model, only if they are missing (first start takes a few minutes)
#   3. the two SYNTHETIC demo shops, only if SEED_DEMO=1 and they are not in the database yet
#   4. the API on port 8000
# Nothing here prints .env or a key.
set -e
cd /repo/backend

echo "[start] database migrations"
alembic upgrade head

if [ ! -f data/models/ml2/ml2_p50.joblib ] || [ ! -f /repo/data/synthetic/out/daily.csv ]; then
  echo "[start] SYNTHETIC data or forecast model missing: generating and training (first start only)"
  make -C /repo train
fi

if [ "${SEED_DEMO:-1}" = "1" ]; then
  echo "[start] demo shops (SYNTHETIC): seed if missing"
  python -m app.seed --if-missing
fi

if [ "${UVICORN_RELOAD:-0}" = "1" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --no-access-log
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log   # the app logs each request as JSON (DEC-90)
