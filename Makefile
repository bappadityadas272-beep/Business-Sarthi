# Business Sarthi tasks (DEC-31, DEC-82). Every target runs INSIDE the backend container.
#   On a PC without make (Windows):  docker compose run --rm backend make <target>
#   On a host with make:             make <target>   (hands itself to Docker automatically)
# Start and stop the API with `docker compose up` / `docker compose down` (docs/RUNBOOK.md).
SYNTH := data/synthetic/out
TARGETS := help synth train seed seed-if-missing migrate test lint eval eval-forecast eval-reforecast eval-stock \
           eval-alerts eval-chat eval-chat-smoke chat-live demo backup restore reset-db kb-check kb-index
.PHONY: $(TARGETS)

ifeq ($(wildcard /.dockerenv),)
# ---- host: run the same target in the container --------------------------------------------------------------
$(TARGETS):
	MSYS_NO_PATHCONV=1 docker compose run --rm backend make $@ $(if $(FILE),FILE=$(FILE))
else
# ---- container -----------------------------------------------------------------------------------------------
help:
	@echo "make test        backend test suite"
	@echo "make lint        ruff over backend/, data/synthetic/ and eval/"
	@echo "make eval        every evaluation (forecast, re-forecast, stock, alerts); rewrites docs/EVAL_REPORT.md"
	@echo "make synth       regenerate SYNTHETIC data (+ demo shops) in $(SYNTH)/"
	@echo "make train       train and calibrate ML2 into backend/data/models/ml2/ (runs synth if needed)"
	@echo "make migrate     apply database migrations"
	@echo "make seed        (re)load the two SYNTHETIC demo shops; replaces them if present"
	@echo "make eval-chat   C-08 chatbot groundedness on eval/chat_eval.jsonl (questions written by the team)"
	@echo "make eval-chat-smoke   the runner on eval/chat_eval_smoke.jsonl (a few labelled smoke questions)"
	@echo "make chat-live   demo step 7 against the LLM provider set in .env (prints no key)"
	@echo "make demo        scripts/demo_run.py: demo steps 1 to 8 over HTTP against a running API"
	@echo "make kb-check    validate data/kb/schemes.json (source_url, last_verified, eligibility); fails if missing"
	@echo "make kb-index    build the scheme embedding index (e5 if installed with EMBED=1, else the fallback)"
	@echo "make backup      copy backend/data/sarthi.db to backend/data/backups/sarthi-<time>.db"
	@echo "make restore FILE=backend/data/backups/<file>.db   put a backup back (stop the API first)"
	@echo "make reset-db    delete the database, migrate and seed again (stop the API first)"

$(SYNTH)/daily.csv: data/synthetic/config.yaml data/synthetic/generate.py
	python data/synthetic/generate.py --demo

synth:
	python data/synthetic/generate.py --demo

train: $(SYNTH)/daily.csv
	cd backend && python -m app.ml.train && python -m app.ml.calibrate

migrate:
	cd backend && alembic upgrade head

seed: $(SYNTH)/daily.csv migrate
	cd backend && python -m app.seed

seed-if-missing: $(SYNTH)/daily.csv migrate
	cd backend && python -m app.seed --if-missing

eval: eval-forecast eval-reforecast eval-stock eval-alerts

eval-forecast:
	cd backend && python ../eval/forecast_eval.py --write

eval-reforecast:
	cd backend && OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python ../eval/reforecast_eval.py --write

eval-alerts:
	cd backend && python ../eval/alert_eval.py --write

eval-stock:
	cd backend && python ../eval/stock_eval.py --write

eval-chat:
	cd backend && python ../eval/chat_eval.py

eval-chat-smoke:
	cd backend && python ../eval/chat_eval.py --file ../eval/chat_eval_smoke.jsonl --smoke

chat-live:
	cd backend && python ../eval/chat_live_check.py

demo:
	cd backend && python ../scripts/demo_run.py

kb-check:
	cd backend && python -m app.rag.kb

kb-index: kb-check
	cd backend && python -m app.rag.build_index

backup:
	python scripts/db_tool.py backup

restore:
	python scripts/db_tool.py restore "$(FILE)"
	cd backend && alembic upgrade head

reset-db:
	rm -f backend/data/sarthi.db
	$(MAKE) seed

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check . ../data/synthetic ../eval ../scripts
endif
