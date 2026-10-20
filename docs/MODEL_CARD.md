# Model Card: Philippine SMS Spam/Scam Detector

Version: see `GET /model-info` (`model_version`, `artifact_schema_version`,
`trained_at`) and the sidecar for the configured artifact. Owner: repository
maintainers. Last reviewed: 2026-10-20.

## 1. What this model is

A text classifier that returns `spam` or `ham` for a single SMS message, plus an
calibrated spam score, signal flags, and highlighted spans (URLs, phone numbers,
money amounts, urgency words, brand names). It is a TF-IDF (word 1–2 grams +
character 3–5 grams) + indicator-feature pipeline. The primary classifier is
picked by cross-validated spam F1 from class-balanced `LogisticRegression` and
`LinearSVC` over a C grid, wrapped in sigmoid `CalibratedClassifierCV`, with a
`MultinomialNB` baseline. The model is **assistive**: it
points a reader at likely scam patterns.

## 2. Intended use

The classifier target is **spam versus ham**. A spam label can include unwanted advertising as well as suspected fraud; it does not independently establish that a message is a scam. The UI uses scam-oriented safety language as a cautious aid, not as a fraud finding.

- **In scope:** helping a person decide whether an SMS looks like a scam; a
  warning UI; a triage aid for a human reviewer; research/teaching on SMS
  classification in a Philippine context.
- **Decision support only.** Show the prediction with uncertainty and detected
  signals, and let the human decide. A prediction must not be presented as proof
  that a sender is a criminal.
- **Out of scope:**
  - automated blocking, deletion, reporting, or account action;
  - law-enforcement, credit, employment, insurance, or immigration decisions;
  - filtering messages on behalf of a third party without their knowledge;
  - detecting all scams or guaranteeing safety;
  - operating on live OTPs/credentials (never send those anywhere);
  - non-SMS content (email, chat, voice transcripts) and languages it was not
    trained on.
- **Not a substitute for official channels.** Users should verify with their bank
  or the agency through official contact details.

## 3. Training data

| Source | What it is | Size / role | In Git? |
|---|---|---|---|
| `data/raw/spam.csv` | Operator-supplied English-style base file; its source/license are unknown until verified | Merged into training when present | No (git-ignored) |
| Verified UCI SMS Spam Collection | Public historical English SMS corpus, 5,574 rows, CC BY 4.0; importer does not download it | Supported import; not added by this change | No |
| `data/raw/ph_supplement.csv`, `_2.csv`, `_3.csv`, `_4.csv`, `_5.csv` | **Synthetic**, template-based Philippine scam and legitimate examples; `_4` adds 42 scam variants and `_5` adds 21 legitimate variants | Merged into training | Yes (template text only) |
| `data/raw/ph_holdout.csv` | **Synthetic**, small labeled diagnostic holdout | Evaluation only, never training | Yes |
| Real Philippine messages | none collected | — | — |

- The configured base file has unknown provenance in the audited workspace. A
  verified UCI import would be English-heavy and dated. The Philippine coverage comes from
  hand-written synthetic templates covering prize scams, bank/e-wallet
  impersonation, parcel-fee phishing, SIM-registration threats, job/loan/
  investment lures, OTP social engineering, and legitimate counterparts (OTPs,
  transaction alerts, delivery notices, Taglish conversation).
- **There is no representative real Philippine dataset in this project.** The
  synthetic templates were written by the project authors and are not a random
  sample of real traffic.
- See the [README](../README.md) and [DATA_COLLECTION.md](DATA_COLLECTION.md) for
  exact current counts, dedup behavior, and provenance details.

## 4. Evaluation and the synthetic-only caveat

- Current metrics come from: (a) a held-out split of the English base corpus +
  synthetic supplement, (b) a synthetic Philippine holdout, and (c) a
  synthetic-only benchmark reported separately. The trainer uses grouped splits
  so a template family cannot cross train/validation/test boundaries, and it
  flags holdout template-family overlap as an optimistic-score warning.
- **Caveat:** templates were written by the same people who chose the patterns;
  near-perfect synthetic-holdout results are a pipeline sanity check, not
  evidence of real-world accuracy. Real users' wording, sender IDs, and scam
  evolution will differ.
- The evaluation reports a threshold sweep, precision/recall, false positives on
  legitimate OTP/bank messages, source/category breakdown, and calibration
  diagnostics. The current workspace's measured numbers and caveats are in the
  dated dataset inventory; they are not representative real-world metrics.

### Metrics source

The dated, machine-specific workspace evaluation and its limitations are recorded in [DATASET_INVENTORY.md](DATASET_INVENTORY.md). It is a synthetic diagnostic comparison, not a representative Philippine evaluation. The model artifact metadata is the authoritative record for the deployed model version and its training run. No real Philippine traffic has been evaluated.

## 5. Thresholds, precision, and confidence

