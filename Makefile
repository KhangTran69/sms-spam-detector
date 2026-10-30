# Developer entry points for the Philippine SMS spam/scam detector.
#
#   make install        install runtime dependencies
#   make dev-install    install runtime + dev/CI tooling
#   make test           run the pytest suite
#   make lint           ruff lint + format check
#   make format         apply ruff formatting
#   make typecheck      mypy on src/ + api/
#   make train          train and save models/spam_detector_v1.pkl
#   make evaluate       held-out evaluation + threshold sweep + PH holdout
#   make benchmark      validate, train, and report in one isolated output directory
#   make demo           train/evaluate using tracked synthetic fixtures only
#   make serve          run the FastAPI service with reload
#   make macos-install  install persistent per-user macOS service
#   make macos-status   inspect service, API, and model readiness
#   make docker-build   build the container image
#   make docker-run     run the image with ./models mounted read-only
#   make clean          remove caches (never touches data/ or models/)

PYTHON ?= .venv/bin/python
PIP ?= $(PYTHON) -m pip
IMAGE ?= philippine-sms-spam-detector:local
PORT ?= 8000
DEMO_MODEL ?= models/demo_synthetic.pkl
DEMO_EVALUATION ?= data/processed/demo-synthetic.json
BENCHMARK_DIR ?= data/processed/benchmark-run

.PHONY: help install dev-install package-install test lint format typecheck train evaluate benchmark demo serve macos-install macos-status macos-stop macos-restart macos-uninstall docker-build docker-run clean

help:
	@sed -n '1,25p' Makefile

install:
	$(PIP) install -r requirements.txt

dev-install:
	$(PIP) install -r requirements.txt -r requirements-dev.txt

package-install:
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .

typecheck:
	$(PYTHON) -m mypy src api

train:
	$(PYTHON) -m src.train

evaluate:
	$(PYTHON) -m src.evaluate

benchmark:
	@test -n "$(DATA)" || { echo "Set DATA to an approved training CSV; see docs/BENCHMARKING.md" >&2; exit 2; }
	$(PYTHON) -m src.benchmark --data "$(DATA)" --output-dir "$(BENCHMARK_DIR)" $(if $(SUPPLEMENTS),--supplement $(SUPPLEMENTS),--no-supplements) $(if $(HOLDOUT),--holdout "$(HOLDOUT)",--holdout none)

demo:
	@mkdir -p "$(dir $(DEMO_MODEL))" "$(dir $(DEMO_EVALUATION))"
	$(PYTHON) -m src.train --data data/raw/ph_supplement.csv \
		--supplement data/raw/ph_supplement_2.csv data/raw/ph_supplement_3.csv \
		data/raw/ph_supplement_4.csv data/raw/ph_supplement_5.csv \
		--holdout data/raw/ph_holdout.csv --output "$(DEMO_MODEL)" \
		--model-version synthetic-demo --text-features combined
	$(PYTHON) -m src.evaluate --data data/raw/ph_supplement.csv \
		--supplement data/raw/ph_supplement_2.csv data/raw/ph_supplement_3.csv \
		data/raw/ph_supplement_4.csv data/raw/ph_supplement_5.csv \
		--holdout data/raw/ph_holdout.csv --model "$(DEMO_MODEL)" \
		--plot none --json-out "$(DEMO_EVALUATION)"
	$(PYTHON) scripts/demo_smoke.py --model "$(DEMO_MODEL)"

serve:
	@command -v "$(PYTHON)" >/dev/null 2>&1 || { echo "Python not found at $(PYTHON). Create .venv and run: make dev-install" >&2; exit 2; }
	$(PYTHON) -m api.cli --host 127.0.0.1 --port $(PORT) --reload

macos-install:
	$(PYTHON) -m api.macos_service install --port $(PORT) $(if $(MODEL),--model "$(MODEL)",)

macos-status:
	$(PYTHON) -m api.macos_service status

macos-stop:
	$(PYTHON) -m api.macos_service stop

macos-restart:
	$(PYTHON) -m api.macos_service restart

macos-uninstall:
	$(PYTHON) -m api.macos_service uninstall

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm -p 127.0.0.1:$(PORT):8000 \
		-v "$(CURDIR)/models:/app/models:ro" \
		-e SMSD_MODEL_PATH=/app/models/spam_detector_v1.pkl \
		$(IMAGE)

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml build/ dist/ *.egg-info
	find . \( -name .venv -o -name venv \) -prune -o -type d -name __pycache__ -prune -exec rm -rf {} +
	find . \( -name .venv -o -name venv \) -prune -o -type f -name '*.py[cod]' -delete
