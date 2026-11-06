# Evaluation datasets and reports

This project keeps public, synthetic, and consented evidence separate. A report
describes the exact file and model artifact evaluated; its numbers do not
establish representative Philippine real-world accuracy.

## Available data

| Dataset | Status | What its evaluation could support |
|---|---|---|
| Public UCI SMS Spam Collection | English corpus, CC BY 4.0; current project benchmark reports it separately from synthetic data | Reproducibility and behavior on this historical English corpus only |
| [PH Spam + Marketing SMS (w/ timestamps)](https://www.kaggle.com/datasets/scottleechua/ph-spam-marketing-sms-w-timestamps) | Retrieved locally; 1,664 normalized unique labeled rows from the 8,895-row raw snapshot; CC BY 4.0 per [publisher documentation](https://github.com/scottleechua/data/tree/main/spam-and-marketing-sms); **not yet evaluated** | At most a diagnostic on a single inbox belonging to one person; it is not representative of the Philippine population |
| [Tagalog-SMS](https://www.kaggle.com/datasets/onzero0/tagalog-sms) | Kaggle metadata reports CC0: Public Domain; local downloader omits the sender field from normalized rows; **not yet downloaded or evaluated** | At most a diagnostic on one person's inbox. The CC0 label does not resolve privacy rights in the message content, and this is not representative Philippine traffic |
| [`DATA103_filipino_spam_detection`](https://huggingface.co/spaces/ferds003/DATA103_filipino_spam_detection) | **Blocked**: the Space declares MIT, while its README describes a merge of a CC BY 4.0 Kaggle source, a CC BY-NC-SA 4.0 Kaggle source, and a GitHub repository with BSD 3-Clause terms. The message-level provenance, authorization, and downstream license compatibility are unresolved. | No ingestion or evaluation until source owners document compatible reuse terms and a suitable privacy basis for every constituent corpus |
| [Philippine Spam/Scam SMS by BwandoWando](https://www.kaggle.com/datasets/bwandowando/philippine-spam-sms-messages) | CC BY-NC-SA 4.0; not approved for this dataset workflow | No ingestion until license compatibility and privacy basis are reviewed |
| [Filipino Gossip Dataset](https://huggingface.co/datasets/jhenberthf/filipino-gossip-dataset) | MIT, but a small text-generation dialogue dataset rather than labeled SMS | Out of scope for spam/ham evaluation |
| [RJCed/Filipino-ScamSMS-Detector](https://github.com/RJCed/Filipino-ScamSMS-Detector) | Experimental paused repository without a root license; README lists the Tagalog-SMS, BwandoWando, and gossip sources above | Not an independent benchmark; do not reuse its CSVs until source-level terms are established |
| [Notanne1305/SMS-Scam-Detection-in-English-Filipino-Texts](https://github.com/Notanne1305/SMS-Scam-Detection-in-English-Filipino-Texts) | No root license file; combined data provenance and redistribution rights are unclear | No download or use until source permissions and licensing are documented |
| Tracked Philippine fixtures | Synthetic | Pipeline and known-template regression checks only |
| Consented Philippine corpus | Not yet collected | No consented field-performance claim is currently available |

Public availability is not consent to republish personal messages. The Kaggle
publisher states CC BY 4.0 and redacts some categories, but this does not resolve
privacy or other rights concerns. Its inbox represents one contributor and its
category mapping is imperfect: `spam` and `ads` become `spam`; `gov`, `notifs`,
and `otp` become `ham`. Blank/redacted rows, unknown categories, and duplicate
counts are disclosed in the local aggregate sidecar. See
[`data/external/README.md`](../data/external/README.md) and
[`DATA_COLLECTION.md`](DATA_COLLECTION.md).

The local raw snapshot, its normalized file, and the supplied ZIP/CSV duplicate
are local-only. The ZIP and standalone CSV are one copy of the same source and
must be counted once. Neither may be used as a substitute for consented or
representative field data; supplied notebooks are not executed by this workflow.

## Download and evaluate locally

Dataset files are never committed and are excluded from CI. Install project
dependencies. The default command fetches PH Spam + Marketing SMS directly
from the publisher's public GitHub CSV; select Tagalog-SMS explicitly:

```bash
make datasets
make eval DATA=data/external/ph-spam-marketing-sms.csv MODEL=models/spam_detector_v1.pkl

make datasets DATASET=tagalog-sms
make eval DATA=data/external/tagalog-sms.csv MODEL=models/spam_detector_v1.pkl
```

For a local, one-inbox diagnostic, screen and redact likely identifiers in
memory before scoring:

```bash
make eval \
  DATA=data/external/ph-spam-marketing-sms.csv \
  MODEL=models/spam_detector_v1.pkl \
  REDACT_PII=1
```

This reuses the normalized-dataset validator, `src/privacy.scrub`, and the
existing content-free report writer. Phone numbers, email addresses, likely
account/ID numbers, and OTP values are redacted in memory; URLs remain intact
as possible smishing signals. Reports contain only aggregate screening counts,
not the original or redacted message text. The source CSV hash still identifies
the original input. Do not use this transformation for sealed consented tests,
because it changes the test input; that path rejects `REDACT_PII=1`.

`make datasets` needs network access but no Kaggle credentials. Tagalog-SMS
requires `KAGGLE_USERNAME` and `KAGGLE_KEY`. The downloader stores the source
CSV, normalized CSV, and message-free metadata under the git-ignored
`data/external/` directory. Both raw inbox sources may contain sender metadata;
keep the raw files local and treat them as sensitive. Their normalizers drop
sender fields before creating evaluation CSVs. The source and normalized
reports stay separate by corpus. Do not point the downloader at an existing
file; it refuses overwrites. For an already normalized CSV,
`make eval DATA=...` uses
the default model from `SMSD_MODEL_PATH` or `models/spam_detector_v1.pkl`.
Optional settings include `MODEL=...`, `OUTPUT_DIR=...`, and
`OPERATING_FPR=...` (default 0.05).

Reports are written to `reports/eval/<dataset>_<model-version>.json` and
`reports/eval/<dataset>.md`. They contain model and dataset SHA-256 digests,
source revision and dirty-tree status, dependency versions, configuration,
evaluation membership fingerprint, sample counts, category/language/source
coverage, confusion counts, precision, recall, F1, false-positive and
false-negative rates, ROC-AUC, PR-AUC, Wilson uncertainty intervals, and
calibration bins. Single-class inputs mark undefined AUC metrics as unavailable.
The membership fingerprint uses dataset hash and row positions; it contains no
message text or stable row identifiers. Reports do not include message
examples, absolute input paths, or predictions per message.

The stored model threshold supplies the headline metrics. An additional
operating-threshold diagnostic maximizes observed recall under the configured
empirical false-positive-rate cap on the same dataset. This is descriptive,
optimistic on a dataset used for threshold exploration, and **not** a production
threshold recommendation. Calibration bins and score-based metrics do not make
the output a fraud probability or a safety guarantee.

The JSON and Markdown output directory is selected by the operator. Keep it
private when the evaluation input is consented or otherwise restricted; hashes,
aggregate errors, and small-group coverage can still be sensitive. Do not
publish private reports or attach them to CI artifacts.

## Status and interpretation

No new benchmark on the PH or Tagalog-SMS corpus has been run in the current
repository change. Do not infer measured results from
the dataset listing or from the synthetic fixtures. The public UCI and synthetic
results in the versioned engineering diagnostic remain separate. None establish
performance on current Philippine messages. A defensible real-world evaluation
requires approved, independently labeled data; campaign and date separation;
adequate legitimate-message coverage; uncertainty estimates; and an untouched
evaluation set. See [DATA_COLLECTION.md](DATA_COLLECTION.md) for the consent,
labeling, privacy, and withdrawal process.

In the 2026-11-06 workspace check, the normalized PH public inbox file was
present, but the default model bundle and its sidecar were absent. No model
scoring was run and no performance metrics were generated. A local diagnostic
will produce only a blocked readiness report until an available model passes
the artifact integrity checks.

## Evidence and headline guards

`python scripts/check_quality_gate.py MODEL.metadata.json --min-f1 0.90`
continues to apply the F1 floor to the model's internal test. Add
`--require-real-holdout` when the gate must also require one held-out source
whose metadata classifies as `consented`, licensed `public_licensed`, or
licensed English `public_english`. It exits with status 2 when provenance is
missing, synthetic, mixed, unknown, or public without a recognized license.
The class is reported explicitly; `public_english` means licensed,
English-language public evidence, not Philippine performance. A licensed
public inbox is at most a diagnostic on that particular inbox and does not
establish consent or representativeness.

`make check-headlines` scans Markdown headings and the website title/H1 for
unsupported performance claims. It reports only file and line locations, never
the headline text. The same guard runs in the Python test suite.

## Consented Philippine evaluation gate

Before real collection, the project owner and qualified privacy/legal reviewer
must close the human-controlled go/no-go record in
[`DATA_COLLECTION.md`](DATA_COLLECTION.md). This repository does not choose a
sample-size target or establish legal compliance.

Run the disposable end-to-end rehearsal with fictional messages:

```bash
make rehearse-consented
```

It exercises explicit local consent, reserved `.example` URL rejection,
review-only export, two separate synthetic blind-label sheets, adjudication,
purpose-specific consent preflight, chronological campaign splitting,
development-only training, and one plan-bound sealed-test evaluation. It uses
only generated fixtures, prints aggregate metrics and hashes without message
text, and deletes its temporary database, sheets, split files, model, plan, and
reports before exiting. Its results are engineering checks only: they are not
consented participant data, Philippine field evidence, or a real-world
performance estimate.

Consented intake is not model data. An export remains a pending-review staging
file until an operator verifies the separate consent register and two blinded
reviewers plus an independent adjudicator complete spam/ham and scam
assessments. The validator checks purpose-specific consent and content-free
privacy/leakage rules; it does not prove authorization, consent, or complete
de-identification.

For a reviewed batch explicitly approved for both development and final test,
run `make split-consented DATA=... DEVELOPMENT_DIR=... EVALUATION_DIR=...`. It
checks active review/sharing/research choices, dates, labels, duplicates, and
template/campaign grouping. It writes a private development file, a separately
stored chronological test file, and a content-free manifest with input/output
hashes, split-membership fingerprints, and aggregate language/category
coverage. Keep the test directory with a
custodian who did not train, select features, or tune the threshold. The tool
cannot prove that the custodian did not previously view the messages; if access
cannot be separated, do not call the test independent.

Train only from the development file and select the decision threshold on its
internal validation partition:

```bash
.venv/bin/python -m src.train \
  --data /secure/development/consented-development-<hash>.csv \
  --holdout none --split-by time --threshold-policy validation \
  --output /secure/candidate/model.pkl
```

Before the test file is opened, register an analyst-authored plan based on
[`templates/consented-evaluation-plan.json`](templates/consented-evaluation-plan.json).
Bind the exact model, development and test hashes, membership fingerprints,
model version, and validation-selected threshold. Predeclare intended use,
minimum language/category coverage, minimum campaign count, maximum
campaign-cluster interval widths, and written rationales. Choose these criteria
from intended use, expected false-positive/false-negative costs, the effective
independent campaign count, and tolerable uncertainty. There is no universal
row-count target. The code's minimum of two test groups permits a cluster
calculation; it is not a sufficient sample for a trustworthy result.

Evaluate once with the matching development file, model, and sealed test file:

```bash
make eval \
  DATA=/secure/sealed-test/consented-evaluation-<hash>.csv \
  TRAINING_DATA=/secure/development/consented-development-<hash>.csv \
  MODEL=/secure/candidate/model.pkl \
  EVALUATION_PLAN=/secure/registered-plan.json \
  OUTPUT_DIR=/secure/reports
```

The gate checks model provenance and exact artifact hash, development-source
hash, chronological campaign metadata, campaign/template/duplicate isolation,
plan registration, coverage, and predeclared uncertainty tolerances. It does
not tune thresholds on the final test. A missing model, consent, review,
provenance, plan, coverage, or separation requirement produces only a private,
content-free readiness report. Reports and manifests contain aggregate values
and hashes, never message text, row or campaign identifiers, or input paths.
Keep source files, plans, models, reports, and backups in protected local
storage; small aggregates and hashes can still be sensitive.

The first eligible consented evaluation atomically creates a private
`.<dataset-sha256>.sealed-evaluation-attempt.json` marker beside the sealed
dataset **before** scoring. It is tied to the exact dataset hash, so changing
the report directory does not permit another attempt. The custodian must retain
the marker with the dataset. The attempt remains consumed if scoring,
uncertainty checks, or report writing later fails; do not delete the marker,
copy the sealed test to reset it, or retry. An uncertainty or coverage failure
yields a content-free readiness report and no performance metrics. This local
guard is not tamper-proof: the custodian and study protocol must prevent access
to copies, deletion of the marker, and manual bypass.

No trained model artifact or independently labeled consented Philippine
corpus is currently available, so this workflow is ready for approved data
intake but blocked from a consented performance result. The local 1,664-row
public one-person inbox is not consented, is not representative, and has not
been evaluated. No public or synthetic score establishes real-world Philippine
accuracy.
