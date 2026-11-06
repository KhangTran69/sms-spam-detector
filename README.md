# Philippine SMS Spam and Scam Detector

An assistive spam-versus-ham SMS classifier, API, and web app for Philippine
English, Filipino, and Taglish. Spam includes unwanted advertising as well as
suspected fraud; a model score is not a probability that a message is a scam.
Verify suspicious requests through trusted official channels.

![Demo: checking a single message, a batch, and the Taglish dark theme](docs/images/demo.gif)

> **Evidence limit:** every Philippine message tracked in this repository is synthetic,
> and the public UCI corpus is English. A public one-person Philippine inbox
> has been retrieved locally (1,664 normalized rows) but has not been evaluated
> and is not representative. Existing scores are
> engineering checks, not real-world accuracy. The tool is assistive only: do not block, report, or
> penalize anyone based on a prediction. Full limitations:
> [docs/MODEL_CARD.md §4](docs/MODEL_CARD.md#4-evaluation-and-the-synthetic-only-caveat).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r constraints/py3.12.txt -e ".[dev]"
make demo
SMSD_MODEL_PATH=models/demo_synthetic.pkl make serve
```

Open <http://127.0.0.1:8000/>. This local demo trains only from tracked
synthetic Philippine fixtures; its scores are not performance evidence. The
server runs in the foreground and stops with Ctrl-C. For full training,
production setup, or a persistent macOS service, see
[deployment](docs/DEPLOYMENT.md).

An optional, local-only XLM-RoBERTa ensemble research spike is documented in
the [benchmark runbook](docs/BENCHMARKING.md#optional-local-transformer-spike).
It is disabled unless configured by the operator and has not passed the
real-holdout promotion gate in the [model card](docs/MODEL_CARD.md).

## Evaluation

The versioned [UCI and synthetic diagnostic report](docs/benchmarks/uci-synthetic-ph-diagnostic-20261022.json)
separates public English results from synthetic Philippine fixture checks. It
was generated from a dirty source tree and is an engineering reproducibility
example, not real-world accuracy. The local Philippine public inbox remains
unevaluated; it represents one person's messages, not Philippine traffic. No
consented Philippine messages or real-world performance estimate are available.
See [evaluation methods and data status](docs/evaluation.md) and the
[dataset inventory](docs/DATASET_INVENTORY.md). The reproducible clean-main
run and its near-duplicate audit are documented in the
[benchmark runbook](docs/BENCHMARKING.md).

## API

The versioned routes use `/v1/*`; root aliases remain available for
backwards compatibility. Interactive API documentation is at `/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /health`, `GET /ready` | Liveness and model readiness |
| `GET /model-info` | Model version, thresholds, provenance, caveats, and optional ensemble configuration status |
| `POST /predict` | Spam/ham label, score, calibration flag, signals, and selected `model_path` |
| `POST /analyze`, `POST /analyze/batch` | Risk band, highlighted text patterns, and per-result `model_path`; batch supports up to 50 messages |
| `POST /feedback` | Optional correction labels; disabled by default and never accepts SMS text |
| `GET /donate`, `POST /donate`, `DELETE /donate` | Separate consented local intake; disabled by default |

Example request:

```bash
curl -X POST http://127.0.0.1:8000/predict -H 'Content-Type: application/json' \
  -d '{"message":"BDO: Your account is locked. Verify here: http://bit.ly/fakebdo"}'
```

## Web app and privacy

The no-build UI supports single-message, batch, and comparison checks. Privacy
Preview runs in the browser; history is opt-in and browser-local. Prediction
requests are processed in memory and are not logged, persisted, or cached by the
app. Full details about comparison, masking, the safety checklist, history, and
storage limits are in the [privacy guide](docs/PRIVACY.md). Demo examples are
fictional and sourced from tracked synthetic fixtures; see
[architecture](docs/ARCHITECTURE.md).

Donation intake is a separate, local-only workflow, disabled by default and
unavailable in production. It does not turn submitted messages into labels or
training data. See [collection guidance](docs/DATA_COLLECTION.md), the
[operator guide](docs/DONATION_INTAKE.md), and the
[versioned privacy notice](docs/privacy-notice.md). These documents do not
establish legal compliance; obtain qualified review before collection.

## Development

```bash
make lint
make typecheck
make test
npm ci && npm run test:modules && npm run test:browser
python scripts/wheel_smoke.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and checks. The
[documentation index](docs/README.md) links to the model card, evaluation,
privacy, deployment, collection, and maintenance guides.

| | |
|---|---|
| ![Likely spam result](docs/images/02-likely-scam.png) | ![Looks safe result](docs/images/03-looks-safe.png) |
| ![Batch check](docs/images/04-batch.png) | ![Taglish, dark theme](docs/images/05-dark-taglish.png) |

Licensed under the MIT License; see [LICENSE](LICENSE). Bundled datasets retain their own licenses — see [docs/DATASET_INVENTORY.md](docs/DATASET_INVENTORY.md).
