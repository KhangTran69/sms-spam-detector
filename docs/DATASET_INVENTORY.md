# Dataset inventory (workspace audit, 2026-10-20)

This is a message-free, machine-specific snapshot of the developer workspace.
The ignored base file and model artifact are not distributed with the repo, so
their counts can differ or be absent elsewhere. Counts describe CSV rows after
the loader's exact and normalized-message deduplication where stated. No
external dataset was downloaded; one synthetic legitimate supplement was added.

| Source | Role / rows | Labels | Provenance and rights | Coverage / confidence |
|---|---:|---|---|---|
| `data/raw/spam.csv` (ignored local file) | Base input 5,574; 5,159 retained, 415 exact/normalized duplicates removed | ham 4,517; spam 642 | Declared `unknown`; source, license, collection dates, and dataset identity not verified | English-style schema, but language and categories are unknown; low provenance confidence |
| `ph_supplement.csv` (tracked) | Training supplement: 128 retained | ham 70; spam 58 | Marked synthetic; file-level license terms are not stated in this repository | Filipino/Taglish intent is not encoded consistently; language/category largely unknown; high confidence it is synthetic, low metadata coverage |
| `ph_supplement_2.csv` (tracked) | 311 input; 296 retained, 15 duplicates removed | ham 41; spam 255 | Marked synthetic; file-level license terms are not stated in this repository | Scam/legitimate categories are present, language mostly unknown; high synthetic confidence |
| `ph_supplement_3.csv` (tracked) | Training supplement: 52 retained | ham 36; spam 16 | Marked synthetic; file-level license terms are not stated in this repository | Language: English 42, Taglish 10; includes bank, delivery, OTP, bill, promo, school and scam categories with small counts; high synthetic confidence |
| `ph_supplement_4.csv` (tracked) | Training supplement: 42 retained; four ambiguous/descriptive rows revised in this audit | spam 42 | Explicitly synthetic, developer-authored; no separate dataset license is declared | English 14, Taglish 14, Filipino 14; bank, delivery, prize, job, loan, investment, and impersonation scams. Fourteen groups, three wording variants each; reserved `example.com` domains and bracketed placeholders only. |
| `ph_supplement_5.csv` (tracked) | Training supplement: 21 retained, added in this change | ham 21 | Explicitly synthetic, developer-authored; no separate dataset license is declared | English 7, Taglish 7, Filipino 7; OTP, bank alert, delivery, bill, promotion, school/work, and personal conversation. Seven groups, three variants each. Uses reserved URLs/placeholders in both safe and scam training contexts. |
| Combined training input | 5,698 retained after exact and normalized global deduplication | ham 4,685; spam 1,013 | Mix of 5,159 unknown and 539 synthetic rows | Language: 5,583 unknown, 63 English, 31 Taglish, 21 Filipino. Category is unknown for 5,267 rows; the rest are synthetic categories with small supports. |
| `data/raw/ph_holdout.csv` (tracked) | Separate diagnostic holdout: 46 rows | ham 26; spam 20 | Synthetic only; not a real-world test set | English 29, Taglish 17; categories are represented by only a few examples each. No exact message or group overlap with the current training input was found; campaign independence is not established. |
| Validation and internal test splits | Derived from the combined training input; sizes depend on split configuration and groups | Both classes required by split validation | Inherit source provenance above | Group-aware split prevents a known group from crossing splits. It cannot make unknown provenance representative or establish Philippine performance. Threshold is selected using validation only. |
| Diagnostic examples in `src/evaluate.py` | 3 hand-authored strings; not data rows and excluded from metrics | N/A | Synthetic, developer-authored diagnostic prompts; no real donor source | Not a benchmark. Reports now include only example IDs and uncalibrated scores, never their text. |
| Public UCI SMS Spam Collection | Not currently added to this workspace by this change; 5,574 rows in the official record | ham/spam after normalization | UCI record states CC BY 4.0; importer requires an operator-provided source file and preserves attribution | Historical English SMS from a different collection context; not Philippine coverage. See the official [UCI record](https://archive.ics.uci.edu/dataset/228/sms%2Bspam%2Bcollection). |

The repository has no top-level data-specific license grant for its synthetic
CSV files. Their content is explicitly synthetic, but redistribution rights
should not be inferred from that label; clarify project licensing before
reusing them outside this repository. The local `spam.csv` must remain
`unknown` unless its actual source and terms are verified. A familiar schema or
matching row count is not proof that it is UCI data.

## Synthetic supplement audit and comparison

Review of supplement 4 found one ambiguous bank alert and three rows phrased
more like descriptions than recipient-facing texts. Those four rows were
rewritten as fictional SMS-style messages. Its 42 rows still all use a reserved
`example.com` URL (39 use placeholders), so supplement 5 adds six legitimate
rows with that reserved domain and 12 with placeholders. Exact/normalized
duplicate checks found no duplicate within either new file. A simple character
similarity scan found no cross-group pair at or above 0.76; the deliberate
English/Filipino/Taglish variants remain together in their explicit family
groups. This is a mechanical check, not a Filipino language quality review.

Reproducible comparison, run on 2026-10-20 with the local `spam.csv`, Python
environment in `.venv`, seed 42, group-aware split, and the same fixed
`ph_holdout.csv` (SHA-256
`036e6dcb6dd62767ce3b0c20c5650a5d716a54d24e323372550ce6071b399844`):

| Training rows | Validation-selected threshold | Holdout P / R / F1 | FP / FN | Holdout counts |
|---|---:|---:|---:|---|
| Baseline: supplements 1–3 (5,635 rows) | 0.51 | 0.909 / 1.000 / 0.952 | 2 / 0 | 46 (26 ham, 20 spam) |
| Expanded: supplements 1–5 (5,698 rows) | 0.75 | 1.000 / 1.000 / 1.000 | 0 / 0 | 46 (26 ham, 20 spam) |

The apparent difference above comes from different validation-selected
thresholds, not demonstrated score separation: at the shared 0.51 threshold
both artifacts have P 0.909, R 1.000, F1 0.952, FP 2, FN 0; at 0.75 both
have P/R/F1 1.000 and no errors. At 0.51 the two false positives are the same
English legitimate examples: delivery (1/4) and a legitimate link (1/1).
At 0.75 there are no false positives among 26 legitimate messages. The
validation-selected expanded threshold yields English P/R/F1 1.000/1.000/1.000
(n=29; 21 ham, 8 spam) and Taglish 1.000/1.000/1.000 (n=17; 5 ham, 12 spam);
at the shared 0.51 threshold both models have English 0.800/1.000/0.889 and
Taglish 1.000/1.000/1.000. Filipino is absent from this holdout. Legitimate
category supports at threshold 0.75 are OTP 4, bank alert 4, delivery 4,
bills 3, promotion 3, personal Taglish 5, appointment 1, school 1, and link 1;
all have 0 false positives. Scam category supports range from 1 to 4 and are
too small for stable category-level performance claims. No exact/normalized
message or group overlap with training was found. This is a synthetic diagnostic
comparison only; at shared thresholds, the additions show no measured change.

Commands used to create the training artifacts outside the repository (neither
replaces the serving model):

```bash
./.venv/bin/python -m src.train --supplement data/raw/ph_supplement.csv data/raw/ph_supplement_2.csv data/raw/ph_supplement_3.csv --output /tmp/sms-detector-baseline.pkl --holdout none
./.venv/bin/python -m src.train --output /tmp/sms-detector-expanded.pkl --holdout none
```

The artifacts were loaded with `src.predict.load_model`; spam scores were
calculated on the fixed holdout and `src.metrics.binary_metrics` was applied at
each stored validation threshold and shared thresholds 0.51 and 0.75. No
threshold was selected from holdout results.

## Evaluation interpretation

The newly added supplements are included in training only; they do not change the
separate synthetic holdout. Version 5 adds 21 legitimate rows, and its final
loader count is one lower than the arithmetical total because normalized duplicate
removal also removed one case/Unicode/whitespace variant from the unknown local
base data. Exact and normalized holdout overlap checks both report zero. The
UCI corpus has a verified public license but is historical and not
Philippine-specific. The synthetic holdout checks code paths and known patterns
only. The current sources do not support a real-world Philippine precision,
recall, false-positive rate, or accuracy claim. Small per-category counts are
descriptive checks, not stable estimates. A future consented evaluation needs
masked, independently labeled messages with enough legitimate OTP, bank-alert,
delivery, bill, promotion, and everyday-message examples, plus scam campaigns
held out by campaign and time. Keep that final set untouched until release
evaluation.

## Candidate training run (2026-10-20)

The local candidate `candidate-2026-10-20` was trained to the ignored artifact
`models/spam_detector_candidate_2026-10-20.pkl` from the current 5,698-row
combined input (4,685 ham, 1,013 spam after global deduplication). It records
source SHA-256 hashes, feature version, Python/scikit-learn versions, split
fingerprint, training timestamp, and validation-selected threshold in its
artifact and ignored sidecars. The base `spam.csv` provenance remains unknown;
this candidate is not suitable evidence for Philippine performance and was
not promoted to the serving model.

Re-evaluating that exact artifact produced internal test precision 0.958,
recall 0.779, F1 0.859 (n=814; 669 ham, 145 spam) at its validation-selected
0.75 threshold. At 0.50, test precision was 0.950, recall 0.924, F1 0.937,
with 7 false positives and 11 false negatives. On the separate synthetic
Philippine holdout it scored 1.000 precision/recall/F1 (n=46), with zero
false positives among 26 synthetic legitimate messages and zero group overlap.
These are reproducible diagnostics, not real-world performance claims. Some
category supports are only one example, and confidence intervals would be
uninformative at that scale. The machine-readable evaluation JSON and model
artifacts are ignored outputs; rerun these commands to reproduce them.

## Text feature mode comparison (2026-10-20)

Word-only, character-only, and combined TF-IDF candidates were trained on the
same 539-row tracked synthetic input (15 normalized duplicates removed), with
the same seed 42 and group split. Each candidate selected its own threshold on
the same validation set; all three then reported on the fixed 77-row internal
test split (24 ham, 53 spam). All input and evaluation rows were synthetic.

| Mode | Validation threshold | Test precision | Test recall | Test F1 | FP / FN |
|---|---:|---:|---:|---:|---:|
| Word | 0.61 | 0.8929 | 0.9434 | 0.9174 | 6 / 3 |
| Character | 0.64 | 0.8929 | 0.9434 | 0.9174 | 6 / 3 |
| Combined | 0.64 | 0.9091 | 0.9434 | 0.9259 | 5 / 3 |

The precision intervals overlap broadly (Wilson marginal 95% intervals:
word/character 0.785–0.950, combined 0.804–0.961). This one small synthetic
split does not establish a meaningful difference or justify changing the
serving model; word-only remains the default. These intervals treat outcomes
as binomial trials and do not adjust for campaign clustering, and the report
does not include a confidence interval for F1. Repeated group-aware evaluation
across seeds, threshold stability, and a product-approved cost-based operating
point remain open work. The separate 46-row synthetic holdout was diagnostic
only and was not used to select features or thresholds.

Reproduce from the repository root by training to separate ignored artifact
paths with the same command and changing only `--text-features` and
`--output`:

```bash
python -m src.train --data data/raw/ph_supplement.csv \
  --supplement data/raw/ph_supplement_2.csv data/raw/ph_supplement_3.csv \
  data/raw/ph_supplement_4.csv data/raw/ph_supplement_5.csv \
  --holdout data/raw/ph_holdout.csv --seed 42 \
  --output models/feature-word.pkl --text-features word
```

The `char` and `combined` variants use the same command with distinct output
paths. All artifacts are candidates; none replaces the serving artifact.

```bash
python -m src.train --output models/spam_detector_candidate_2026-10-20.pkl \
  --model-version candidate-2026-10-20 --holdout data/raw/ph_holdout.csv
python -m src.evaluate --model models/spam_detector_candidate_2026-10-20.pkl \
  --json-out data/processed/candidate-2026-10-20.json
```
