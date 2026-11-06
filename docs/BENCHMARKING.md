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

Use the separate hash-bound consented workflow in
[`evaluation.md`](evaluation.md#consented-philippine-evaluation-gate), which
preflights independent labeling and consent, creates a chronological
campaign-separated sealed test split, registers coverage/uncertainty criteria,
and blocks metrics if provenance or separation checks fail. The older
`src.evaluate` command is for public, unknown, and synthetic engineering
diagnostics; it rejects a consented final holdout so the consent gates cannot
be bypassed. Keep all consented data and resulting reports in protected local
storage. The tracked synthetic holdout remains a pipeline diagnostic only.

## One-command candidate benchmark

`python -m src.benchmark` validates the named input paths, trains an isolated
candidate, evaluates its held-out split, and stores all artifacts in one new or
empty output directory. A public or consented base CSV must be named explicitly;
the command does not silently add the repository's synthetic supplements.
Training and evaluation use the same named sources and the same grouped split.
The report includes the candidate's exact byte hash, source revision and dirty
tree status, package versions, dataset hashes, split membership fingerprints,
class errors, coverage, uncertainty, and a fixed-threshold MultinomialNB baseline
fit only on the training groups. Baseline and candidate results use identical
test groups. Public and synthetic rows are broken out by provenance.

For example, with an already approved UCI import and tracked synthetic fixtures:

```bash
python -m src.benchmark \
  --data data/raw/imported/uci_sms_spam.csv \
  --supplement data/raw/ph_supplement.csv data/raw/ph_supplement_2.csv \
              data/raw/ph_supplement_3.csv data/raw/ph_supplement_4.csv \
              data/raw/ph_supplement_5.csv \
  --holdout data/raw/ph_holdout.csv \
  --output-dir data/processed/uci-synthetic-run
```

The holdout remains diagnostic and synthetic. For consented files, run
`python -m src.consented_data ... --purpose training` on each training input
and `--purpose evaluation` on the frozen holdout first, then keep the candidate
directory in the same protected workspace as its inputs. Reports omit message
text and local paths, but source hashes and aggregate metrics still derive from
private data. The command refuses to overwrite existing candidate or report
files. Its report schema is versioned; retain the artifact and manifest next to
the report when reproducing a result.

## Clean main reproduction (2026-11-01)

The [clean-main report](benchmarks/clean-main-6ac6a795-20261101.json) reproduces
commit `6ac6a795cce2d23b91796a0a9ca95844d2d565c4` with Python 3.13.3, the pinned
UCI archive and extracted-file hashes, five tracked synthetic supplements, and
the tracked synthetic holdout. It records the dependency versions, dataset
hashes, split fingerprint, class-specific results, fixed-threshold baseline,
and uncertainty. This is a public-plus-synthetic diagnostic, not a Philippine
field-accuracy estimate.

The [near-duplicate audit](benchmarks/clean-main-6ac6a795-20261101-near-duplicate-audit.json)
records zero exact or normalized duplicates and zero template-group overlap,
including zero overlap with the 69 holdout groups. A separate screen required
both a TF-IDF character 3–5-gram cosine similarity of at least 0.90 and a
case-folded SequenceMatcher sequence ratio of at least 0.90. It found 14
high-similarity candidate pairs across internal splits (6 train/validation and
8 train/test); all pairs shared a label and came from the public corpus. The
screen found no pair with cosine
similarity of at least 0.80 between training rows and the synthetic holdout.
The internal pairs are possible template-leakage candidates rather than
confirmed duplicates. Group disjointness alone does not rule out near-duplicate
leakage; read the diagnostic scores with that limit.

## Optional local transformer spike

The transformer is an opt-in research path. The default installation, default
training command, and default API continue to use the linear TF-IDF model. The
local loader supports XLM-RoBERTa sequence-classification artifacts only and
never downloads a checkpoint. Obtain and review any base checkpoint separately
before supplying its local directory.

Install the optional stack for the active Python minor version; the three
constraint files pin the same compatibility set for Python 3.11, 3.12, and
3.13; the optional stack was not installed for this repository validation run:

```bash
python -m pip install -e ".[transform]" -c constraints/transform-py3.11.txt
```

Replace the constraints filename with `transform-py3.12.txt` or
`transform-py3.13.txt` for those interpreters. The base `.[dev]` install does
not install PyTorch, Transformers, or Accelerate.

The source-tree training CLI accepts only explicit local data and model paths.
For the combined linear-plus-transformer workflow, name approved non-synthetic
training data, disable implicit supplements, and do not pass any sealed test
file as training input:

```bash
python -m src.train \
  --data /protected/path/approved-training.csv \
  --no-supplements --holdout none \
  --output /protected/path/linear-candidate.pkl \
  --ensemble \
  --transformer-base-model /protected/path/xlm-roberta-base \
  --transformer-output /protected/path/xlm-roberta-smsd-candidate
```

The transformer receives the exact group-aware split created for the linear
candidate. It trains on training groups and uses validation groups for the
Trainer's epoch evaluation and to select its own precision-first decision
threshold; it does not receive the test rows. This threshold selection does
not calibrate the transformer's raw scores. The independent
`scripts/finetune_transformer.py` command follows the same split and provenance
checks. Synthetic-only runs fail unless `--allow-synthetic-demo` is explicit;
synthetic output and mixed synthetic output are marked `demo_quality`. Unknown
provenance is rejected, including when the synthetic-demo flag is supplied.
The output provenance file records the base-checkpoint hash and a hash of the
trained model/tokenizer files (excluding the provenance file itself), plus
source hashes, versions, and split membership fingerprint. It contains no
message text.

To route uncertain API predictions, set both server-side environment variables
before startup:

```bash
SMSD_TRANSFORMER_MODEL_PATH=/protected/path/xlm-roberta-smsd-candidate \
SMSD_TRANSFORMER_CONFIDENCE_BAND=0.10 \
make serve
```

Only messages for which `abs(linear_spam_score - linear_decision_threshold) < band`
are sent to the local transformer when the linear artifact marks its score as
calibrated. If the linear score is uncalibrated, all results remain linear.
Other out-of-band results also remain linear. Each API result
contains `model_path`; transformer-routed results have
`probability_calibrated: false` and identify the transformer artifact using a
prefix of its verified content hash in `model_version`. The transformer's
separate decision threshold was selected on validation data; its score has not
been calibrated. The linear decision threshold remains unchanged. These commands do
not generate a transformer test or holdout accuracy report. Anonymous
correction feedback is disabled while the optional transformer is configured,
because the feedback contract cannot identify which inference route produced
the result. The default linear latency regression test is automated; optional
ensemble latency is documented but has no enforced budget.

**No promotion decision is currently possible.** The Task 5 real-holdout
comparison has not been run, and no minimum improvement margin was registered
in advance. The model card leaves that margin intentionally unset. The
ensemble must remain disabled until the project owner registers the comparison
procedure and minimum margin, and an authorized run evaluates both candidates
against the same approved, hash-bound real holdout. Synthetic checks, local
plumbing tests, and public corpus scores cannot satisfy that gate.
