# Consented data collection and labeling

This guide covers future collection and research use of Philippine SMS data.
The optional donation flow is separate from prediction, disabled by default,
loopback-only, and unavailable in production mode. Submission never triggers
training or evaluation. See [DONATION_INTAKE.md](DONATION_INTAKE.md) for local
operator setup and [privacy-notice.md](privacy-notice.md) for the current
donor-facing notice (`2026-11-01-v4`).

## Pre-collection governance handoff

**No real-message collection is approved by this repository change.** Keep
`SMSD_DONATIONS_ENABLED` unset until the project owner completes and signs one
pre-collection go/no-go record after qualified privacy/legal review. The record
must resolve every item below; an empty or deferred item means no-go.

| Role | Required decision or control before collection |
|---|---|
| Project owner | State the study question, intended use, eligible contributors, recruitment and consent process, controller identity/contact, lawful-basis decision, access list, collection window, approved notice, retention periods for source/export/splits/model/reports, withdrawal handling for derived artifacts, backup deletion, incident owner and escalation path, and release decision. Appoint a separate sealed-test custodian. |
| Qualified privacy/legal reviewer | Review controller/processor roles, lawful basis, notice, proportionality, minimization, safeguards, data-subject rights, retention/deletion, any assessment/registration/notification duties, withdrawal, backups, and incident handling under applicable Philippine requirements. Record unresolved legal questions; do not treat this software as a compliance finding. |
| Data steward | Keep the consent/withdrawal register separate and access-controlled; verify each message's active purpose-specific consent, sharing authorization, expiry, and withdrawal status; manually screen PII; assign opaque campaign groups; track deletion through exports, splits, backups, and any derived model; keep a content-free audit trail. |
| Two independent labelers | Follow confidentiality and conflict-of-interest instructions; receive separate randomized sheets with masked messages only; label without donor hints, each other's judgments, model scores, or predictions; return first-pass annotations before discussion. A third independent adjudicator resolves disagreements. |
| Sealed-test custodian | Restrict test-file access from training and threshold selection; retain it until the plan and exact model/development hashes are registered; authorize one evaluation attempt and preserve its attempt record. |

The go/no-go record must name owners and dates for access review, withdrawal
requests, backup deletion, expiry/purge, and incident triage. The application
cannot verify a separate consent register, enforce reviewer blinding,
authenticate human roles, prove contributor independence, or prove the test was
previously unseen. Campaign grouping avoids sender identifiers and limits
template leakage, but it does not prove contributors are independent.

This handoff specifies no participant, message, or campaign sample-size target.
Before any sealed test is opened, the owner and qualified reviewer must justify
the study size, language/category coverage, effective independent-campaign
count, and acceptable uncertainty intervals for the intended use and error
costs, then register those criteria in the evaluation plan. No repository
default establishes adequate evidence.

## Evidence status

No representative real Philippine corpus has been collected; no independently
labeled, consented Philippine corpus or trained model artifact is currently
available for this workflow. The local PH Spam + Marketing SMS
snapshot is a public one-person inbox with 1,664 normalized labeled rows; it is
not consented research data and cannot establish representative Philippine
performance. The supplied ZIP and CSV are the same snapshot and must be counted
once. Supplied EDA notebooks are untrusted artifacts and must not be executed.
See [DATASET_INVENTORY.md](DATASET_INVENTORY.md) and
[`data/external/README.md`](../data/external/README.md) for source status.

## 1. Consent and privacy boundaries

Before enabling the local form, an operator must identify themselves and a
contact route, review the actual purpose and legal basis, assess the host and
access controls, and obtain qualified privacy/legal advice where needed. The
software does not establish legal compliance. Keep the service on localhost;
do not put it behind a public reverse proxy, expose it to a network, or deploy
the intake.

The versioned notice asks for separate affirmative choices:

- authorization to share a message sent directly to the submitter or written
  by them;
- consent to local human review and labeling;
- an optional, separate choice to consider it for future model research,
  including training or evaluation.

Never solicit someone else's private conversation, a live OTP, password, PIN,
credential, complete sender details, contact list, or account number. The form
does not ask for names, phone numbers, email addresses, or sender identifiers.
Likely PII screening runs before database storage, in storage validation, and
again before export. It is conservative but incomplete; donors must inspect and
redact flagged text themselves. URLs remain research signals and are flagged
for donor review. No scanner proves that data is anonymous or safe to share.

SQLite storage lives locally with restrictive permissions and a 90-day active
retention period. The host operator remains responsible for full-disk
encryption, account access, physical security, backup deletion, and avoiding
cloud-synced folders. The application does not encrypt the database. Withdrawal
erases message and label fields and retains only a content-free tombstone for
the stated period. A separate consent register links opaque consent tokens to
the relevant withdrawal process; keep it separately protected and never put
names or contact identifiers in the research CSV.

The form is only an intake queue. Exported donations have blank target labels,
`pending_review` status, and `eligible_for_modeling=false`. The research
pipeline never consumes submissions automatically. A separate operator must
verify active consent, research scope, retention, and authorization against the
restricted register, then obtain independent labels before a row can pass
preflight.

