# Project Improvement Execution Record

Updated: 2026-10-24

This record separates measured engineering checks from proposals and work that
still needs consented data or participant input. It does not approve a
production release policy.

## 1. Baseline and provenance

The local file data/raw/spam.csv is declared unknown provenance in the dataset
inventory and was excluded. I downloaded the UCI SMS Spam Collection from the
official archive, verified the archive and extracted-file SHA-256 values
against docs/BENCHMARKING.md, and imported it with its CC BY 4.0 attribution.
UCI contains English SMS; it is not Philippine data.

The benchmark used 5,157 retained public UCI messages and the five tracked
synthetic Philippine supplements (513 messages). Duplicate removal dropped
415 base rows (414 exact and one normalized duplicate). The final training
input had 5,670 rows: 4,752 ham and 918 spam. Its category metadata is absent
for 5,285 rows. The separate 264-message Philippine holdout is fully synthetic.
No consented Philippine messages are present.

The grouped split used seed 42 and placed 810 rows in each validation and test
split. It is grouped for known duplicate/template metadata; this does not make
synthetic template groups equivalent to independent real campaigns. The
validation-only threshold candidate was 0.93, but the cv-robust rule retained
0.50 because the candidate did not improve every cross-validation fold.

The run is in the ignored local directory
data/processed/phase-baseline-20261024/. It contains a message-free report,
candidate artifact, metadata, and manifest. The report records source revision
c616ff0e9b28b81e49c318d9a673e7e24d3967c4, model SHA-256
7f6d627316fd5a41f343c9611a8f48b49a20d5bd68cd99622e12931792923d20, Python
3.13.3, and dependency versions. source_tree_clean is false because UI work
was in progress during the run; training and evaluation code did not change.
The generated inputs and report remain ignored and are not part of Git.

| Evaluation set | Support | Precision | Recall | False positives | False-positive rate (95% Wilson interval) |
|---|---:|---:|---:|---:|---:|
| Internal test, public UCI | 740 (637 ham, 103 spam) | 99.0% | 93.2% | 1 | 0.16% (0.03%–0.88%) |
| Internal test, synthetic | 70 (42 ham, 28 spam) | 81.8% | 96.4% | 6 | 14.3% (6.7%–27.8%) |
| Synthetic Philippine holdout | 264 (124 ham, 140 spam) | 96.9% | 90.0% | 4 | 3.2% (1.3%–8.0%) |

The mixed internal test reports a Brier score of 0.0159 and expected
calibration error of 0.0115; the synthetic holdout reports 0.0591 and 0.0446.
Calibration bins are sparse outside the extreme score ranges, so these numbers
are descriptive, not evidence that scores transfer to Philippine recipients.

On the synthetic holdout, 1 of 11 legitimate OTPs and 3 of 8 legitimate
e-wallet receipts were flagged. Bank alerts had 0/16 and delivery notices 0/11
flagged. Those small denominators produce wide uncertainty; for example, the
OTP false-positive interval is approximately 1.6%–37.7%. They cannot establish
acceptable field performance. Language support in the internal test was
especially thin: 10 Taglish and 3 Filipino (tl) rows, compared with 759
English and 38 unknown-language rows. The synthetic holdout contains 149
English, 91 Taglish, and 24 Filipino examples, still author-created fixtures.

The selected LinearSVC model exceeded the same-split MultinomialNB baseline on
the internal mixed-provenance test (F1 0.943 vs. 0.855). This is a reproducible
pipeline comparison, not a claim of real Philippine improvement. No model,
feature, calibration, or threshold change was made from this run.

## 2. Proposed release criteria (provisional)

The following numbers are starting points for owner review, not approved policy
or claims that the current model passes:

- Before making a Philippine performance claim, obtain at least 300 consented,
  independently labeled ham messages in each critical category: OTP,
  bank/e-wallet alert, and delivery. Include at least 50 per language in any
  language/category cell reported; require 300 examples per class and language
  before making a language-specific performance claim.
