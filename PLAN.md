# Project Plan: Philippine SMS Spam and Scam Detector

## Goal
Build and validate a maintainable SMS classifier that identifies spam and scams while minimizing false positives on legitimate Philippine messages, especially OTPs and account alerts.

## Phase 1: Prepare the dataset

- Download the Kaggle Spam Text Message Classification CSV and save it as `data/raw/spam.csv`.
- Confirm the file uses `v1`/`v2` or `label`/`message` columns and labels map to `spam` and `ham`.
- Add Philippine examples only when they are labeled and sourced responsibly. Include both scams and legitimate messages such as OTPs, bank alerts, delivery notices, and everyday Tagalog/Taglish messages.
- Remove or mask personal information before committing or sharing data. Keep raw data out of Git.
- Record dataset source, collection date, labeling method, and any known sampling bias.

**Deliverable:** documented, usable CSV with both classes and representative Philippine messages.

## Phase 2: Inspect and prepare the data

- Run `notebooks/01_eda.ipynb` to inspect class balance, message lengths, duplicates, and label quality.
- Check that train/test splitting keeps both classes represented.
- Review the preprocessing rules for Taglish normalization, phone numbers, URLs, currency, and urgency words.
- Save any approved cleaned or derived data under `data/processed/`; preserve the original source data.

**Deliverable:** EDA findings and a reproducible dataset preparation decision.

## Phase 3: Train baseline and primary models

- Install dependencies from `requirements.txt` in a Python 3.10+ virtual environment.
- Run `python -m src.train` to compare MultinomialNB with class-balanced LogisticRegression.
- Review per-class precision, recall, F1, and especially false positives on legitimate messages.
- Save the primary pipeline to `models/spam_detector_v1.pkl`.
- If false positives are too high, evaluate a higher spam decision threshold using a held-out validation set; document the selected threshold and update prediction behavior consistently.

**Deliverable:** versioned model artifact and recorded validation metrics.

## Phase 4: Validate Philippine scam coverage

- Run `python -m src.evaluate --data data/raw/spam.csv --plot data/processed/confusion_matrix.png`.
- Review the three built-in Philippine scam examples as diagnostic cases, not as a substitute for a labeled test set.
- Build a Philippine holdout set containing scams, legitimate OTPs, bank messages, and ordinary Tagalog/Taglish texts.
- Measure precision and recall by message type and inspect errors for leakage, duplicates, and source bias.
- Add new scam patterns only with representative labeled examples; avoid rules that flag legitimate messages solely because they contain a link, amount, or phone number.

**Deliverable:** documented performance on a representative local holdout set and a prioritized error list.

## Phase 5: Serve predictions through the API

- Start the service with `uvicorn api.main:app --reload` after training.
- Check `/health`, then send a request to `/predict` with a sample message.
- Confirm response schema, predicted class probability, and indicator flags.
- Confirm empty and oversized requests receive validation errors, and missing model artifacts produce a clear service error.

**Deliverable:** locally running API with verified request and response behavior.

## Phase 6: Operational readiness

- Add automated tests for preprocessing, feature extraction, model loading, API validation, and prediction response behavior.
- Pin dependency versions after confirming the environment and record the Python version used to train the artifact.
- Establish a process for reviewing false positives and false negatives, updating labels, retraining, and comparing model versions.
- Keep user messages private, define retention limits, and avoid using predictions as the sole basis for blocking or reporting messages.
- Deploy only after local holdout performance and privacy practices meet the project's requirements.

**Deliverable:** tested, reproducible release process with monitoring and data-handling practices.

## Immediate next steps

1. Download the Kaggle CSV into `data/raw/spam.csv`.
2. Run the EDA notebook and record dataset limitations.
3. Add labeled Philippine scam and legitimate-message examples when available.
4. Train and compare models, then inspect false positives.
5. Evaluate against a Philippine holdout set before relying on predictions.
6. Start the API and verify its behavior locally.
