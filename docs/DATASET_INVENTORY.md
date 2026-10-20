# Dataset inventory (workspace audit, 2026-10-20)

This is a message-free, machine-specific snapshot of the developer workspace.
The ignored base file and model artifact are not distributed with the repo, so
their counts can differ or be absent elsewhere. Counts describe CSV rows after
the loader's exact-message deduplication where stated. No new dataset was
downloaded or added for this audit.

| Source | Role / rows | Labels | Provenance and rights | Coverage / confidence |
|---|---:|---|---|---|
| `data/raw/spam.csv` (ignored local file) | Base input 5,574; 5,159 retained, 415 exact/normalized duplicates removed | ham 4,517; spam 642 | Declared `unknown`; source, license, collection dates, and dataset identity not verified | English-style schema, but language and categories are unknown; low provenance confidence |
| `ph_supplement.csv` (tracked) | Training supplement: 128 retained | ham 70; spam 58 | Marked synthetic; file-level license terms are not stated in this repository | Filipino/Taglish intent is not encoded consistently; language/category largely unknown; high confidence it is synthetic, low metadata coverage |
| `ph_supplement_2.csv` (tracked) | 311 input; 296 retained, 15 duplicates removed | ham 41; spam 255 | Marked synthetic; file-level license terms are not stated in this repository | Scam/legitimate categories are present, language mostly unknown; high synthetic confidence |
| `ph_supplement_3.csv` (tracked) | Training supplement: 52 retained | ham 36; spam 16 | Marked synthetic; file-level license terms are not stated in this repository | Language: English 42, Taglish 10; includes bank, delivery, OTP, bill, promo, school and scam categories with small counts; high synthetic confidence |
| `ph_supplement_4.csv` (tracked) | Training supplement: 42 retained, added in this change | spam 42 | Explicitly synthetic, developer-authored; no separate dataset license is declared | English 14, Taglish 14, Filipino 14; bank, delivery, prize, job, loan, investment, and impersonation scams. Fourteen groups, three wording variants each; reserved `example.com` domains and bracketed placeholders only. |
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