- Include at least 10 independent donor/campaign groups for each reported
  category or language slice. Keep donors and campaigns disjoint across
  development and final evaluation; use a later collection period for the
  final set when reliable dates exist.
- For candidate review, require the upper 95% Wilson bound on false-positive
  rate to be at most 5% in each critical legitimate category and the lower
  95% bound on spam recall to be at least 80% overall and in any language for
  which a claim is made. These are proposed tradeoffs and need owner approval.
- Require calibration checks on the frozen evaluation data and report Brier
  score, calibration error, intervals, and sample counts. Do not use the
  calibrated score as a fraud probability.
- Compare candidates and the incumbent on identical development splits.
  Propose a maximum 2 percentage-point false-positive-rate regression in each
  critical category, with uncertainty reported; any exception needs explicit
  owner review before the final holdout is opened.
- Keep operational gates from docs/RETRAINING.md: no message-body logging or
  server-side message persistence, successful /ready, known artifact
  provenance, and a verified rollback path.
- For comprehension review, use the provisional thresholds in
  docs/HUMAN_REVIEW.md; a misunderstanding of a low score as a safety
  guarantee blocks the interface until the copy is revised and retested.

These criteria must be approved or replaced by the project owner before a real
release evaluation. Under the current evidence, the detector does not meet a
validated Philippine performance gate because the required consented data do
not exist.

## 3. Collection and labeling plan

The existing intake and labeling process in docs/DATA_COLLECTION.md is the
source of truth. It already requires a documented consent scope, revocable
consent, separate consent records, pseudonymous donor/campaign groups,
de-identification before storage, a local preflight, two independent labels,
adjudication of disagreements, and deletion of derived artifacts after
withdrawal or retention expiry. The current importer treats consent flags as
operator attestations; it cannot prove consent or catch every identifier.

Proposed coverage matrix:

| Label | Priority categories | Language coverage |
|---|---|---|
| ham | OTP, bank/e-wallet alerts and receipts, delivery notices, bills, promotions, personal/everyday messages | English, Filipino, Taglish |
| spam | credential/OTP theft, bank/e-wallet impersonation, parcel fees, prize claims, job/loan lures, investment claims, government/telco impersonation | English, Filipino, Taglish |

Recruitment, if later authorized, should request only masked, expired messages
under an approved consent process. Never request live OTPs, credentials,
account numbers, identifying screenshots, or message content in public
channels. Reviewers label independently before discussion; a third reviewer
adjudicates disagreements. Preserve an ambiguous label state and exclude
unresolved examples from training and evaluation.

Create the final evaluation set before experiments. Use a pseudonymous split
group that prevents either donor or campaign overlap; when both relationships
connect records, keep the connected group together. Freeze the final set,
store it under the same access and deletion controls as its source, and do not
use its errors to tune features, calibration, or thresholds.

Human actions still required: approve the consent text, retention period,
coverage and release targets; appoint a data steward, labelers, and adjudicator;
and obtain participant donations through an authorized process. No participants
have been contacted and no real messages were collected for this work.

## 4. Development experiments

No changes to preprocessing, model selection, calibration, or decision
threshold were justified by the available evidence. Public-English data do not
represent Philippine message language or category mix, and the synthetic
Philippine examples cannot validate field errors. Do not treat the synthetic
holdout as an iterative development set.

After a consented development set is available, compare word, character, and
combined TF-IDF candidates with the same group-aware splits and seed. Record
the report, source hashes, split fingerprints, class/category/language support,
confidence intervals, and candidate artifact hash in a fresh benchmark
directory for each configuration. Use development data for error review and
candidate selection; open the frozen evaluation set once after criteria and
candidate selection are fixed. Add complexity only if these controlled
experiments show a repeatable baseline limitation.

## 5. Interface changes and comprehension review

The single-message result now presents the assessment, score, a visible
limitation, and one immediate next step. The full text-pattern explanation is
collapsed under a keyboard-operable disclosure. Model version, data
provenance, and thresholds are under a separate collapsed disclosure. Browser
and model readiness plus the retry control remain visible. Batch and comparison
views retain their detailed independent results.

