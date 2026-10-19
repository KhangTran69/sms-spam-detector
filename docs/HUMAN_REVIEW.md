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

- Ask participants to review a balanced, randomized set of synthetic examples:
  likely scam, suspicious, and looks safe; include legitimate OTPs and account
  alerts, plus scam links, prize claims, fees, impersonation, and Taglish.
- For each example, ask: What do you think this message is? What part of the UI
  influenced you? What would you do next? Was the wording clear or too certain?
- Record only the example ID, participant pseudonym, their expected label,
  confidence, category, usability issue, and notes with no personal details.
- Do not coach participants toward the model's answer. Keep their first label
  before showing any explanation, then ask if the safety guidance is actionable.
- Have two reviewers independently label any candidate real examples. Resolve
  disagreements with a documented adjudicator; keep low-confidence/ambiguous
  samples out of benchmark sets until resolved.

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
