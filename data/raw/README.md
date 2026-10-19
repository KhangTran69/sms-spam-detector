# Data directory — schema, provenance, and privacy

`data/raw/` is for **raw source data**. Everything here is Git-ignored except
the synthetic, shareable Philippine files listed below and this README.

## Tracked files

| File | Kind | Purpose |
|---|---|---|
| `ph_supplement.csv` | synthetic templates | Small Taglish/English scam + legitimate patterns merged into training. |
| `ph_supplement_2.csv` | synthetic templates | Larger categorized set (prize, bank phishing, delivery, loan, job, romance, load, investment, impersonation, legitimate). |
| `ph_supplement_3.csv` | synthetic templates | Additional labeled scam and legitimate patterns with source/category metadata. |
| `ph_holdout.csv` | synthetic benchmark | Disjoint-by-message holdout with `category`, `language`, `source`, and `labeling_confidence` metadata. Used only for evaluation, never training. |
| `spam.csv` (not tracked) | public corpus | UCI/Kaggle English SMS Spam Collection (`label,message` or `v1,v2`). Download separately. |

**None of these files are a representative sample of real Philippine SMS
traffic.** They exist so the pipeline, tests, and evaluation harness can run
reproducibly. Do not quote their scores as real-world accuracy.

## Labeled CSV schema

Required columns (case-insensitive, one of these layouts):

- `label,message`
- `label,text`
- Kaggle SMS Spam Collection: `v1` (label), `v2` (message)

Labels are normalized to `ham` / `spam`; accepted aliases include `legit`,
`legitimate`, `scam`, `phishing`, and `0`/`1`.

Optional metadata columns (used by evaluation breakdowns when present):

| Column | Examples | Notes |
|---|---|---|
| `source` | `synthetic_template`, `consented_2026_q1` | Provenance group, not a person. |
| `category` | `otp`, `bank_alert`, `delivery`, `prize_scam` | Message type / campaign category. |
| `language` | `en`, `tl`, `taglish` | Do not infer personally identifying dialect details. |
| `labeling_confidence` | `high`, `medium`, `low` | Human labeler confidence. |
| `received_at` | ISO-8601 timestamp | Required for `--split-by time`; collect only the date precision needed. |
| `group` / `template_family` / `campaign` | `gma-prize-2026a` | Explicit leakage-prevention group. If absent, a masked template key is derived automatically. |

Unknown/blank metadata becomes `unknown`; it is never invented.

## Validation behavior

The loader (`src/data.py`) fails with an actionable error on:

- a missing, empty, or non-CSV file;
- an unrecognized schema or empty message;
- unknown labels or the same message carrying conflicting labels;
- missing classes, or classes with fewer than two examples.

Exact duplicate messages are removed **before** splitting (first occurrence
kept) with a warning. The training/validation/test split is group-aware by
template family, so related examples do not cross split boundaries.

## Privacy rules for real data

- Collect only with consent and for a stated purpose.
- De-identify before saving: remove or mask names, full numbers, account
  numbers, addresses, OTPs, and any free-text identifiers. Keep a separately
  stored, access-controlled key only if re-identification is genuinely needed
  (normally it is not).
- Never commit raw personal SMS, sender numbers, or account data. Keep them
  outside Git (or in an approved, access-controlled store).
- Prefer hashed `message_id` + redacted text for error review; see
  `src.preprocess.redact_message`.
- Do not put real holdout messages into logs, notebooks, issues, or model
  metadata.

See `docs/DATA_COLLECTION.md` for the full consented collection, labeling, and
template-family process.
