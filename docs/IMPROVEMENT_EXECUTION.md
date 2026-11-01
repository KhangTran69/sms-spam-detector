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

The release criteria must be approved and registered before the final test is
opened. Do not use fixed example counts as a universal sufficiency rule. Set
minimum language/category coverage and maximum uncertainty widths from the
intended use, expected false-positive and false-negative costs, and the
effective number of independent campaign groups. Explain why each threshold is
adequate for the specific decision. The evaluator's two-group floor only
allows cluster calculations; it is not evidence of adequate support. Report
per-class/category/language sample counts and missingness, confusion counts,
and campaign-cluster uncertainty. If the registered criteria are unmet, report
readiness blockers rather than a performance claim.

Compare candidates and the incumbent on identical development splits; set any
false-positive or recall tolerances explicitly with an uncertainty rationale.
Do not tune on the frozen test or use a calibrated spam/ham score as a fraud
probability.
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

The intake and labeling process in docs/DATA_COLLECTION.md is the source of
truth. It requires separate consent choices, a restricted consent register,
de-identification review, two independent labels, an independent adjudicator
for disagreements, campaign/template grouping, a local preflight, and
withdrawal/retention handling. Consent fields are operator attestations; they
cannot prove consent or catch every identifier. The group code must not encode
or derive from donor or sender identifiers. Campaign separation therefore does
not establish independent contributors; disclose this limitation rather than
claiming donor-level separation.

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

Create the final evaluation set before experiments. Use campaign/template
groups and chronological separation, then freeze the final set under an
independent custodian. Do not retain donor/sender IDs to derive groups. Because
contributor-level linkage is not available, campaign groups cannot guarantee
that all messages from one contributor are isolated; document this limitation
and avoid claims of independent contributors. Do not use final-test errors to
tune features, calibration, or thresholds.

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

The human-review protocol contains a comprehension script and questions for a
future owner-approved review. No participant sessions have occurred; the
questions are prepared, not validated, and no passing percentage is set.
Automated browser checks cover opening and closing model details by keyboard,
mobile reflow, missing-model behavior, and API recovery. Manual screen-reader
review and participant comprehension testing remain outstanding.

## 6. Limited pilot and rollback readiness

No public deployment, participant recruitment, or real-message collection is
authorized by this plan. The disposable synthetic rehearsal described in
`evaluation.md` checks the software workflow only. It is not a human study,
consented participant data, or predictive evidence. The pre-collection
go/no-go handoff in `DATA_COLLECTION.md` is authoritative; collection stays
disabled until the project owner signs it after qualified privacy/legal review.
Any future usability session using fictional examples is a separate owner
decision and cannot be treated as a model evaluation.

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

No initial participant count, study duration, or pass threshold is proposed
here. Before any human session, the project owner and qualified reviewer must
approve its purpose, recruitment, consent, script, decision rule, and data
handling. For a future real-message study, they must justify and register
coverage and uncertainty criteria before the sealed test is opened. Do not
collect messages or claim model performance based on the synthetic rehearsal.

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

Still required before any real-message collection or real-world claim:

1. A signed owner go/no-go record after qualified privacy/legal review that
   resolves the controller/contact, lawful basis, access, retention, withdrawal
   and derived-artifact handling, backup deletion, and incident process.
2. Named and trained data steward, two independent labelers, adjudicator, and
   separate sealed-test custodian, with access and blinding controls.
3. Active purpose-specific consent, independently adjudicated labels,
   campaign/time separation, and documented limits on contributor-level
   independence.
4. Owner- and reviewer-justified coverage and uncertainty criteria registered
   before the sealed test is opened; this project sets no sample-size target.
5. Manual screen-reader review and any separately approved usability review.
6. A locally exercised rollback and a named operator before any service pilot.
