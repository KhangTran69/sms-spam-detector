# Project Plan: Philippine SMS Spam and Scam Detector

## Goal
Build and validate a maintainable SMS classifier that identifies spam and scams while minimizing false positives on legitimate Philippine messages, especially OTPs and account alerts.

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

- Install dependencies from `requirements.txt` in a Python 3.11+ virtual environment.
- Run `python -m src.train` to compare MultinomialNB with class-balanced LogisticRegression.
- Review per-class precision, recall, F1, and especially false positives on legitimate messages.
- Save the primary pipeline to `models/spam_detector_v1.pkl`.
- If false positives are too high, evaluate a higher spam decision threshold using a held-out validation set; document the selected threshold and update prediction behavior consistently.

**Deliverable:** versioned model artifact and recorded validation metrics.

## Phase 4: Validate Philippine scam coverage

- Run `python -m src.evaluate --data data/raw/spam.csv --plot data/processed/confusion_matrix.png`.
- Treat the three built-in Philippine prompts as synthetic diagnostics, not as a substitute for a consented labeled test set.
- Build a Philippine holdout set containing scams, legitimate OTPs, bank messages, and ordinary Tagalog/Taglish texts.
- Measure precision and recall by message type and inspect errors for leakage, duplicates, and source bias.
- Add new scam patterns only with representative labeled examples; avoid rules that flag legitimate messages solely because they contain a link, amount, or phone number.

**Deliverable:** documented performance on a representative local holdout set and a prioritized error list.

## Phase 5: Serve predictions through the API

- Start the service with `uvicorn api.main:app --reload` after training.
- Check `/health`, then send a request to `/predict` with a sample message.
- Confirm response schema, uncalibrated model score, and indicator flags.
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
