# Business Sarthi tasks. Run INSIDE the backend container (DEC-31):
#   docker compose run --rm -w /repo backend make train
# (Git Bash: export MSYS_NO_PATHCONV=1 first.)
SYNTH := data/synthetic/out
.PHONY: help synth train test lint

help:
	@echo "make synth   regenerate synthetic data (+ demo shops) in $(SYNTH)/"
	@echo "make train   train ML2 quantile models into backend/data/models/ml2/ (runs synth if needed)"
	@echo "make test    run the backend test suite"
	@echo "make lint    ruff over backend/ and data/synthetic/"

$(SYNTH)/daily.csv: data/synthetic/config.yaml data/synthetic/generate.py
	python data/synthetic/generate.py --demo

synth:
	python data/synthetic/generate.py --demo

train: $(SYNTH)/daily.csv
	cd backend && python -m app.ml.train

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check . ../data/synthetic
