# Data directory — schema, provenance, and privacy

`data/raw/` is for **raw source data**. Everything here is Git-ignored except
the synthetic, shareable Philippine files listed below and this README.

## Tracked files

| File | Kind | Purpose |
|---|---|---|
| `ph_supplement.csv` | synthetic templates | Small Taglish/English scam + legitimate patterns merged into training. |
| `ph_supplement_2.csv` | synthetic templates | Larger categorized set (prize, bank phishing, delivery, loan, job, romance, load, investment, impersonation, legitimate). |
| `ph_supplement_3.csv` | synthetic templates | Additional labeled scam and legitimate patterns with source/category metadata. |
| `ph_supplement_4.csv` | synthetic scam templates | 42 new fictional scam-only variations across seven categories, three languages, and 14 campaign-family groups. Uses reserved `example.com` URLs and bracketed placeholders; automatically included in default training. |
| `ph_supplement_5.csv` | synthetic mixed templates | 150 fictional rows: 21 hand-written legitimate examples plus 129 generated examples from 20 families. Automatically included in default training. |
| `ph_holdout.csv` | synthetic benchmark | Disjoint-by-message holdout with `category`, `language`, `source`, and `labeling_confidence` metadata. Used only for evaluation, never training. |
| `spam.csv` (not tracked) | unknown until verified | Operator-supplied base file. Its current provenance is unverified; do not assume it is the UCI corpus. |

**None of these files are a representative sample of real Philippine SMS
traffic.** They exist so the pipeline, tests, and evaluation harness can run
reproducibly. Do not quote their scores as real-world accuracy.

The fourth supplement adds 42 messages (all labeled `spam`): six each for bank
phishing, delivery, prize, job, loan, investment, and impersonation scams.
Each category has two campaign-family groups with three wording variants per
group. Variants stay together during grouped splitting. The messages are
developer-authored synthetic training material, not collected SMS and not an
independent evaluation set. They do not change `ph_holdout.csv`.

The fifth supplement contains 21 hand-written, developer-authored legitimate
examples plus 129 generated examples from 20 campaign families. The 21 hand-
written messages cover OTP, bank, delivery, bill, promotion, school/work, and
personal categories in English, Filipino, and Taglish. The full file remains
synthetic and does not represent the natural distribution of Philippine
messages. The current local counts and hashes are in
[`docs/DATASET_INVENTORY.md`](../../docs/DATASET_INVENTORY.md).

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
| `group` / `template_family` / `campaign` | `campaign_opaque_a1` | Explicit leakage-prevention group. For consented data, use an opaque pseudonym. If absent, a masked template key is derived automatically. |
| `data_kind` | `synthetic`, `public`, `consented`, `unknown` | Declared provenance class; declaration is not independent verification. Legacy `real` is accepted as an alias for consented data. |
| `dataset_id`, `dataset_version`, `license`, `collection_period` | UCI metadata | Source-level attribution; these must be consistent within the file. |

Unknown/blank metadata becomes `unknown`; it is never invented.

For reproducible source attribution, imported CSVs can also provide
`dataset_id`, `dataset_version`, `license` (or `licence` / `usage_terms`), and
`collection_period`. These fields must be consistent within a file. The
training artifact and adjacent `.manifest.json` record each file's SHA-256,
input/retained/deduplicated row counts, label/language/category/provenance
counts, source metadata, and split fingerprint. The manifest contains no SMS
text. Missing source terms stay `unknown`.

## Importing the public UCI corpus

The [UCI SMS Spam Collection](https://archive.ics.uci.edu/dataset/228/sms%2Bspam%2Bcollection)
contains 5,574 historical English messages and is licensed CC BY 4.0. The
current local `spam.csv` has unverified provenance, so it cannot be represented
as that corpus. Importing a verified UCI copy may add attributed data, but exact
duplicates of the local file will be removed during loading. To normalize an
operator-provided UCI tab-separated file and preserve attribution:

```bash
python -m src.import_public_dataset --input /path/to/SMSSpamCollection --format uci-tsv
```

CSV inputs with `label,message` or Kaggle `v1,v2` columns are also accepted.
The importer writes to ignored `data/raw/imported/uci_sms_spam.csv`, labels it
`public`, records dataset ID/version/license/language, and refuses to overwrite
an existing file or write outside `data/raw/`. It does not download data. Cite
Almeida and Hidalgo (2011), UCI Dataset 228, and comply with CC BY 4.0
attribution when redistributing or adapting the corpus. The corpus is old and
English-heavy, uses sources from several regions, and does not establish
Philippine SMS performance. Avoid adding other mirrors of the same corpus: the
global normalized-message deduplicator will remove Unicode/case/whitespace
variants, while punctuation and semantic near-duplicates can
still bias metrics.

No additional public Philippine SMS corpus with sufficiently clear provenance,
license, and message-level language/category metadata was verified for this
change. Do not add datasets from social-media reports, mixed-channel corpora,
or synthetic generators as though they were received SMS.

## Validation behavior

The loader (`src/data.py`) fails with an actionable error on:

- a missing, empty, or non-CSV file;
- an unrecognized schema or empty message;
- unknown labels or the same message carrying conflicting labels;
- missing classes, or classes with fewer than two examples.

Exact duplicates and duplicates after Unicode NFKC normalization, case-folding,
and whitespace collapsing are removed **before** splitting (first occurrence
kept) with a warning. Conflicting labels are rejected after normalization.
Punctuation and semantic variants are not normalized. The holdout is checked
for exact and normalized overlap. The training/validation/test split is group-
aware by template family, so related examples do not cross split boundaries.
Classifier selection and probability calibration also use group-isolated folds;
training fails if groups cannot support those folds without leakage.

## Privacy rules for real data

- Collect only with consent and for a stated purpose.
- De-identify before saving: remove or mask names, full numbers, account
  numbers, addresses, OTPs, and any free-text identifiers. Keep a separately
  stored, access-controlled key only if re-identification is genuinely needed
  (normally it is not).
- Never commit raw personal SMS, sender numbers, or account data. Keep them
  outside Git (or in an approved, access-controlled store).
- Keep error review to row numbers, labels, model scores, and categorical
  metadata. Do not include message text or donor/campaign identifiers in
  evaluation reports or logs.
- Do not put real holdout messages into logs, notebooks, issues, or model
  metadata.

See `docs/DATA_COLLECTION.md` for the full consented collection, labeling, and
template-family process.
