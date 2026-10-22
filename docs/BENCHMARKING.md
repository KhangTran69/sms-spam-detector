# Reproducible benchmark reports

The evaluator can write a message-free JSON report containing dataset file
hashes and aggregate counts, model version and metadata, split configuration and
membership fingerprints, validation threshold diagnostics, false positives,
missed spam, language/category coverage, and uncertainty intervals. Reports
describe only the supplied data and split. A consented Philippine benchmark is
not available yet; never present synthetic or unknown-provenance scores as
Philippine real-world performance.

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
