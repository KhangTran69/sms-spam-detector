# Human Review Protocol

This protocol is a plan for future participant review. **No participant study
has been conducted and no consented Philippine SMS corpus is available.** A
public one-person inbox snapshot is present only in ignored local storage; do
not describe it as consented research or as representative field evidence.

## Goals

- Check whether Filipino, Taglish, and English speakers understand the verdict,
  risk band, uncertainty language, and safety guidance.
- Find false positives on legitimate OTPs, bank/e-wallet alerts, delivery
  notices, promos, and personal messages.
- Find false negatives across scam categories and identify confusing UI signals.

## Recruitment and consent

1. Recruit adult Filipino/Taglish SMS recipients through an appropriate,
   voluntary research process. Do not recruit by sending people scam messages.
2. Explain the purpose, what will be shown, what feedback is collected, who can
   access it, retention, and how to withdraw. Participation must be optional and
   unrelated to access to a service.
3. Start with the synthetic fixtures and clearly label them as fictional. If a
   participant chooses to contribute a real message, use a separate written
   consent step and the de-identification workflow in `DATA_COLLECTION.md`.
4. Never ask for a live OTP, PIN, password, account number, full sender number,
   name, address, or screenshot. Redact before any researcher sees a contributed
   message. Delete accidental secrets immediately and record the incident.

## Independent SMS labeling protocol

Use only messages whose active, versioned consent record explicitly covers the
planned use. The donation form's required consent covers local review and
labeling; model research is a separate optional choice. Verify authorization to
share, withdrawal status, and retention against the restricted consent
register. A donor's optional label hint is not ground truth and is omitted from
the reviewer export.

Two reviewers independently receive the same masked message, a randomized
record ID, and the same task instructions. They must not see each other's
labels, the donor hint, the detector's prediction/score, or model explanations.
Return separate annotation sheets before any discussion. The reviewer export
contains no prediction field; the intake validator rejects unrecognized extra
columns, including prediction fields. This workflow depends on the operator's
assignment and access controls, which the application cannot enforce.

For each message, record these separate outcomes:

- **Spam/ham target:** `spam` includes unsolicited bulk/marketing or spam-like
  messages; `ham` is a message a recipient would reasonably expect or want.
  This label does not itself assert fraud.
- **Scam assessment:** `suspected`, `not_suspected`, or `unclear`, based on the
  message text and available consented context. It is an assessment, not a
  finding that a crime occurred.
- **Category and language:** use short controlled codes such as
  `bank_alert`, `delivery`, `promotion`, `phishing`, `en`, `fil`, `tl-en`, or
  `unknown`. Do not put free-text names, senders, or identifiers in metadata.
- **Confidence:** each reviewer and the final adjudicator select `low`,
  `medium`, or `high` for the spam/ham label. Low-confidence cases remain out
  of model imports.

If the two reviewers disagree on spam/ham or scam assessment, a third reviewer
who is neither original reviewer independently adjudicates. Preserve the two
first-pass labels and record the final adjudicated values separately. Mark only
resolved rows `review_status=adjudicated`; unresolved, withdrawn, expired,
privacy-flagged, or low-confidence rows are excluded. Never overwrite review
history silently.

Assign an opaque campaign group from documented message-template/campaign
evidence and a restricted grouping register. Do not retain, hash, or derive
group IDs from sender phone numbers or other direct identifiers. Record only
the date precision needed for chronology. The same campaign/template group
must stay on one side of every train/validation/test split. For final temporal
evaluation, `received_at` must be present and evaluation consent must be active.
Campaign grouping reduces related-template leakage; it does not establish
contributor-level independence. One contributor may submit messages from
multiple campaigns, and one campaign may include messages from multiple
contributors. Do not interpret campaign count as participant count.

## Review session

- This protocol sets no participant or message sample-size target. The project
  owner and qualified privacy/legal reviewer must justify the study design and
  document any coverage and uncertainty criteria before recruitment or data
  collection. Do not open the sealed test before those criteria are registered.
- For a UI comprehension session, use a balanced, randomized set of clearly
  fictional examples across the UI's spam-signal bands. Include legitimate
  OTPs, account alerts, delivery notices, and personal Taglish alongside
  fictional scam patterns. Do not collect real messages in this session.
- For each example, ask: What do you think this message is? What part of the UI
  influenced you? What would you do next? Was the wording clear or too certain?
- Before showing details, ask the participant to explain what the score means
  and whether a low score guarantees safety. Ask where they would verify an
  unexpected bank or delivery request and what they would do with an OTP request.
- Check whether participants can find the text-pattern details with a keyboard
  and whether the visible service status and retry control are clear.
- Record only the example ID, participant pseudonym, their expected label,
  confidence, category, usability issue, and notes with no personal details.
- Do not coach participants toward the model's answer. Keep their first label
  before showing any explanation, then ask if the safety guidance is actionable.
- Have two reviewers independently label any candidate real examples. Resolve
  disagreements with a documented adjudicator; keep low-confidence/ambiguous
  samples out of benchmark sets until resolved.

## Comprehension questions and decision rule

Ask these questions and record the answers. The project owner and privacy
reviewer must agree on a decision rule before the session; this guide does not
set a passing percentage or release threshold:

- Does the participant understand that the model estimates spam versus
  legitimate-message patterns, not whether a sender committed fraud?
- Does the participant understand that a low score does not guarantee safety?
- Would the participant verify an unexpected financial request through an
  independently obtained official channel and avoid sharing an OTP or PIN?
- Could any wording be mistaken for an instruction to block, report, or punish
  a sender? Record such a misunderstanding for owner review before release.
- Can the participant use the details controls with a keyboard? Record
  screen-reader issues separately; this session does not replace dedicated
  screen-reader testing.

If a material misunderstanding appears, review and revise the wording or layout
before making a release decision. Qualitative feedback is not a model
performance estimate and cannot establish population-wide usability.

## Analysis and release gate

- Report participant count, message counts by class/category/language, missing
  responses, and how many examples were synthetic versus consented real data.
- Summarize confusion on the terms "likely scam", "suspicious", probability,
  and the recommended action. Track OTP and legitimate-alert false-positive
  reports separately.
- Update copy or UI only when supported by review notes; re-run accessibility
  checks and the relevant automated UI/API checks after changing the interface.
- Human feedback is qualitative usability evidence, not a performance estimate.
  Model accuracy claims require a separate, consented, campaign/time-separated
  holdout described in `DATA_COLLECTION.md`.

## Ready-to-use de-identified intake file

Copy `data/templates/consented_ph_sms_template.csv` to a secure working location,
not into a public issue or chat. Keep the original consent record separately
from the pseudonymous dataset. The repository ignores `data/raw/` real data and
`data/feedback/` reports by default; verify `git status --ignored` before any
commit involving data.
