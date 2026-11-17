# Business Sarthi tasks. Run INSIDE the backend container (DEC-31):
#   docker compose run --rm -w /repo backend make train
# (Git Bash: export MSYS_NO_PATHCONV=1 first.)
SYNTH := data/synthetic/out
.PHONY: help synth seed train eval eval-reforecast eval-stock eval-alerts eval-chat chat-live test lint

help:
	@echo "make synth   regenerate synthetic data (+ demo shops) in $(SYNTH)/"
	@echo "make train   train and calibrate ML2 into backend/data/models/ml2/ (runs synth if needed)"
	@echo "make eval    ML2 evaluation on the held-out test shops; rewrites docs/EVAL_REPORT.md"
	@echo "make eval-reforecast   ML3 re-forecast backtest (several minutes); updates its part of docs/EVAL_REPORT.md"
	@echo "make seed    load the two SYNTHETIC demo shops into the database (needs synth and train)"
	@echo "make eval-chat   C-08 chatbot groundedness on eval/chat_eval.jsonl (questions written by the team)"
	@echo "make chat-live   C-07 demo step 7 against the LLM provider set in .env (prints no key)"
	@echo "make test    run the backend test suite"
	@echo "make lint    ruff over backend/ and data/synthetic/"

$(SYNTH)/daily.csv: data/synthetic/config.yaml data/synthetic/generate.py
	python data/synthetic/generate.py --demo

synth:
	python data/synthetic/generate.py --demo

train: $(SYNTH)/daily.csv
	cd backend && python -m app.ml.train && python -m app.ml.calibrate

eval:
	cd backend && python ../eval/forecast_eval.py --write

eval-reforecast:
	cd backend && OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python ../eval/reforecast_eval.py --write

eval-alerts:
	cd backend && python ../eval/alert_eval.py --write

eval-stock:
	cd backend && python ../eval/stock_eval.py --write

eval-chat:
	cd backend && python ../eval/chat_eval.py

chat-live:
	cd backend && python ../eval/chat_live_check.py

seed: $(SYNTH)/daily.csv
	cd backend && alembic upgrade head && python -m app.seed

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check . ../data/synthetic ../eval
