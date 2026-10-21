# Philippine SMS Spam and Scam Detector

An assistive SMS classifier, API, and web app for Philippine English, Filipino,
and Taglish. It combines word and character TF-IDF features with URL, phone,
money, urgency, and brand signals. The classifier is picked by cross-validation
and calibrated, and the service is FastAPI with a no-build web UI.

![Demo: checking a single message, a batch, and the Taglish dark theme](docs/images/demo.gif)

> **Evidence limit:** every Philippine message in this repository is synthetic,
> and the public UCI corpus is English. Scores below are engineering checks, not
> real-world accuracy. The tool is assistive only: do not block, report, or
> penalize anyone based on a prediction. Full limitations:
> [docs/MODEL_CARD.md §4](docs/MODEL_CARD.md#4-evaluation-and-the-synthetic-only-caveat).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r constraints/py3.12.txt -e ".[dev]"   # or py3.11 / py3.13

# 1. Get the public UCI SMS Spam Collection (CC BY 4.0) and import it with attribution
curl -LO https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip
unzip sms+spam+collection.zip SMSSpamCollection
python -m src.import_public_dataset --input SMSSpamCollection --format uci-tsv

# 2. Train (UCI + tracked synthetic PH supplements; the synthetic PH holdout is evaluated separately)
python -m src.train --data data/raw/imported/uci_sms_spam.csv

# 3. Serve the API and web UI at http://127.0.0.1:8000 (interactive docs at /docs)
smsd-serve            # or: uvicorn api.main:app --host 127.0.0.1 --port 8000
```

No data? `make demo` trains and smoke-tests a synthetic-only model. With Docker,
train first, then run `docker compose up -d` (the model is mounted read-only; see
[DEPLOYMENT.md](docs/DEPLOYMENT.md)).

## Results

The data is UCI plus the tracked synthetic PH supplements, deduplicated and split
by group. With seed 42 the internal test split has 810 messages, 131 of them spam.
Measured on 2026-10-21 with `python -m src.train --data data/raw/imported/uci_sms_spam.csv`.

| Model | Threshold | Spam precision | Spam recall | Spam F1 | Accuracy | Calibration error (ECE) |
|---|---|---|---|---|---|---|
| **Current:** LinearSVC (C=1, chosen by 5-fold CV F1 0.947) + sigmoid calibration, word+char features | 0.50 | 0.945 | 0.924 | **0.934** | 0.979 | **0.014** |
| MultinomialNB baseline (same features) | 0.50 | 0.906 | 0.809 | 0.855 | 0.956 | n/a |
| Previous default: LogisticRegression, word features, validation-tuned threshold* | 0.63 | 0.936 | 0.800 | 0.863 | 0.955 | 0.083 |

\*Measured on the earlier data and split: 814 test messages, 145 spam.

**Synthetic PH holdout (264 messages, 0 template families shared with training):**
precision 0.969, recall 0.900, F1 0.933, with 4 false alarms (3 e-wallet receipts,
1 OTP) and 14 missed scams. The holdout is synthetic, so these numbers check the
pipeline and are not field accuracy.

| | |
|---|---|
| ![Likely scam result](docs/images/02-likely-scam.png) | ![Looks safe result](docs/images/03-looks-safe.png) |
| ![Batch check](docs/images/04-batch.png) | ![Taglish, dark theme](docs/images/05-dark-taglish.png) |

## API

| Endpoint | Purpose |
|---|---|
| `GET /health`, `GET /ready` | Liveness; readiness (loads and validates the model) |
| `GET /model-info` | Version, threshold, risk bands, provenance, caveats |
| `POST /predict` | Label, calibrated score, flags, threshold |
| `POST /analyze`, `POST /analyze/batch` | Adds risk band and highlighted signals; batch takes up to 50 |
| `POST /feedback` | Optional anonymous label correction, off by default; never accepts message text |

```bash
curl -X POST http://127.0.0.1:8000/predict -H 'Content-Type: application/json' \
  -d '{"message":"BDO: Your account is locked. Verify here: http://bit.ly/fakebdo"}'
```

## Development

```bash
pytest -q && ruff check . && ruff format --check . && mypy src api
```

`make help` lists common commands. `python -m src.train --help` and
`python -m src.evaluate --help` list every option.

## Adding consented Philippine messages

No consented Philippine messages are currently included. Use the blank
[intake template](data/templates/consented_ph_sms_template.csv) only in an
approved encrypted workspace, verify revocable consent and its permitted use,
redact personal details, and have two reviewers label each message with an
independent adjudicator for disagreements. Keep consent records separate from
message data, apply a retention deadline, and remove derived artifacts when
consent is withdrawn. Run the local-only preflight before using a batch:

```bash
python -m src.consented_data /secure/workspace/consented_batch.csv --purpose training
```

The preflight reports aggregate counts and row/rule codes only; it cannot prove
consent or detect every identifier. Keep a campaign-separated evaluation batch
out of training and threshold selection. See
[docs/DATA_COLLECTION.md](docs/DATA_COLLECTION.md) for the full workflow and
privacy limits.

## Documentation

[Model card and limitations](docs/MODEL_CARD.md) ·
[Data collection and consented import](docs/DATA_COLLECTION.md) ·
[Dataset inventory](docs/DATASET_INVENTORY.md) ·
[Deployment](docs/DEPLOYMENT.md) · [Retraining](docs/RETRAINING.md) ·
[Privacy](docs/PRIVACY.md) · [Human review](docs/HUMAN_REVIEW.md)

```text
src/             data validation, features, model selection, training, metrics, inference
api/             FastAPI app (main, routes, schemas) and api/web/ single-page UI
data/raw/        tracked synthetic PH fixtures; real data and imports are git-ignored
data/templates/  consented-collection template
scripts/         synthetic data generation, curation, demo smoke test
docs/            model card, data, deployment, privacy, retraining, review
```