The artifact stores a `decision_threshold` (classify as spam when the raw model
spam score reaches the threshold) and a
`suspicious_threshold` for the UI warning band; both are chosen on a validation
split with a precision-first objective (protect legitimate OTP/bank messages) and
are exposed by `GET /model-info`. `POST /analyze` returns a legacy field named
`spam_probability`; in current artifacts it is a sigmoid-calibrated score
(`probability_calibrated: true`), alongside `decision_threshold`, `margin`, `confidence`, and
`risk_band`.

- Raising the threshold **increases precision** (fewer false alarms) and
  **decreases recall** (more missed scams). Lowering it does the opposite.
- Choose the operating point for the deployment's cost of errors, not for the
  best single F1. For "don't scare people with false alarms", move it up; for
  "catch as much as possible, review later", move it down.
- `probability` in `/predict` is a legacy field name for the score of the
  **returned class**. Calibration is fitted on training folds only; on the
  UCI test split ECE fell from 0.083 (uncalibrated LogisticRegression) to
  0.016.
- **Do not treat scores as calibrated guarantees.** Calibration was measured on
  English UCI data and synthetic Philippine examples, not real Philippine traffic. Prefer qualitative bands (likely scam / suspicious / looks safe) in
  user-facing copy, over precise percentages.
- A model that changes threshold but not weights is still the same artifact
  version for audit purposes; record which operating point a deployment uses.

## 6. Language coverage

- English dominates training data.
- Taglish/Tagalog handling is **light**: NFKC normalization, elongation
  squeezing (`napakaaa` → `napakaa`), URL/amount/phone tokens, and a small
  indicator list. The model does **not** translate, morphologically analyze, or
  deeply tokenize Filipino, and diacritics/regional variants are not normalized
  comprehensively.
- Expect weaker performance on deep Tagalog, Cebuano/Bisaya, Ilocano, and mixed
  or romanized regional messages; do not claim multilingual capability.

## 7. Known failure modes

1. **Legitimate bank/e-wallet alerts** with a link, an amount, a brand name, and
   an urgency phrase ("expires now") are structurally similar to phishing;
   false positives here are the costliest error.
2. **OTP messages** with urgency words can drift toward the boundary; the model
   is tuned to keep these as ham, but check them first when reviewing errors.
3. **New scam templates** not represented in synthetic data or UCI corpus;
   performance is unknown and likely lower.
4. **Adversarial evasion**: typos, spacing, homoglyphs, emoji, splitting amounts
   (`P5O,OOO`), or "polite" wording that removes classic markers.
5. **Short messages** (a bare link or amount) provide little signal; rely on the
   human and the highlighted signals, not the verdict alone.
6. **Sender ID context is unavailable**; the model sees text only.
7. **Class imbalance and corpus bias**: the English corpus and synthetic PH
   templates skew toward certain scam shapes and formal English; informal
   legitimate Filipino conversation is underrepresented.
8. **Masked numbers/links** reduce signal; a legit alert with masked identifiers
   may look more suspicious or less.
9. **Batch analysis** returns independent per-message verdicts; it does not model
   conversation context across messages.

## 8. Fairness and privacy

- No demographic attributes (age, gender, income, ethnicity, location) are
  collected or used. Fairness is therefore evaluated by **message category and
  language**, not by demographic subgroup; if demographics are ever inferred,
  that is a risk to document, not a feature.
- The biggest equity risk is **over-flagging legitimate financial notifications**
  (people who depend on SMS banking/OTPs) and **under-flagging** messages in
  languages/registers unlike the training data.
- No server-side message storage; browser history is opt-in and local. See
  [PRIVACY.md](PRIVACY.md).
- Real message data is never committed; see
  [DATA_COLLECTION.md](DATA_COLLECTION.md).

## 9. Ethical use

- Present output as a **hint with evidence**, never as an accusation or a
  guarantee.
- Keep a human in the loop; provide an easy way to view the original message and
  the highlighted signals, and to disagree with the verdict.
- Never automate punishment (blocking a number, reporting an account, denying
  service) from this model. If downstream action is ever considered, require
  human review, an appeal path, and measured precision on real data first.
- Do not deploy in a way that reads people's private messages without their
  knowledge or consent.
- Be transparent about limitations: synthetic evaluation, English-heavy corpus,
  shallow Taglish support, and the absence of real Philippine validation.
- Revisit this card on every retrain and at least annually; record the artifact
  version and evaluation date.

## 10. Maintenance

Retraining cadence, validation gates, rollback, and monitoring are in
[RETRAINING.md](RETRAINING.md). When the artifact changes, preserve its sidecar
metadata and update the versioned evaluation record and this card's version
references.

## Positive-label interpretation

The classifier learns `spam` versus `ham`. A `spam` prediction can describe
unsolicited advertising as well as suspected fraud; it does not by itself show
that a message is a scam or that a sender is malicious. User-facing warnings
are decision support. Verify with the sender through independently obtained
official contact details.
