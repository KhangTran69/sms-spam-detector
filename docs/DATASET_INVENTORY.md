# Dataset inventory (local workspace audit, 2026-10-21)

This is a message-free count and provenance snapshot from one developer
workspace. The base CSV and model artifacts are ignored by Git and are not
distributed. Counts are computed after exact and normalized duplicate removal.
No real Philippine messages or new public dataset were added in this audit.

| Source | Role / rows | Labels | Provenance and limitations |
|---|---:|---|---|
| `data/raw/spam.csv` (ignored local file) | 5,574 input; 5,159 retained; 415 duplicates removed | ham 4,517; spam 642 | Source, license, date, and identity unknown. SHA-256: `ec218ffbb1dae2f3a4fca95e92cfe2cd38960c3219759a978f795636355784d8`. |
| `ph_supplement.csv` | 128 | ham 70; spam 58 | Synthetic; source/category/language metadata is mostly unknown. SHA-256: `e2551477919b8def8f87cb8c03f47630b399b26e132f99ddb60974fa43146d00`. |
| `ph_supplement_2.csv` | 141 | ham 41; spam 100 | Synthetic and curated; small coverage. SHA-256: `fc421a56d05211bc74422f5fe00936de3401eec5ccbf7ecaccaf60a55804324e`. |
| `ph_supplement_3.csv` | 52 | ham 36; spam 16 | Synthetic; English and Taglish labels/categories, small support. SHA-256: `638d4992e5cccf9168dfaea85e01fb0bf78361182fa8014bf051488e873dffd2`. |
| `ph_supplement_4.csv` | 42 | spam 42 | Synthetic; English, Taglish, and Filipino scam templates with reserved example domains/placeholders. SHA-256: `1695232f09c55ae852dda75eeee019c525dbdf3eef32dd316ff5f47cb5b1dd91`. |
| `ph_supplement_5.csv` | 150 | ham 90; spam 60 | Synthetic; legitimate and scam categories, with repeated template families grouped. SHA-256: `a58a8352670b96385d1ae6ec9e78d7e8d1fb7678ddca96c222b76a61a74690d7`. |
| Combined training input | 5,672 retained | ham 4,754; spam 918 | 5,159 unknown-provenance and 513 synthetic rows. Languages: unknown 5,428; English 132; Taglish 76; Filipino (`tl`) 36. Category is unknown for 5,287 rows; remaining categories have small supports. |
| `data/raw/ph_holdout.csv` | 264 | ham 124; spam 140 | Synthetic diagnostic only. All 264 rows marked synthetic; languages: English 149, Taglish 91, Filipino (`tl`) 24. SHA-256: `ec5ff937c0e2b55e160fa45cb5639b8afd9b1d86c481c230dd3213608a16ac51`. Current exact/normalized message and derived/explicit group overlap checks against training are zero. |
| Public UCI SMS Spam Collection | Not present in this workspace | — | UCI lists the historical English corpus under CC BY 4.0. It is not Philippine data; importing it requires the operator to obtain the source and preserve attribution. See the official [UCI record](https://archive.ics.uci.edu/dataset/228/sms%2Bspam%2Bcollection). |

The project does not state a separate license for its synthetic CSV content.
Do not infer redistribution rights from the synthetic label. The local
`spam.csv` remains `unknown`; matching the UCI row count or schema does not
prove it came from UCI.

## Evaluation and reproducibility

The repository has no committed benchmark report tied to the current local
input hashes and current split membership. Older numeric comparisons in
workspace notes used earlier dataset versions and ignored artifacts; those
figures are historical diagnostics, not current results, and have been removed
from the README. The `models/` files are local ignored artifacts, so a clean
checkout cannot independently verify their metrics. The running local API at
`127.0.0.1:8000` reports `spam_detector_v1`, a legacy artifact with an
uncalibrated score and unavailable training provenance. It is not evidence of
current source performance.

Training removes exact and normalized duplicates before splitting. The default
split keeps known groups together; threshold selection uses validation only,
and the final internal test split is separate. Model selection and calibration
must also use group-isolated folds. Synthetic checks are not independent field
validation. Use `python -m src.evaluate --json-out <protected-report-path>` to
produce a machine-readable evaluation for a specific model and input set.
Keep the report with its source hashes, model version, split fingerprint,
settings, and sample counts in a restricted location when private data is used.

No real-world Philippine performance claim is currently supported. Establishing
one requires consented, de-identified Philippine messages with independently
reviewed labels, adequate legitimate OTP/bank/delivery/bill/everyday examples,
scam campaigns held out by campaign and time, and an untouched evaluation set.
Keep that set out of model selection, calibration, and threshold tuning.
