# Philippine SMS Spam and Scam Detector

An assistive SMS classifier and web demo for Philippine English, Filipino, and Taglish. It combines TF-IDF text features with URL, phone, money, urgency, and brand signals. The project includes data validation, leakage-aware training/evaluation, a FastAPI service, a browser UI, CI, and container deployment files.

> **Evidence limit:** Philippine examples currently tracked here are synthetic. The public UCI SMS Spam Collection is English-heavy. This repository does not contain a representative, consented Philippine SMS dataset, so its scores are engineering checks—not evidence of real-world accuracy. Do not block, delete, report, or penalize anyone based only on a prediction.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

Python 3.11+ is required. The base SMS corpus is not committed. Download the Kaggle [Spam Text Message Classification](https://www.kaggle.com/datasets/anthonytherrien/spam-text-message-classification) CSV, or use the documented UCI SMS Spam Collection source, and save it as `data/raw/spam.csv`. Accepted formats are Kaggle `v1`/`v2` and `label`/`message` CSVs.

The tracked Philippine supplements and holdout are synthetic templates for repeatable pipeline checks. See [data/raw/README.md](data/raw/README.md) and [docs/DATA_COLLECTION.md](docs/DATA_COLLECTION.md) before adding any real messages. Raw real messages, model artifacts, and feedback reports are excluded from Git.

The documented public English source is the UCI SMS Spam Collection (5,574 historical messages, CC BY 4.0). The current ignored `spam.csv` has no recorded source/license metadata, so it remains `unknown` until its provenance is verified. Do not add mirrors as extra supplements: exact copies are removed and near-duplicates can distort evaluation. To normalize a separately downloaded UCI TSV while preserving attribution, run `python -m src.import_public_dataset --input /path/to/SMSSpamCollection --format uci-tsv`. The importer writes only to ignored `data/raw/` and never downloads the corpus. See [data/raw/README.md](data/raw/README.md) for limitations and attribution.

## Train and evaluate

```bash
python -m src.train
python -m src.evaluate --json-out data/processed/evaluation.json
```

Training validates schemas and labels, removes exact duplicates before splitting, keeps campaign/template groups together, tunes the decision threshold on validation data, and reports the final test metrics separately. The artifact contains the model, threshold, training/data provenance, and version metadata. The public English corpus and three synthetic Philippine supplements are used by default when present.

Training records per-file source metadata and label/language/category/provenance coverage in the artifact and a message-free `models/*.manifest.json` sidecar. The manifest includes input/retained row counts, duplicates, file hashes, class counts, split method/seed/fingerprint, and whether metadata was unverified. Small per-class splits are flagged so scores with limited support are not mistaken for stable estimates.

For real data with reliable `received_at` timestamps and campaign groups, chronological validation/test splits are available:

```bash
python -m src.train --split-by time
```

Time splits require valid dates for every row and fail if both classes cannot be represented. Use `--split-by group` for the default group-aware split. The random split option is diagnostic only and can leak related examples.

Evaluation reports class metrics, false positives by legitimate category, threshold tradeoffs, calibration diagnostics, and holdout/template overlap. It prints sample counts and labels synthetic results. The model currently reports uncalibrated scores; a score is not a probability guarantee. Do not use synthetic holdout results as a real-world accuracy claim.

Run `python -m src.train --help` and `python -m src.evaluate --help` for all data, threshold, split, and output options.

## Run the API and web UI

Train a model, then start the service:

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. Interactive API docs are at `/docs`.

- `GET /health` and `GET /ready` provide liveness/readiness.
- `GET /model-info` returns model version, thresholds, provenance, and data caveats.
- `POST /predict` returns the label, score, calibration status, flags, threshold, and model version.
- `POST /analyze` adds risk bands and signal highlights for the UI.
- `POST /analyze/batch` accepts up to 50 messages.
- `POST /feedback` accepts only a user-selected expected label, displayed label, broad category, and model version. It rejects message/text fields and is disabled by default.

Example:

```bash
curl -X POST http://127.0.0.1:8000/predict \\
  -H 'Content-Type: application/json' \\
  -d '{"message":"BDO: Your account is locked. Verify here: http://bit.ly/fakebdo"}'
```

### Optional anonymous correction reports

The web form appears only when the operator opts in:

```bash
SMSD_FEEDBACK_ENABLED=true uvicorn api.main:app --host 127.0.0.1 --port 8000
```

A submitted report stores the chosen correction, broad category, timestamp, and model version in `data/feedback/reports.jsonl`. It never sends or stores the SMS text, sender details, or IP address. Reports are unverified review signals; they are never automatically added to training. The queue is local, ignored by Git, and capped at 10 MiB. For Docker Compose, set `SMSD_FEEDBACK_ENABLED=true`; reports persist in the named `smsd_feedback` Docker volume. Do not expose this anonymous endpoint publicly without authentication or deployment-level abuse controls and a retention policy.

Summarize an enabled local queue without exporting report IDs or timestamps:

```bash
python -m src.feedback --path data/feedback/reports.jsonl --output data/processed/feedback-summary.json
```

## Docker

Train the model locally first, then:

```bash
docker compose build
docker compose up -d
curl http://127.0.0.1:8000/ready
```

The container runs as non-root, binds to loopback by default, and mounts the model read-only. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for production network, TLS, health, and rollback guidance.

## Data collection and human review

No real-data collection or participant study has been completed. Use the blank [consented message template](data/templates/consented_ph_sms_template.csv) only in an approved secure workspace. Obtain informed consent, redact names/numbers/OTPs/accounts before storage, have two reviewers label examples, and keep campaign, source, language, category, confidence, and date metadata. Keep a real holdout separate by campaign and time. Read [docs/HUMAN_REVIEW.md](docs/HUMAN_REVIEW.md) before organizing participant review.

## Development checks

```bash
pytest -q
ruff check .
ruff format --check .
mypy src api
```

GitHub Actions runs the project quality checks. `make help` lists common local commands.

## Documentation

- [Data collection, labeling, and leakage prevention](docs/DATA_COLLECTION.md)
- [Human review protocol](docs/HUMAN_REVIEW.md)
- [Privacy and data handling](docs/PRIVACY.md)
- [Model card and limitations](docs/MODEL_CARD.md)
- [Retraining, versioning, and rollback](docs/RETRAINING.md)
- [Deployment guide](docs/DEPLOYMENT.md)

## Project layout

```text
data/raw/        ignored source data plus tracked synthetic fixtures
data/templates/  blank consented-data intake schema
src/             validation, preprocessing, features, training, metrics, inference
api/             FastAPI endpoints
web/             bundled single-page UI
models/          ignored trained model artifacts
docs/            data, review, model, privacy, retraining, deployment guidance
tests/           data, model, API, preprocessing, and web-contract checks
```

### Provenance and preprocessing compatibility

CSV files may include `data_kind` with `synthetic`, `public`, `consented`, or `unknown` (the default); legacy `real` is accepted as consented data. This is a source declaration, not independent verification. Training records fitted-row counts by kind; `synthetic_training_data` is true when synthetic rows were used, false only when all fitted rows are declared public or consented, and null when their status is unknown. Tracked Philippine fixtures are explicitly synthetic.

Feature version 2.1.0 recognizes `hxxp(s)` links and bracketed-dot domains and avoids matching partial domain suffixes. Retrain older artifacts before serving them; the loader rejects mismatched feature versions. These changes require evaluation and do not imply improved real-world accuracy.
