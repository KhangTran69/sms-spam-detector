# Philippines SMS Spam and Scam Detector

A Python 3.10+ pipeline that classifies SMS messages as `spam` or `ham`, tuned for Philippine traffic: Taglish text, PH mobile/landline numbers, `₱`/`PHP`/`pesos` amounts, urgency words, and locally common scam templates. It combines word/bigram TF-IDF with interpretable indicator features, trains a MultinomialNB baseline and a class-balanced LogisticRegression primary model, and serves both a JSON API and a bundled web UI through FastAPI.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Requires Python 3.10+ (developed and verified on 3.13). The training run expects `data/raw/spam.csv`.

## Dataset

Primary source: [Spam Text Message Classification on Kaggle](https://www.kaggle.com/datasets/anthonytherien/spam-text-message-classification). Kaggle downloads require a signed-in account — either download the CSV in a browser, or use the Kaggle CLI with your credentials and move the extracted CSV to `data/raw/spam.csv`.

That dataset is a re-upload of the public [UCI SMS Spam Collection](https://archive.ics.uci.edu/ml/datasets/sms+spam+collection) (5,574 English messages, 4,827 ham / 747 spam). Since Kaggle's API denied anonymous download, `data/raw/spam.csv` in this workspace was generated from the UCI original (same corpus), written with `label,message` columns. The loader also accepts Kaggle's `v1`/`v2` layout, so either file works.

`data/raw/` is git-ignored except the two synthetic Philippine files below. Do not commit real personal message data.

## Philippine supplement and holdout

- `data/raw/ph_supplement.csv` and `data/raw/ph_supplement_2.csv` — **synthetic, template-based** labeled examples merged into training. They cover prize/foundation claims, bank and e-wallet impersonation, parcel-fee and SIM-registration phishing, job/loan/investment lures, OTP-forwarding social engineering, Taglish variants, and legitimate OTPs, account notices, deliveries, and everyday messages. These templates are for pipeline verification, not a representative sample of real Philippine traffic.
- `data/raw/ph_holdout.csv` — a small disjoint labeled set used by `src/evaluate.py` to report local precision, including how many legit OTP/code messages get falsely flagged.

To add the real Philippine patterns you collect: append `label,message` rows to a supplement (both classes — include legitimate OTPs and bank alerts as `ham`), keep the holdout separate, and retrain. A data-quality test asserts the supplements and holdout stay disjoint and that the three diagnostic examples below never appear in them.

## Train

```bash
python -m src.train
# Options:
python -m src.train --data data/raw/spam.csv --supplement data/raw/ph_supplement.csv --output models/spam_detector_v1.pkl
python -m src.train --supplement none   # base dataset only
```

Training merges the base CSV with both available Philippine supplements by default (exact duplicate messages dropped), reports a MultinomialNB baseline and the LogisticRegression primary (`class_weight='balanced'`), and saves the fitted primary pipeline with joblib to `models/spam_detector_v1.pkl`. Pass one or more paths with `--supplement`; use `--supplement none` to disable supplements.

Measured on the current data (5,284 unique messages; stratified 80/20 split, seed 42):

| Model | Spam precision | Spam recall | Accuracy |
|---|---|---|---|
| MultinomialNB (baseline) | 0.96 | 0.77 | 0.97 |
| LogisticRegression (primary) | 0.96 | 0.95 | 0.99 |

## Evaluate

```bash
python -m src.evaluate
# Options: --data --supplement --model --holdout --plot (pass 'none' to disable supplement/holdout/plot)
```

Evaluation replicates the training split so metrics come from the held-out test set only, then prints a classification report, spam precision, a confusion matrix (saved to `data/processed/confusion_matrix.png`), a **threshold sweep** for precision-focused operation, the Philippine holdout results, and the three diagnostic examples from the project brief.

Current threshold sweep (test split):

| Threshold | Spam precision | Spam recall | FP (ham→spam) | FN (spam→ham) |
|---|---|---|---|---|
| 0.50 | 0.96 | 0.95 | 5 | 7 |
| 0.70 | 1.00 | 0.85 | 0 | 21 |

At the default 0.5 threshold the model already produced **zero false positives on legit OTP/code messages** in the Philippine holdout (18/18 correct). If your deployment prioritizes precision over recall — the project brief's goal of not flagging legitimate OTPs — operate at a higher cut-off such as 0.70: the sweep reports 1.00 precision with 0 false positives at the cost of missed spam. The sweep output names the smallest tested threshold reaching precision ≥ 0.99.

## Predict (CLI)

```bash
python -m src.predict "BDO: Your account is locked. Verify here: http://bit.ly/fakebdo"
# {"prediction": "spam", "probability": ..., "flags": ["has_url"]}
```

`probability` is the model's probability for the returned class. `flags` can include `has_url`, `has_phone`, `has_money`, `has_urgency`.

## API

Train the model first, then run:

```bash
uvicorn api.main:app --reload
# then open http://127.0.0.1:8000 for the web UI
```

```bash
curl -X POST http://127.0.0.1:8000/predict \
  -H 'Content-Type: application/json' \
  -d '{"message":"Nag-claim ka ng ₱500,000 sa GMA Kapuso Foundation. Call now 09123456789"}'
# {"prediction":"spam","probability":0.996,"flags":["has_phone","has_money","has_urgency"]}

curl -X POST http://127.0.0.1:8000/analyze \
  -H 'Content-Type: application/json' \
  -d '{"message":"BDO: account locked agad! Verify http://bit.ly/fake or call 09171234567"}'
```

- `GET /health` — liveness check.
- `POST /predict` — minimal verdict: `prediction`, `probability` (of the returned class), `flags`. Pydantic validation: message required, 1–10,000 characters and not blank; violations return 422. If the model artifact is missing the service returns 503 with instructions. The model loads lazily on first request and is reused.
- `POST /analyze` — full analysis for the UI: everything `/predict` returns plus `message` (echo), `spam_probability` (raw P(spam)), `matches` (non-overlapping highlight spans `{"type","text","start","end"}` for url/phone/money/urgency/brand), and `brands` (lowercased unique brand mentions).
- `POST /analyze/batch` — `{"messages": [...]}` with 1–50 messages; returns `{"count", "results"}` with one `/analyze`-shaped result per message, index-aligned.
- Interactive docs at `http://127.0.0.1:8000/docs`.

## Web UI

The API also serves a bundled single-page app (no build step) from `web/` at `http://127.0.0.1:8000/`:

- **Paste-and-check** with a verdict card (Likely scam / Suspicious / Looks safe — bands at 0.70 / 0.40 over `spam_probability`, chosen to match the precision-first threshold guidance above) and a tri-zone risk meter.
- **Highlighted signals**: scam markers rendered inline from `matches` (links, phone numbers, peso amounts, urgency words, brand mentions) with a legend and an impersonation warning when a bank/e-wallet name appears in a risky message.
- **Safety tips** that adapt to the verdict and detected signals.
- **Batch check**: up to 50 messages, one per line, with a summary strip and a clickable results table (clicking a row opens the full analysis).
- **History**: the last 50 checks kept in browser `localStorage` (nothing is stored server-side); entries can be re-opened and the list cleared.

`src/predict.py` exposes this as `analyze_message()`; `predict_message()` keeps its minimal contract on top of it.

## Tests

```bash
python -m pytest tests/ -v
```

44 tests cover preprocessing (PH mobile/landline/masked numbers, money variants, urgency, Taglish normalization), the feature schema and ColumnTransformer output, a full train→save→load→predict round-trip on synthetic data, API validation and error behavior for all three endpoints (including batch limits and blank-message rejection), and data-quality checks on the supplement/holdout files (both classes present, mutually disjoint, brief examples excluded).

## Philippine scam patterns recognized

The preprocessing layer detects the *signals*; the learned model weighs them:

- **Money**: `₱500,000`, `PHP 1,250.00`, `500 pesos`, `P15,000`
- **Phones**: `09171234567`, `+63 917 123 4567`, `0917-123-4567`, masked `0922xxxxxxx`, `(02) 8-631-8000`
- **URLs**: `http://…`, `https://…`, `www.…` (normalized to a `URLTOKEN` so the domain itself doesn't matter)
- **Urgency**: `now`, `agad`, `limited`, `expires`
- **Taglish normalization**: Unicode NFKC + elongation squeezing (`napakaaa` → `napakaa`); Filipino vocabulary is preserved, not translated

Template categories in the supplement: fake prizes (GMA Kapuso Foundation, PCSO), bank/e-wallet impersonation (BDO, BPI, Metrobank, UnionBank, GCash, Maya) with account-lock or KYC verification lures, parcel/customs-fee phishing (LBC, J&T, PhilPost), SIM-registration deactivation threats, free load/data promos, work-from-home and loan offers, investment doubling scams, OTP-forwarding social engineering, relative-in-trouble (`tulong`) scams, and government-subsidy bait (DSWD, 4Ps, SSS). Legitimate counterparts (real OTP formats, receipts, bills, delivery notices) are labeled `ham` so links, amounts, and numbers alone do not make a message spam.

## Project layout

```
data/raw/            spam.csv (git-ignored), synthetic Philippine supplements and holdout (tracked)
data/processed/      evaluation artifacts (confusion matrix)
notebooks/01_eda.ipynb
src/preprocess.py    cleaning, Taglish normalization, indicator extraction, match spans
src/features.py      TF-IDF (1-2 grams) + scaled indicators via ColumnTransformer
src/train.py         dataset loading/merge, NB baseline + balanced LR, joblib persistence
src/evaluate.py      held-out metrics, threshold sweep, PH holdout, brief examples
src/predict.py       CLI inference + analyze_message (full UI payload)
api/main.py          FastAPI /health + /predict + /analyze + /analyze/batch, serves web/
web/                 single-page UI (index.html, styles.css, app.js — no build step)
tests/               pytest suite (44 tests)
```

## Limitations

The base corpus is English-heavy; the Philippine coverage comes from synthetic templates and has only been checked against an 18-message synthetic holdout — perfect scores there are a sanity check, not proof of real-world performance. Urgency words in legitimate messages still pull confidence toward the boundary (an OTP that ends with "Expires in 5 minutes." scores 0.565 `ham` vs 0.805 without it), which is exactly why the threshold sweep exists. Basic Taglish handling does not translate or deeply tokenize Filipino. Validate on consented, representative local data before any production use, and never block or report messages on model output alone.
