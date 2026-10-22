# Reproducible benchmark reports

The evaluator can write a message-free JSON report containing dataset file
hashes and aggregate counts, model version and metadata, split configuration and
membership fingerprints, validation threshold diagnostics, false positives,
missed spam, language/category coverage, and uncertainty intervals. Reports
describe only the supplied data and split. A consented Philippine benchmark is
not available yet; never present synthetic or unknown-provenance scores as
Philippine real-world performance.

The checked-in [UCI + synthetic diagnostic report](benchmarks/uci-synthetic-ph-diagnostic-20261022.json)
is a reproducible example. Its internal test split reports public and synthetic
rows separately, and its external Philippine holdout is fully synthetic. The
report's `run.source_tree_clean` is false because it was generated while the
current changes were uncommitted; `run.source_revision` identifies the base
revision, so retain this change set when reproducing the run.

In this diagnostic run, the 810-row internal test split contains 740 public
corpus rows (1 false positive, 7 missed spam) and 70 synthetic rows (6 false
positives, 1 missed spam). Its separate 264-message synthetic Philippine
holdout has 4 false positives and 14 missed spam, with 0/69 template groups
overlapping training. The holdout covers 149 English, 91 Taglish, and 24
Filipino (`tl`) fixtures; category supports are uneven, and 3 of 8 fictional
e-wallet receipts plus 1 of 11 OTP examples were flagged. These counts describe
the fixtures only. The report includes Wilson marginal intervals and campaign
bootstrap uncertainty; small supports produce wide intervals and do not support
real-world accuracy estimates.

## Reproduce the public + synthetic diagnostic

The public input is the UCI SMS Spam Collection (CC BY 4.0), not a Philippine
corpus. Verify the archive and extracted TSV against the pinned hashes used by
CI before importing. Use a fresh ignored output filename if the default import
already exists:

```bash
mkdir -p .cache/uci
curl --fail --location --retry 3 --output .cache/uci/collection.zip \
  https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip
echo '1587ea43e58e82b14ff1f5425c88e17f8496bfcdb67a583dbff9eefaf9963ce3  .cache/uci/collection.zip' | shasum -a 256 -c
unzip -o -q .cache/uci/collection.zip SMSSpamCollection -d .cache/uci
echo '7d039a24a6083ed9ef0f806ebad56bbb976e3aeb8de05669173bfdc4996c239d  .cache/uci/SMSSpamCollection' | shasum -a 256 -c

python -m src.import_public_dataset \
  --input .cache/uci/SMSSpamCollection --format uci-tsv \
  --output data/raw/imported/uci_sms_spam.csv
python -m src.train \
  --data data/raw/imported/uci_sms_spam.csv \
  --output models/uci-synthetic-ph-diagnostic.pkl \
  --metadata-output models/uci-synthetic-ph-diagnostic.metadata.json \
  --holdout data/raw/ph_holdout.csv \
  --model-version uci-synthetic-ph-diagnostic-20261022 \
  --text-features combined
python -m src.evaluate \
  --data data/raw/imported/uci_sms_spam.csv \
  --model models/uci-synthetic-ph-diagnostic.pkl \
  --holdout data/raw/ph_holdout.csv --plot none \
  --json-out data/processed/uci-synthetic-ph-diagnostic.json
```

Training automatically adds the five tracked synthetic supplements. The report
breaks the mixed internal test split down by `data_kind`; keep public English
and synthetic Philippine diagnostic results separate when reporting them.
Never relabel the synthetic holdout as field data. The committed JSON identifies
the artifact evaluated by its SHA-256, but the model artifact itself is not
committed; reproduce training in the recorded dependency environment and compare
the artifact hash before treating a rerun as identical.

## Evaluate a frozen, consented holdout

Use the approved, de-identified training sources and a separate evaluation
batch that has evaluation consent. Keep both, the model artifact, and report in
the protected workspace. The holdout must be frozen before model or threshold
selection, have no campaign/donor groups in common with training, and represent
a later collection period where reliable dates are available. The evaluation
set is for one final measurement, not iterative tuning.

```bash
python -m src.consented_data /secure/workspace/consented-training.csv --purpose training
python -m src.consented_data /secure/workspace/consented-evaluation.csv --purpose evaluation

python -m src.evaluate \
  --data /secure/workspace/approved/base-training.csv \
  --supplement /secure/workspace/approved/consented-training.csv \
  --model /secure/workspace/candidates/candidate.pkl \
  --holdout /secure/workspace/approved/consented-evaluation.csv \
  --plot none \
  --json-out /secure/workspace/reports/consented-evaluation.json
```

The report records full SHA-256 values for each input file without exposing its
local path, plus the model artifact SHA-256, model version,
threshold/configuration metadata, split fingerprint, source revision and clean
working-tree flag, runtime library versions, and aggregate
class/language/category counts. Generate the report from a clean revision when
possible; if `source_tree_clean` is false, preserve the code changes needed to
reproduce that run. Record the source revision separately as well:

```bash
sha256sum /secure/workspace/candidates/candidate.pkl
git rev-parse HEAD
```

Review warnings before interpreting metrics. Confirm evaluation groups are
disjoint from training groups, dates are later when known, and class/category
counts support the claims. Treat false-positive counts for legitimate OTPs,
bank alerts, delivery messages, and promos separately from missed spam. Small
support and wide intervals mean the estimate is uncertain. Store reports with
the same access controls and deletion schedule as the protected source data;
although the JSON omits SMS text and private paths, its metrics and hashes are
derived from private inputs.

The tracked synthetic Philippine holdout can exercise this report path, but it
is a pipeline diagnostic only. See [DATA_COLLECTION.md](DATA_COLLECTION.md)
for consent, labeling, and campaign/date separation requirements.
