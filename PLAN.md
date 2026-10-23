# Project Plan: Philippine SMS Spam and Scam Detector

## Goal
Build and validate a maintainable spam-versus-ham SMS classifier that supports scam awareness while minimizing false positives on legitimate Philippine messages, especially OTPs and account alerts. A spam score is not a fraud probability or a finding about a sender.

## Phase 1: Prepare the dataset

- Use the documented UCI import only after reviewing its source and CC BY 4.0 terms, or provide another corpus after independently verifying its terms. The ignored `data/raw/spam.csv` has unknown provenance until verified; a compatible schema does not prove its source.
- Confirm the file uses `v1`/`v2` or `label`/`message` columns and labels map to `spam` and `ham`.
- Add Philippine examples only when they are labeled and sourced responsibly. Include both scams and legitimate messages such as OTPs, bank alerts, delivery notices, and everyday Tagalog/Taglish messages.
- Keep real SMS text out of Git and reports. Collect only under documented consent, mask before storage, and follow the revocation, retention, review, and deletion workflow in `docs/DATA_COLLECTION.md`.
- Record dataset source, collection date, labeling method, and any known sampling bias.

**Deliverable:** documented, usable CSV with both classes and representative Philippine messages.

## Phase 2: Inspect and prepare the data

- Inspect the message-free source manifest and evaluation coverage for class balance, duplicates, metadata gaps, and group isolation.
- Check that train/test splitting keeps both classes represented.
- Review the preprocessing rules for Taglish normalization, phone numbers, URLs, currency, and urgency words.
- Save any approved cleaned or derived data under `data/processed/`; preserve the original source data.

**Deliverable:** EDA findings and a reproducible dataset preparation decision.

## Phase 3: Train baseline and primary models

- Install the pinned environment described in `README.md`, then import a source with known provenance using `python -m src.import_public_dataset` or the consented-data workflow.
- Train with `python -m src.train --data <approved.csv>`; the current workflow compares class-balanced LogisticRegression and LinearSVC with a MultinomialNB baseline, selects features and calibration inside group-aware folds, and uses validation-only threshold selection.
- Review the message-free manifest, per-class metrics, false positives on legitimate categories, calibration diagnostics, and uncertainty. Keep the final test groups out of feature, calibration, and threshold choices.
- Use `make benchmark DATA=<approved.csv>` for an isolated artifact, metadata, manifest, and report run. The default model path and synthetic supplements are configurable; do not describe synthetic-only results as Philippine field accuracy.

**Deliverable:** versioned model artifact, sidecar provenance, and reproducible evaluation report.

## Phase 4: Validate Philippine scam coverage

- Run `python -m src.evaluate --data <approved.csv> --holdout <independent.csv> --json-out <report.json>`; add `--plot <path>` when a confusion-matrix image is useful.
- Treat tracked Philippine fixtures and generated prompts as synthetic diagnostics, not as a substitute for a consented labeled test set.
- Build a Philippine holdout set containing scams, legitimate OTPs, bank messages, and ordinary Tagalog/Taglish texts.
- Measure precision and recall by message type and inspect errors for leakage, duplicates, and source bias.
- Add new scam patterns only with representative labeled examples; avoid rules that flag legitimate messages solely because they contain a link, amount, or phone number.

**Deliverable:** documented performance on a representative local holdout set and a prioritized error list.

## Phase 5: Serve predictions through the API

- Start the service with `smsd-serve` (or `make serve`) after training.
- Check `/health`, `/ready`, and `/model-info`, then send a request to `/analyze` or `/predict` with a fictional sample message.
- Confirm the prediction, spam score, calibration indicator, thresholds, and signal flags; a calibrated spam score is not a probability of fraud.
- Confirm empty and oversized requests receive validation errors, and missing model artifacts produce a clear service error.

**Deliverable:** locally running API with verified request and response behavior.

## Phase 6: Operational readiness

- Add automated tests for preprocessing, feature extraction, model loading, API validation, and prediction response behavior.
- Pin dependency versions after confirming the environment and record the Python version used to train the artifact.
- Establish a process for reviewing false positives and false negatives, updating labels, retraining, and comparing model versions.
- Keep user messages private, define retention limits, and avoid using predictions as the sole basis for blocking or reporting messages.
- Deploy only after local holdout performance and privacy practices meet the project's requirements.

**Deliverable:** tested, reproducible release process with monitoring and data-handling practices.

## Remaining validation work

1. Verify provenance and usage terms for the operator-supplied base corpus; otherwise leave it labeled `unknown`.
2. Collect a sufficiently broad Philippine set only through the documented consent and privacy workflow.
3. Hold out real campaigns and, where possible, later collection periods; keep that test set untouched.
4. Compare model versions on the same independent set before claiming a change in performance.
5. Reassess false positives on legitimate OTPs, bank alerts, delivery notices, promotions, and everyday messages.
6. Establish deployment monitoring and review using aggregate, privacy-safe outcomes.

The repository implements grouped splitting, validation-only threshold tuning, API validation, automated checks, opt-in browser history, and text-free correction reports. These engineering features do not establish real-world Philippine accuracy. Use `data_kind` (`synthetic`, `public`, `consented`, or `unknown`) to declare row provenance; legacy `real` is accepted as an alias for consented data. Missing provenance remains unknown. Scores are uncalibrated unless calibration is fitted and validated; detected text signals are not explanations of the model's decision.
