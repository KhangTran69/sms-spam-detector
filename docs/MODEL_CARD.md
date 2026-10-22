# Model Card: Philippine SMS Spam/Scam Detector

Version: see `GET /model-info` (`model_version`, `artifact_schema_version`,
`trained_at`) and the sidecar for the configured artifact. Owner: repository
maintainers. Last reviewed: 2026-10-21.

## 1. What this model is

A text classifier that returns `spam` or `ham` for a single SMS message, plus a
spam score, signal flags, and highlighted spans (URLs, phone numbers,
money amounts, urgency words, brand names). It is a TF-IDF (word 1–2 grams +
character 3–5 grams) + indicator-feature pipeline. The primary classifier is
picked by cross-validated spam F1 from class-balanced `LogisticRegression` and
`LinearSVC` over a C grid, wrapped in sigmoid `CalibratedClassifierCV`, with a
`MultinomialNB` baseline. The model is **assistive**: it
points a reader at likely scam patterns.

## 2. Intended use

The classifier target is **spam versus ham**. A spam label can include unwanted advertising as well as suspected fraud; it does not independently establish that a message is a scam. The UI describes the result as a spam assessment and detected text patterns, not as a fraud finding or an explanation of which features caused the model's decision.

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
| `data/raw/ph_supplement.csv`, `_2.csv`, `_3.csv`, `_4.csv`, `_5.csv` | **Synthetic**, developer-authored Philippine scam and legitimate examples. `_2` was deduped and capped at 2 rows per template family (311 → 141). `_5` adds 129 generated rows from 20 families (`scripts/generate_synthetic_ph.py`) | 513 rows merged into training: ham 237, spam 276 | Yes (synthetic text only) |
| `data/raw/ph_holdout.csv` | **Synthetic** holdout: 264 rows (ham 124, spam 140), 23 generated families plus 46 earlier hand-written rows | Evaluation only, never training. Current exact/normalized message and group overlap checks report zero; style overlap remains possible | Yes |
| Real Philippine messages | **none collected yet.** `src/import_consented.py` and `data/templates/consented_ph_sms_template.csv` are ready, but no consented data exists | — | — |

> **All Philippine data in this repository is still synthetic.** Rebalancing,
> deduplication, and a larger holdout make the pipeline checks less fragile.
> They do not make holdout scores evidence of real-world accuracy: one author
> wrote both training and holdout templates, so style overlap remains.

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

No representative Philippine performance estimate is available. The tracked
Philippine messages were written by project authors; a synthetic holdout can
check code paths and known patterns, but does not establish performance on
recipient messages or future scam campaigns. The local base CSV has unknown
provenance. A checked-in public-corpus and synthetic diagnostic report records
its source hashes and exact evaluated artifact hash; it remains an engineering
reproducibility example, not an estimate of Philippine field performance. See
the [dataset inventory](DATASET_INVENTORY.md) for the workspace snapshot and
evidence limits.

When run, evaluation reports threshold-selected internal test metrics, false
positives on legitimate categories, language/category/message-length coverage,
and uncertainty. These describe only the input data and split recorded in that
run. A synthetic holdout is reported separately. Do not use it to select
features, calibrate the model, or tune a threshold.

### Metrics source

The local workspace snapshot and evaluation limits are recorded in [DATASET_INVENTORY.md](DATASET_INVENTORY.md). Model artifacts are ignored local files; their metadata is authoritative only for the exact artifact that was loaded. No real Philippine traffic has been evaluated.

## 5. Thresholds, precision, and confidence

The artifact stores a `decision_threshold` (classify as spam when the raw model
spam score reaches the threshold) and a
`suspicious_threshold` for the UI warning band; both are chosen on a validation
split with a precision-first objective (protect legitimate OTP/bank messages) and
are exposed by `GET /model-info`. `POST /analyze` returns a legacy field named
`spam_probability`; new artifacts record whether the spam-versus-ham score is
sigmoid-calibrated in `probability_calibrated`. The field name is retained for
API compatibility. Calibration concerns the spam/ham training labels and is
not a calibrated probability that a message is fraudulent. Legacy artifacts
may return an uncalibrated score.
The API includes that flag alongside `decision_threshold`, `margin`, `confidence`,
and `risk_band`; the UI reads it from the loaded artifact. Evaluation reports
use the same metadata for score terminology, and expose a `threshold_diagnostic`
that distinguishes a deliberately retained 0.5 threshold under the `cv-robust`
policy from an unexplained mismatch. The diagnostic also checks the recorded
validation candidate, adopted threshold, adoption boolean, configured policy,
and (for `cv-robust`) fold gains against the declared adoption rule. It reports
missing metadata separately from malformed metadata, candidate drift, and an
artifact-threshold mismatch. Data-hash and split-fingerprint warnings remain
separate evidence of input drift; equal hashes alone do not validate a
contradictory threshold record.

- Raising the threshold **increases precision** (fewer false alarms) and
  **decreases recall** (more missed scams). Lowering it does the opposite.
