# Philippine field evaluation: preregistration and readiness

> **Methodology only.** No new datasets, participant recruitment, message
> collection, manual labeling, or field-performance claims are part of this
> engineering change. Tracked Philippine examples remain synthetic. The one-person
> public Philippine inbox diagnostic is not an independent or representative test.

This is a decision checklist, not a replacement for the authoritative
[DATA_COLLECTION.md](DATA_COLLECTION.md), [HUMAN_REVIEW.md](HUMAN_REVIEW.md),
[evaluation.md](evaluation.md), or the
[consented evaluation plan template](templates/consented-evaluation-plan.json).
The project owner and a qualified privacy/legal reviewer must document a
**go/no-go approval before real collection**.

## Study question, sampling and recruitment

Define precisely where this *assistive spam/ham triage tool* will be used,
including dates, phone/network environment, privacy notice, language support
and the cost of warning on a legitimate message. The model does not establish
fraud or verify a sender.

- Establish a documented sampling frame of consenting adult Philippine SMS
  recipients across supported locations, language use (English, Filipino,
  Taglish), handset/network contexts and time periods. Do not imply national
  representativeness from convenience volunteers or one inbox.
- Stratify legitimate messages into personal chat, school/work, delivery,
  transaction/bank/e-wallet alerts, **expired and masked** OTP notices,
  promotions, bills and other intended uses. Separately stratify spam patterns
  such as phishing, impersonation, payment requests and bulk marketing.
- Document the recruitment process, expected subgroup mix, oversampling plan,
  exclusions, actual missing coverage and whether population-weighted estimates
  have any defensible external population weights. Never manufacture weights
  to make results appear representative.
- Prespecify minimum numbers of **independent campaigns** and coverage by
  language/category after calculating sample requirements from the desired
  interval widths. Count messages, participants and campaigns separately.
  The evaluator's technical floor of two groups is not sufficient evidence.
- Avoid repeated message families, source-specific near-duplicates and any
  contributor/campaign leakage across development and the final holdout.

## Privacy and independent ground truth

Request no active OTP, password, PIN, account number, name, sender number or
private third-party conversation. Accept only authorized, purpose-specifically
consented, minimized samples under the approved workflow. Keep a restricted
consent/withdrawal register separate from research records, with scope, access,
retention, expiration and deletion procedures verified by a human steward.
Automated PII scrubbing is a screen, never proof of de-identification.

Assign two blinded reviewers independently; hide participant suggestions,
model scores and each other's initial labels. Adjudicate disagreement with an
independent reviewer. Preserve separate spam/ham and *suspected scam*
assessments: a spam label cannot substantiate an actual criminal scam. Mark
ambiguous or low-confidence data as unresolved and disclose exclusions.

## Independent evaluation and metrics

1. Freeze a later chronological **campaign-group-separated** test set under an
   independent custodian, with exact/normalized/near-duplicate checks. Keep
   train/validation development data distinct.
2. Train and select the stored threshold on development/validation **only**.
   Register the evaluation plan and the exact model, data and split-membership
   hashes before any sealed test is scored.
3. Use the existing one-shot `src.public_evaluation` readiness gate. A missing
   consent, source hash, group separation or preregistered coverage/uncertainty
   requirement must block the claim, not trigger repeated retesting.
4. Report TP/FP/FN/TN, spam precision, recall, F1, false-positive and
   false-negative rates, specificity, calibration diagnostics, and actual
   sample/campaign support. Use Wilson intervals and campaign-cluster
   bootstrap intervals where supported; avoid precise rates for sparse
   subgroups. Give English, Filipino, Taglish and critical legitimate-message
   category breakdowns and the gap between weighted and unweighted estimates.
5. Compare at a **fixed** threshold to the incumbent model on an unchanged
   holdout. Do not tune on test results, rename an internal split as an
   external holdout or substitute UCI/synthetic performance for field evidence.

## Acceptance gates: owner must preregister numerical thresholds

The following fields are **mandatory decisions, not preapproved values**.
The owner and qualified reviewer must specify the exact numerical criterion,
justification based on intended-use error cost, required independent support,
interval type, and action if it fails *before* the sealed evaluation.

| Release gate | Required preregistered decision |
|---|---|
| Provenance/consent | 100% of evaluated records eligible for consented research, independent review, retention and sharing authorization |
| Leakage and custody | Zero accepted train/test campaign/template overlaps and no permitted sealed-test retuning |
| Legitimate SMS false alarms | Maximum overall false-positive rate **and upper confidence bound**, including OTP/bank/delivery critical-category bounds |
| Missed spam | Minimum spam recall **and lower confidence bound**, separately for adequately supported languages/categories |
| Spam precision and F1 | Minimum precision/F1 with supported interval widths; reflect realistic spam prevalence |
| Calibration | If percentages are presented as calibrated, predeclare a maximum calibration error and bin support, else use cautious score language |
| Coverage | Minimum independent campaign groups, participants, language/category support, and maximum missingness; choose using intended precision |
| Uncertainty | Maximum cluster interval width for precision, recall, F1, FPR and FNR in `templates/consented-evaluation-plan.json` |
| Operational safety | No raw-content leakage, acceptable p95 latency on named hardware, recovery and rollback demonstrated, critical-category regressions reviewed |
| Comprehension | Qualified human review finds no material false-safety interpretation or blocking keyboard/screen-reader barrier |

A number-filled plan must be justified and signed. Do **not** invent a universal
sample count or configure the final thresholds using the sealed test. An
unavailable or overly wide confidence interval means *insufficient evidence*,
not a pass. Human comprehension and accessibility checks are distinct from
classifier accuracy.

## Reproducible procedure (not performed with real SMS)

```bash
# Disposable end-to-end rehearsal with fictional examples only
make rehearse-consented

# These commands require separate approved data, private storage and custody:
make split-consented DATA=/secure/approved-reviewed.csv \
  DEVELOPMENT_DIR=/secure/development EVALUATION_DIR=/secure/sealed-test

python -m src.train --data "/secure/development/consented-development-<hash>.csv" \
  --no-supplements --holdout none --split-by time --threshold-policy validation \
  --output /secure/candidate/model.pkl

# Register every acceptance threshold and artifact/data/membership hash first.
# The custodian must authorize exactly one final evaluation attempt:
make eval DATA="/secure/sealed-test/consented-evaluation-<hash>.csv" \
  TRAINING_DATA="/secure/development/consented-development-<hash>.csv" \
  MODEL=/secure/candidate/model.pkl \
  EVALUATION_PLAN=/secure/registered-plan.json \
  OUTPUT_DIR=/secure/private-reports
```

The sealed-test attempt marker remains consumed even if coverage or
uncertainty validation fails. Do not erase the marker, copy the test set to
retry, or use the result to choose a revised candidate. No project source
file, example, or synthetic rehearsal provides authorization for a field study.

**Current go/no-go:** no authorized independent consented Philippine corpus and
no signed numerical acceptance criteria exist; therefore a representative
Philippine field-performance release remains blocked.