### Data Privacy Act considerations

The Philippine Data Privacy Act of 2012 (Republic Act No. 10173), its
Implementing Rules and Regulations, and National Privacy Commission (NPC)
issuances may apply. Before operating collection, assess controller/processor
roles, purpose and lawful basis, transparency, proportionality, safeguards,
retention and disposal, rights requests, breach response, and any applicable
registration or notification duties. Do not infer that this repository's
technical controls make a collection compliant. Public availability is not
consent; scraping public pages is not automatically exempt from data-protection
requirements. Dataset license and privacy basis are separate questions.

Primary official references: [Republic Act No. 10173 (Official Gazette)](https://officialgazette.gov.ph/2012/15/republic-act-no-10173),
[DPA Implementing Rules and Regulations (NPC)](https://privacy.gov.ph/implementing-rules%20regulations-data-privacy-act-2012/),
[NPC Circular No. 2023-04, Guidelines on Consent](https://privacy.gov.ph/wp-content/uploads/2023/11/NPC-Circular-No.-2023-04_Guidelines-on-Consent_07Nov2023.pdf),
[NPC data-subject rights](https://privacy.gov.ph/data-subject-rights/),
[NPC right to erasure or blocking](https://privacy.gov.ph/right-to-erasure-or-blocking/),
and [NPC Advisory No. 2026-01 on publicly available personal data](https://privacy.gov.ph/wp-content/uploads/2026/04/SGD_A_1.pdf).
These references are not legal advice. The operator must resolve applicability
and deployment-specific questions with qualified counsel or a privacy officer.

## 2. Schema and independent labeling

Use the exact header in
[`data/templates/consented_ph_sms_template.csv`](../data/templates/consented_ph_sms_template.csv).
The message file contains minimized research metadata; the reversible consent
mapping stays in a separate restricted register.

Keep these concepts distinct:

- `label`: the detector's spam/ham target. `spam` may include unsolicited
  advertising and does not itself mean fraud; `ham` means a message a recipient
  would reasonably expect or want.
- `scam_assessment`: a separate `suspected`, `not_suspected`, or `unclear`
  assessment. It is not a finding of criminal conduct.
- `category`, `language`, and `received_at`: controlled category/language codes
  and the least precise reliable date needed for time-separated analysis. Use
  `unknown` when uncertain; do not invent timestamps.
- `reviewer_a_*` and `reviewer_b_*`: separate first-pass decisions and
  confidence (`low`, `medium`, `high`). Both reviewers must be different
  people. Neither sees the other's labels, donor hint, model prediction, score,
  or explanation.
- `adjudicated_*` and `review_status`: final target and scam assessment after
  independent review. Disagreement requires a third reviewer who did not make
  either first-pass decision. Low-confidence, unresolved, withdrawn, expired,
  or privacy-flagged rows are excluded.
- `consent_record_id`, `consent_version`, `consent_scope`, `consent_date`,
  `retention_until`, `consent_verified`, `consent_active`, `review_consent`,
  `model_research_consent`, and `authorized_to_share`: minimal consent
  declarations checked against the separate register. These fields are
  attestations, not proof by themselves.
- `group`: an opaque campaign/template-family grouping code. It must not encode
  or derive from donor, sender, phone, or other direct identifiers. A group
  exists to prevent related campaigns/templates from crossing a split; it is
  not a donor ID. Keep any restricted mapping needed to support withdrawal
  outside the research file.

Donor-provided hints are never ground truth. Two reviewers label the same
masked message independently while blind to model output. A third independent
adjudicator resolves disagreement; preserve both original judgments and the
final decision. Follow the practical workflow in
[`HUMAN_REVIEW.md`](HUMAN_REVIEW.md). Do not recruit or contact participants as
part of repository development.

## 3. Local validation and review queue

Start with the blank template in an encrypted workspace outside Git. Use an
opaque `consent_record_id` from the separate register and a distinct campaign
group. Never use a donor/sender identifier or a hash of one to build groups.
Record only the consent scope, notice version, dates, controlled category and
language, independent reviews, and adjudication needed for the stated purpose.

Run privacy-safe preflight against the private CSV:

```bash
.venv/bin/python -m src.consented_data /secure/workspace/batch.csv --purpose training
.venv/bin/python -m src.consented_data /secure/workspace/batch.csv --purpose evaluation
```

The validator reports aggregate counts and CSV row numbers/rule codes only; it
never echoes SMS text or matched PII. It requires active, verified consent,
sharing authorization, model-research permission for research use, two
independent labels, adjudication, dates for evaluation, and both target classes
for evaluation. It rejects exact and detected template-family duplicates that
span campaign groups. It cannot prove the consent register is genuine, detect
all PII, or ensure that reviewers followed blinding instructions. Resolve all
findings manually and revalidate.

The donation export is a review staging queue, not a dataset:

```bash
make export-donations OUTPUT=/secure/workspace/review-staging.csv
```

It omits withdrawn/expired or newly PII-flagged submissions, removes donor hints
and model outputs, and cannot be used directly for training or evaluation. Two
reviewers label it outside the application; an operator then verifies consent
and fills the full reviewed-data template. Never commit raw or reviewed real
messages or pass them to CI.

## 4. Leakage-resistant split and sealed test

Only an approved, independently reviewed, consented batch with active
`model_research` scope (or equivalent explicit training-and-evaluation scope),
all required consent choices, valid `received_at` values, and both spam/ham
labels may enter this workflow. The batch must be approved for both development
and final evaluation. The split command preflights both purposes, rejects
duplicates/template families that span campaign IDs, then holds whole campaign
groups chronologically. It writes the development CSV and final evaluation CSV
to **separate private directories**, plus a content-free hash and membership
manifest next to the development file:

```bash
make split-consented \
  DATA=/secure/inbox/approved-reviewed.csv \
  DEVELOPMENT_DIR=/secure/development \
  EVALUATION_DIR=/secure/sealed-test
```

The development file contains older training and validation groups. The
trainer makes its own chronological train/validation split from that file and
selects the threshold on validation only. The newest group-separated file is
the sealed test. Train the candidate without the default external holdout:

```bash
.venv/bin/python -m src.train \
  --data /secure/development/consented-development-<hash>.csv \
  --holdout none --split-by time --threshold-policy validation \
  --output /secure/candidate/model.pkl
```

No one involved in training or feature/threshold decisions should inspect the
sealed message file. A separate custodian should retain access and reveal it
only for the one registered evaluation. Software cannot prove that the test
was not previously viewed; the manifest states this limitation. If a genuinely
separate custodian is unavailable, do not describe the test as sealed or
independent.

Before evaluation, register an analyst-authored plan using
[`templates/consented-evaluation-plan.json`](templates/consented-evaluation-plan.json).
Fill in exact model/data hashes, development and test membership fingerprints,
fixed model version and validation-selected threshold, intended use, minimum
language/category coverage, campaign-group requirement, and maximum acceptable
campaign-cluster interval widths. Record specific rationales before the test
file is opened. There is no universal row-count target: set criteria from the
intended use, error costs, effective independent campaign count, and the
precision needed in uncertainty intervals. The code's two-group floor is only
the mathematical minimum for cluster calculations, not evidence of adequacy.

The evaluation command requires the exact development file, model artifact,
sealed evaluation file, and plan. It verifies model provenance, threshold
selection policy, hashes, membership, chronology, group isolation, duplicates,
coverage, and uncertainty gates. If a gate fails or no trained artifact exists,
it writes only a private readiness report and no performance headline:

```bash
make eval \
  DATA=/secure/sealed-test/consented-evaluation-<hash>.csv \
  TRAINING_DATA=/secure/development/consented-development-<hash>.csv \
  MODEL=/secure/candidate/model.pkl \
  EVALUATION_PLAN=/secure/registered-plan.json \
  OUTPUT_DIR=/secure/reports
```

Keep both inputs, plan, manifest, report, model, backups, and any derived
artifacts in protected local storage. Reports contain aggregate metrics and
content-free fingerprints only, but small subgroup results can still disclose
sensitive information. Set and enforce retention/deletion rules for source
files, backups, and derived artifacts before collection begins.

## 5. Official data handling, retention, and limits

Keep public, synthetic, consented, and UCI results separate; never combine them
into a single headline. Public availability and dataset licensing do not
constitute donor consent. The local one-person public inbox is not a substitute
for consented collection or a representative evaluation. See
[`evaluation.md`](evaluation.md) for public source decisions and the current
benchmark status.

The donation queue retains active submissions for 90 days from consent and
purges them on the next database access. The operator must delete backups on
the same schedule. For research-approved records, select and document the
shortest necessary retention period before collecting them; assess withdrawal
and expiry against source files, splits, models, reports, and backups. A
withdrawal can require rebuilding derived artifacts; the operator must document
what can and cannot be removed. Do not state that deleting a source row
automatically removes learned influence from an existing model.

## 6. Batch checklist

- [ ] Approved purpose, lawful basis, notice version, contact, access control,
      retention, deletion, and backup plan documented by the owner and
      qualified privacy/legal reviewer.
- [ ] Submitter is authorized; explicit review, sharing, and research choices
      verified against the separate consent register.
- [ ] No live codes, credentials, full sender details, names, contact details,
      or unmasked likely PII; manual privacy review completed.
- [ ] Two blind independent spam/ham and scam reviews, confidence, and any
      independent adjudication recorded.
- [ ] Campaign/template grouping uses no donor/sender identifier; dates are
      valid and as coarse as the temporal design permits.
- [ ] Exact/near duplicate checks and chronological group split pass; the
      sealed test remains with an independent custodian.
- [ ] Evaluation plan, coverage, uncertainty tolerances, and intended use were
      recorded before the final test is opened.
- [ ] Reports remain private, content-free, separated by evidence source, and
      carry source/model hashes and limitations.
