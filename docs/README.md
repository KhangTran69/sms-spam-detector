# Documentation

Operational and governance documentation for the Philippine SMS Spam/Scam
Detector. Start with the top-level [README](../README.md) for setup, current
evidence status, and API examples; this directory covers the
"how do we run and maintain this responsibly" questions.

| Document | What it answers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | High-level system architecture, offline ML pipeline, real-time inference flow, and feedback loops. |
| [DATA_COLLECTION.md](DATA_COLLECTION.md) | Consent and privacy controls, independent labeling, grouped chronological split, sealed-test custody, and withdrawal. |
| [DONATION_INTAKE.md](DONATION_INTAKE.md) | Optional local donation intake, consent configuration, retention, withdrawal, export, and DPA considerations. |
| [privacy-notice.md](privacy-notice.md) | Versioned donor-facing notice shown before an optional donation. |
| [DATASET_INVENTORY.md](DATASET_INVENTORY.md) | Message-free audit of the current workspace's sources, counts, provenance, coverage, and evidence limits. |
| [evaluation.md](evaluation.md) | Public corpus status, disposable end-to-end synthetic rehearsal, consented evaluation plan, one-shot sealed-test gates, and interpretation limits. |
| [BENCHMARKING.md](BENCHMARKING.md) | Reproducible training/evaluation commands and the dated UCI/synthetic benchmark and near-duplicate audit. |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Local setup, training, serving, Docker/compose, reverse proxy + TLS, environment variables, health/readiness, artifact mounting, rollback, and limits. |
| [MODEL_CARD.md](MODEL_CARD.md) | What the model is and is not for, training data provenance, evaluation caveats, threshold/confidence guidance, known failure modes, fairness, and ethics. |
| [RETRAINING.md](RETRAINING.md) | Retraining cadence and triggers, validation gates, artifact versioning, reproducible splits, monitoring, incident response, and audit trail. |
| [PRIVACY.md](PRIVACY.md) | Prediction privacy, the optional consent-gated donation exception, opt-in browser history, logging rules, retention, and data-subject requests. |
| [HUMAN_REVIEW.md](HUMAN_REVIEW.md) | Consent-first review sessions, safe participant tasks, qualitative analysis, and release gates. |
| [IMPROVEMENT_EXECUTION.md](IMPROVEMENT_EXECUTION.md) | Current baseline reproduction, proposed provisional release criteria, collection plan, UX changes, and remaining pilot work. |

## Scope of current evidence

All Philippine data tracked in Git is synthetic; one public inbox corpus is
available locally but has not been evaluated. The consented split/evaluation
workflow is implemented, but no consented corpus or trained artifact exists.
No Philippine field performance has been established. The canonical statement of limitations is
[MODEL_CARD.md §4](MODEL_CARD.md#4-evaluation-and-the-synthetic-only-caveat).
The top-level [README evaluation section](../README.md#evaluation) summarizes
the current state; dataset-specific instructions and quality gates are in
[evaluation.md](evaluation.md) and [DEPLOYMENT.md](DEPLOYMENT.md).
