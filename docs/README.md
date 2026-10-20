# Documentation

Operational and governance documentation for the Philippine SMS Spam/Scam
Detector. Start with the top-level [README](../README.md) for setup, current
dataset details, measured metrics, and API examples; this directory covers the
"how do we run and maintain this responsibly" questions.

| Document | What it answers |
|---|---|
| [DATA_COLLECTION.md](DATA_COLLECTION.md) | How message data is collected, consented, masked, labeled, grouped, stored, and separated into synthetic vs. real data. |
| [DATASET_INVENTORY.md](DATASET_INVENTORY.md) | Message-free audit of the current workspace's sources, counts, provenance, coverage, and evidence limits. |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Local setup, training, serving, Docker/compose, reverse proxy + TLS, environment variables, health/readiness, artifact mounting, rollback, and limits. |
| [MODEL_CARD.md](MODEL_CARD.md) | What the model is and is not for, training data provenance, evaluation caveats, threshold/confidence guidance, known failure modes, fairness, and ethics. |
| [RETRAINING.md](RETRAINING.md) | Retraining cadence and triggers, validation gates, artifact versioning, reproducible splits, monitoring, incident response, and audit trail. |
| [PRIVACY.md](PRIVACY.md) | Data minimization, no server-side message persistence, opt-in browser history, logging rules, retention, and data-subject requests. |
| [HUMAN_REVIEW.md](HUMAN_REVIEW.md) | Consent-first review sessions, safe participant tasks, qualitative analysis, and release gates. |

## Read this first: scope of current evidence

- The ignored base corpus in a developer's workspace has **unverified
  provenance** until its source and terms are checked. The supported verified
  import is the public **UCI SMS Spam Collection** (English, CC BY 4.0); its
  importer does not download data. The Philippine coverage in this repository
  is **synthetic, template-based** data written to exercise the pipeline.
- **No representative real-world Philippine SMS dataset has been collected or
  evaluated.** Every number currently reported is a synthetic/UCI test-set or
  synthetic-holdout number. See [MODEL_CARD.md](MODEL_CARD.md) and the
  [README](../README.md) metrics section (the README is the source of truth for
  measured numbers; this directory deliberately does not duplicate them).
- This project is a portfolio/engineering prototype. It is **assistive only**:
  do not block, delete, report, or penalize anyone based solely on a prediction.
- Real personal message data must never be committed. Only the synthetic
  Philippine CSVs are tracked in Git; `data/raw/spam.csv` and `models/*` are
  git-ignored.

## Canonical commands

```bash
# Setup (Python >= 3.11; verified on 3.13)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Train / evaluate / serve
python -m src.train
python -m src.evaluate
uvicorn api.main:app --host 127.0.0.1 --port 8000

# Quality gates
pytest -q
ruff check . && ruff format --check .
mypy src api
```

`make <target>` wraps the same commands ([Makefile](../Makefile)); run
`python -m src.train --help` and `python -m src.evaluate --help` for the
authoritative flags of the current revision.