- Choose the operating point for the deployment's cost of errors, not for the
  best single F1. For "don't scare people with false alarms", move it up; for
  "catch as much as possible, review later", move it down.
- `probability` in `/predict` is a legacy field name for the score of the
  **returned class**. For new artifacts, the full feature and classifier
  pipeline is calibrated inside group-isolated training folds. The final test
  split is excluded from feature selection, calibration, and threshold choice.
- A calibrated score is calibrated only with respect to the spam/ham labels and
  procedure recorded by that artifact. It does not establish fraud probability,
  reliable performance on Philippine recipients, or a guarantee about a
  particular message. The UI exposes the artifact's calibration state in score
  wording and accessibility labels; detected signals are text patterns, not
  explanations of the model's decision.
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

## Appendix: training, evaluation, and artifact details

Moved here from the top-level README so it lives in one place.

The primary classifier is chosen by up to 5-fold group-aware cross-validated
spam F1 on the training split from class-balanced LogisticRegression (C in
0.3/1/3/10/30) and LinearSVC (C in 0.03/0.1/0.3/1), then wrapped in sigmoid
`CalibratedClassifierCV`. Feature extraction is fitted inside each calibration
fold, and training fails if group-isolated folds cannot keep both labels in
every fold. The decision threshold is 0.5 unless the
validation-tuned threshold improves out-of-fold F1 in every fold and by at
least 0.01 on average (`--threshold-policy cv-robust`, the default); use
`--threshold-policy validation` to restore the old behaviour.

Training validates schemas and labels, removes exact and normalized duplicates before splitting, keeps campaign/template groups together, tunes the decision threshold on validation data, and reports the final test metrics separately. The artifact contains the model, threshold, training/data provenance, and version metadata. The configured base file and five synthetic Philippine supplements are used by default when present; unknown provenance stays marked unknown.

Training records per-file source metadata and label/language/category/provenance coverage in the artifact and a message-free `models/*.manifest.json` sidecar. The manifest includes input/retained row counts, duplicates, file hashes, class counts, split method/seed/fingerprint, and whether metadata was unverified. Small per-class splits are flagged so scores with limited support are not mistaken for stable estimates. See the dated [dataset inventory](DATASET_INVENTORY.md) for this workspace's audited counts and provenance limits.

For real data with reliable `received_at` timestamps and campaign groups, chronological validation/test splits are available:

```bash
python -m src.train --split-by time
```

Time splits require valid dates for every row and fail if both classes cannot be represented. Use `--split-by group` for the default group-aware split. The random split option is diagnostic only and can leak related examples.

Evaluation reports precision, recall, F1, false positives, sample counts, and coverage by language, category, and message length (1–70, 71–160, and 161+ Unicode code points). Wilson intervals are marginal binomial intervals; optional campaign-group bootstrap intervals resample whole group IDs and are withheld below ten groups. A group ID derived from a template is only a campaign proxy, not evidence of independent real campaigns. Reports label each split from its declared provenance and omit SMS content from errors.

Use `python -m src.evaluate --stability-seeds 13 42 73 --json-out data/processed/stability.json` for repeated group-aware threshold stability checks. The final test groups are reserved first and excluded from these development-only refits; repeated validation metrics select their own thresholds and are not independent performance estimates. Preserve the seed list with the report. Synthetic diagnostics remain separate from real-world validation. Optional `--false-positive-cost` and `--false-negative-cost` training arguments must be supplied together; they configure an exploratory validation-only threshold choice and do not express an approved production policy.

New artifacts calibrate the full feature and classifier pipeline on group-
isolated training folds and report test calibration diagnostics. Calibration
does not yield a probability of fraud or guarantee reliability on unseen
traffic. Legacy artifacts may be uncalibrated; consult the loaded artifact's
`probability_calibrated` flag. Do not use synthetic or unknown-provenance
results as a real-world accuracy claim.

Run `python -m src.train --help` and `python -m src.evaluate --help` for all data, threshold, split, and output options.

### Provenance and preprocessing compatibility

CSV files may include `data_kind` with `synthetic`, `public`, `consented`, or `unknown` (the default); legacy `real` is accepted as consented data. This is a source declaration, not independent verification. Training records fitted-row counts by kind; `synthetic_training_data` is true when synthetic rows were used, false only when all fitted rows are declared public or consented, and null when their status is unknown. Tracked Philippine fixtures are explicitly synthetic.

Feature version 2.2.0 adds selectable word, character, or combined TF-IDF
representations; the default is now `combined`. A 2.1.0 word-only artifact is
accepted only when its fitted pipeline confirms the unchanged word-vectorizer
settings and input schema. Other incompatible feature contracts still require
retraining. When `SMSD_MODEL_SHA256` is configured, the loader hashes and
deserializes the same in-memory bytes; SHA-256 verifies byte identity only and
does not authenticate an untrusted pickle. This change has not been shown to
improve real-world accuracy.