The human-review protocol now contains a short comprehension script and
provisional success criteria. No participant sessions have occurred; report
the criteria as prepared, not validated. Automated browser checks cover opening
and closing model details by keyboard, mobile reflow, missing-model behavior,
and API recovery. Manual screen-reader review and participant comprehension
testing remain outstanding.

## 6. Limited pilot and rollback readiness

No public deployment or participant recruitment is authorized by this plan.
The proposed first pilot is a local, moderated usability study using fictional
fixtures only, after owner approval of recruitment and consent materials. It
does not test predictive accuracy. A later field pilot requires the consented
data gates above, a privacy review, an approved owner, and a named operator.

For any later pilot:

- Owner: approves scope, criteria, stop conditions, and release decision.
- Data steward: verifies consent, access, retention, withdrawals, and deletion.
- Two labelers plus an independent adjudicator: produce reviewed labels.
- Operator: checks readiness, monitors service-level aggregates, and can
  restore the previous artifact.
- Record only request counts, latency percentiles, status/error counts,
  artifact version, and aggregate correction counts. Disable request-body
  logging. Treat corrections as unverified investigation signals, never as
  ground truth or automatic training data.
- Stop for any message-content exposure, unavailable model beyond the existing
  operational limit, material increase in errors, or repeated reports of a
  critical legitimate-message category. Follow the incident and rollback
  procedure in docs/RETRAINING.md.

Rollback steps are documented in docs/RETRAINING.md and
docs/DEPLOYMENT.md. They were exercised locally by starting the API with the
phase-baseline candidate, restarting with the previously saved
demo_synthetic_combined artifact, and switching back to the candidate.
Each start returned /ready=ready and the expected model version from
/model-info. This verifies path selection and startup readiness only; it is
not a production rollback or an evaluation of either artifact's accuracy.

The proposed initial pilot is a two-week local, moderated usability round with
5–8 adult volunteers, subject to owner approval of recruitment and consent
materials. Use fictional fixtures only; do not submit private participant SMS.
Entry criteria are an approved script, accessible build, successful readiness
and rollback checks, and an observer trained to record task outcomes without
message content. Success means the provisional comprehension criteria in
docs/HUMAN_REVIEW.md are met, service recovery works, and no private data is
collected. Stop for a privacy exposure, a participant interpreting the score
as a guarantee or instruction to punish a sender, or a service issue that
breaches the runbook limits. Any repeat of the study after copy changes uses
new participants.

The app does not currently provide aggregate telemetry. For a future pilot,
the operator must prepare message-free counters for request totals, p50/p95
latency, status/error counts, model version, and opt-in correction counts,
with request-body and per-user logging disabled. A correction cluster prompts
human review and does not establish a verified error rate.

## 7. Validation and remaining work

Validation completed on 2026-10-24:

- Python suite: 326 passed. One existing Starlette deprecation warning notes
  the TestClient/httpx integration.
- Ruff lint and format checks passed; mypy passed for src and api.
- JavaScript module tests passed. Browser smoke tests passed, including
  keyboard operation of the disclosure, mobile reflow, missing-model behavior,
  and API recovery.
- Desktop (1365×900) and mobile (390×844) screenshots were visually reviewed.
  The result and one next step remained visible, details began collapsed, and
  neither size had horizontal overflow.
- The rollback artifact switch and return were verified as described above.
- git diff --check passed. The UCI import, baseline candidate, and report are
  in ignored paths; no SMS data or model artifact was added to Git.

Still required before any real-world claim or field pilot:

1. Owner approval of provisional release and comprehension criteria.
2. Approved consent text, collection authority, secure storage, and retention.
3. Consented, de-identified messages with independently adjudicated labels and
   campaign/donor separation.
4. A development set and a frozen, later-period final evaluation set with
   adequate category and language support.
5. Participant comprehension sessions and a manual assistive-technology
   review.
6. A locally exercised rollback using known artifact versions, followed by
   owner approval before any live pilot.
