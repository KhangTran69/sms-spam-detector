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
#   make demo           train/evaluate using tracked synthetic fixtures only
#   make serve          run the FastAPI service with reload
#   make docker-build   build the container image
#   make docker-run     run the image with ./models mounted read-only
#   make clean          remove caches (never touches data/ or models/)

PYTHON ?= .venv/bin/python
PIP ?= $(PYTHON) -m pip
UVICORN ?= .venv/bin/uvicorn
IMAGE ?= philippine-sms-spam-detector:local
PORT ?= 8000
DEMO_MODEL ?= models/demo_synthetic.pkl
DEMO_EVALUATION ?= data/processed/demo-synthetic.json

.PHONY: install dev-install package-install test lint format typecheck train evaluate demo serve docker-build docker-run clean

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

demo:
	@mkdir -p "$(dir $(DEMO_MODEL))" "$(dir $(DEMO_EVALUATION))"
	$(PYTHON) -m src.train --data data/raw/ph_supplement.csv \
		--supplement data/raw/ph_supplement_2.csv data/raw/ph_supplement_3.csv \
		data/raw/ph_supplement_4.csv data/raw/ph_supplement_5.csv \
		--holdout data/raw/ph_holdout.csv --output "$(DEMO_MODEL)" \
		--model-version synthetic-demo-word --text-features word
	$(PYTHON) -m src.evaluate --data data/raw/ph_supplement.csv \
		--supplement data/raw/ph_supplement_2.csv data/raw/ph_supplement_3.csv \
		data/raw/ph_supplement_4.csv data/raw/ph_supplement_5.csv \
		--holdout data/raw/ph_holdout.csv --model "$(DEMO_MODEL)" \
		--plot none --json-out "$(DEMO_EVALUATION)"
	$(PYTHON) scripts/demo_smoke.py --model "$(DEMO_MODEL)"

serve:
	$(UVICORN) api.main:app --host 127.0.0.1 --port $(PORT) --reload

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm -p 127.0.0.1:$(PORT):8000 \
		-v "$(CURDIR)/models:/app/models:ro" \
		-e SMSD_MODEL_PATH=/app/models/spam_detector_v1.pkl \
		$(IMAGE)

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml
	find . \( -name .venv -o -name venv \) -prune -o -type d -name __pycache__ -prune -exec rm -rf {} +
	find . \( -name .venv -o -name venv \) -prune -o -type f -name '*.py[cod]' -delete
