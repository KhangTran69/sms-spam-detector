# Human Review Protocol

This protocol is a plan for future participant review. **No participant study has
been conducted and no real Philippine SMS data is currently available in this
repository.** Do not describe these steps as completed research.

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

## Review session

- For an initial formative round, plan 5–8 adult Filipino/Taglish SMS recipients.
  Use a balanced, randomized set of clearly fictional examples across the UI's
  high, elevated, and low spam score bands. Include legitimate OTPs, account
  alerts, delivery notices, and personal Taglish alongside fictional scam
  patterns. Do not collect real messages in this comprehension round.
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

## Provisional comprehension criteria

These are proposed study criteria, not an approved production policy. Confirm
them with the project owner before using them to make a release decision:

- At least 80% of participants explain that the model estimates spam versus
  legitimate-message patterns, not whether a sender committed fraud.
- At least 80% say that a low score does not guarantee a message is safe.
- At least 80% choose an independently obtained official channel to verify an
  unexpected financial request, and say not to share an OTP or PIN.
- No participant should mistake the score as an instruction to block, report,
  or punish a sender. Any such misunderstanding is a blocking copy issue to
  revise and retest.
- Participants can open and close the model and message-pattern details with
  keyboard controls. Record screen-reader issues separately; this quick test
  does not replace a dedicated screen-reader review.

If a criterion fails, revise the wording or layout and repeat the same tasks
with new participants. A small formative round can find confusion; it cannot
estimate model accuracy or establish population-wide usability.

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
