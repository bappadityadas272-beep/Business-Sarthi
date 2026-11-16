# Business Sarthi tasks. Run INSIDE the backend container (DEC-31):
#   docker compose run --rm -w /repo backend make train
# (Git Bash: export MSYS_NO_PATHCONV=1 first.)
SYNTH := data/synthetic/out
.PHONY: help synth train eval eval-reforecast test lint

help:
	@echo "make synth   regenerate synthetic data (+ demo shops) in $(SYNTH)/"
	@echo "make train   train and calibrate ML2 into backend/data/models/ml2/ (runs synth if needed)"
	@echo "make eval    ML2 evaluation on the held-out test shops; rewrites docs/EVAL_REPORT.md"
	@echo "make eval-reforecast   ML3 re-forecast backtest (several minutes); updates its part of docs/EVAL_REPORT.md"
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

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check . ../data/synthetic ../eval
