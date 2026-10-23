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
| [IMPROVEMENT_EXECUTION.md](IMPROVEMENT_EXECUTION.md) | Current baseline reproduction, proposed provisional release criteria, collection plan, UX changes, and remaining pilot work. |

## Scope of current evidence

All Philippine data is synthetic and no real Philippine traffic has been
evaluated. The canonical statement of limitations is
[MODEL_CARD.md §4](MODEL_CARD.md#4-evaluation-and-the-synthetic-only-caveat).
Measured numbers live only in the top-level [README](../README.md#results).
Setup and quality-gate commands are in the README [Quickstart](../README.md#quickstart).
