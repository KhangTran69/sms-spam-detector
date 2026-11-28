# Comprehension session script (facilitator template)

This is a ready-to-run facilitator script for the UI comprehension session
described in [HUMAN_REVIEW.md](../HUMAN_REVIEW.md) ("Review session"). It is a
plan, not a report: **no comprehension session has been run and no results
exist.** The project owner and privacy reviewer must agree on the decision rule
before the first session, as HUMAN_REVIEW requires; this script does not set a
passing percentage or a release threshold.

## Session rules (from HUMAN_REVIEW.md)

- Every example shown is **fictional**. Use only the synthetic fixtures in the
  table below, copied from tracked synthetic files (`data_kind=synthetic`).
  Never show a real message, and do not collect real messages in this session.
- Never ask for a live OTP, PIN, password, account number, full sender number,
  name, address, or screenshot.
- Do not coach participants toward the model's answer. Record each
  participant's first label before showing any explanation, then ask whether
  the safety guidance is actionable.
- Randomize the example order for each participant; the table below is grouped
  by band only for preparation.
- Record only the example ID, participant pseudonym, their expected label,
  confidence, category, usability issue, and notes with no personal details.
- Participation is optional and unrelated to access to any service.

## Before the session (facilitator preparation)

1. Score each fixture below with the local detector and confirm the band the
   UI actually displays. The "Expected band" column is a preparation estimate,
   not a verified result; if a fixture does not display in the listed band,
   substitute an alternate fixture from the same tracked file and note the
   swap (without personal details) in the session record.
2. Randomize one example order per participant.
3. Prepare the recording sheet: example ID, participant pseudonym, expected
   label, confidence, category, usability issue, notes. Nothing else.
4. Recruit and brief participants per HUMAN_REVIEW "Recruitment and consent".
   A participant who wants to contribute a real message goes through the
   separate written consent step and the de-identification workflow in
   `DATA_COLLECTION.md` — not through this session.

## Fictional fixture set (12 examples: 3 bands × 4 message kinds)

All fixture text below is copied verbatim from tracked synthetic files
(`data/raw/ph_holdout.csv`, `data/raw/ph_supplement_3.csv`,
`data/raw/ph_supplement.csv`). Senders, amounts, codes, numbers, and URLs in
them are fictional and exist only as synthetic templates. They are not real
messages and must never be described as real.

| Example ID | Expected band | Message kind | Fictional fixture (verbatim from tracked synthetic file) | Tracked source |
|---|---|---|---|---|
| LS-OTP | Likely scam (`likely_scam`, high spam score) | OTP request | Ate/Kuya, ShopeePay agent po ito. Pakibigay ang OTP para ma-reverse ang maling transfer na ₱1,099. | `ph_holdout.csv` row 140 (`otp_theft`, spam) |
| LS-BANK | Likely scam (`likely_scam`, high spam score) | Bank/e-wallet alert | BDO: Account suspended due to failed login attempts. Reactivate here: http://bit.ly/bdo-react | `ph_holdout.csv` row 3 (`bank_phishing`, spam) |
| LS-DEL | Likely scam (`likely_scam`, high spam score) | Delivery notice | PHLPost: Your parcel is on hold. Pay ₱120 clearance fee at phlpost-clearance.top before Nov 2. | `ph_holdout.csv` row 20 (`parcel_scam`, spam) |
| LS-TL | Likely scam (`likely_scam`, high spam score) | Personal Taglish | Tita, nahospital si mama. Kailangan ng PHP 20,000 agad. Send sa GCash 09178889999 at huwag sabihin kay papa. | `ph_supplement_3.csv` row 42 (`relative_scam`, spam) |
| SU-OTP | Suspicious (`suspicious`, elevated) | OTP request | Hi po, si Bea ito. Na-send ko sa number mo yung code ko by mistake. Pakibalik yung 6 digits? | `ph_holdout.csv` row 138 (`otp_theft`, spam) |
| SU-BANK | Suspicious (`suspicious`, elevated) | Bank/e-wallet alert | BPI: A new device logged in. If this wasn't you, verify at bpi-alert.site/login now or account will be locked. | `ph_supplement_3.csv` row 31 (`bank_phishing`, spam) |
| SU-DEL | Suspicious (`suspicious`, elevated) | Delivery notice | J&T: Parcel held - pay ₱75 customs fee now: bit.ly/jt-fee75 | `ph_holdout.csv` row 6 (`delivery_scam`, spam) |
| SU-TL | Suspicious (`suspicious`, elevated) | Personal Taglish | Hi po, I'm looking for someone to talk to. Can you send load to 09177778888? God bless. | `ph_holdout.csv` row 30 (`romance_scam`, spam) |
| SA-OTP | Looks safe (`looks_safe`, low score) | OTP | Metrobank: Your OTP is 118204. Valid for 10 minutes. Never share this code with anyone. | `ph_supplement_3.csv` row 2 (`otp`, ham) |
| SA-BANK | Looks safe (`looks_safe`, low score) | Bank/e-wallet alert | GCash: You received ₱1,500 from ANA LIM. Balance: ₱6,200.00. | `ph_holdout.csv` row 11 (`bank_alert`, ham) |
| SA-DEL | Looks safe (`looks_safe`, low score) | Delivery notice | J&T Express: Parcel JT5522878 out for delivery. Track at jtexpress.ph/track | `ph_holdout.csv` row 12 (`delivery`, ham) |
| SA-TL | Looks safe (`looks_safe`, low score) | Personal Taglish | Ingat ka sa byahe mamaya. Text mo ako pagdating mo. | `ph_supplement.csv` row 101 (ham) |

## Opening script (read or paraphrase)

> Thank you for helping. I am testing whether the warnings and wording in a
> local SMS spam-detection tool make sense to people, not whether the tool is
> accurate. Everything I show you today is a made-up example message; none of
> them are real messages from a real phone.
>
> Please use the tool as you normally would. We are evaluating the interface,
> not testing you. What you tell me will not affect anything you use.
> We will explain what the model score means after recording your answers.
>
> I will show you one made-up message at a time and ask what you think. I may
> take notes; I will record only your pseudonym and your answers about the
> examples, never anything about you.

## Before showing any score details

Ask these first, before the verdict, score, or pattern details are visible:

- "What do you think the score means?"
- **Guarantee probe (ask verbatim): "Does a low score guarantee the message is safe?"**
- "Where would you verify an unexpected bank or delivery request?"
- "What would you do if a message asked you for an OTP?"

Record the answers without supplying definitions or pointing to the warning.
Repeat the guarantee probe after the participant has used the interface; keep
the before and after responses separate. If a participant treats a low score
as a promise of safety, record it as a comprehension failure for this session
under the unchanged decision rule below.

## Per-example flow

For each example, in the participant's randomized order:

1. Show the message text only (no verdict, score, or details). Ask:
   - **Probe 1: "What do you think this message is?"** — record this first
     label before anything else is shown or said.
2. Then show the UI verdict: band, score, uncertainty wording, and the
   recommended action. Ask:
   - **Probe 2: "What part of the UI influenced you?"**
   - "Was the wording clear or too certain?"
3. Ask:
   - **Probe 3: "What would you do next?"** — listen for verification through
     an independently obtained official channel and for refusal to share OTPs
     or PINs.
4. Ask whether the safety guidance is actionable, and write down any wording
   that could be mistaken for an instruction to block, report, or punish a
   sender for owner review.

Do not confirm or correct the participant's answers at any point.

## Keyboard and status checks

- Ask the participant to find the text-pattern details using the keyboard
  only, and record whether they could.
- Ask whether the visible service status and retry control are clear.
- Record screen-reader issues separately; this session does not replace
  dedicated screen-reader testing.

## Recording sheet (per example)

| Field | Allowed values |
|---|---|
| Example ID | Fixture ID from the table above |
| Participant pseudonym | Participant-chosen pseudonym; no names |
| Expected label | Participant's first label, before explanations |
| Confidence | `low` / `medium` / `high` |
| Category | e.g. `otp`, `bank_alert`, `delivery`, `personal_taglish`, scam category |
| Usability issue | Short description of anything confusing |
| Notes | No personal details |

## Pass criterion

**Pass criterion: no participant reads a low score as a guarantee.** If any
participant does — in the guarantee probe or anywhere else — the session does
not pass. A material misunderstanding means the wording or layout must be
reviewed and revised before any release decision, per HUMAN_REVIEW
"Comprehension questions and decision rule". The owner and privacy reviewer
still set any remaining decision-rule details before the session.

## After the session

- Report participant count, message counts by class/category/language, missing
  responses, and how many examples were synthetic (all of them, in this
  session) versus consented real data (none).
- Summarize confusion on the terms "likely scam", "suspicious", probability,
  and the recommended action. Track OTP and legitimate-alert false-positive
  reports separately.
- Update copy or UI only when supported by review notes; re-run accessibility
  checks and the relevant automated UI/API checks after changing the
  interface.
- Remember: this feedback is qualitative usability evidence, not a model
  performance estimate, and it cannot establish population-wide usability.


## Filipino / Taglish facilitator prompts (draft for native-speaker review)

Use the same neutral meaning and order as the English questions. Do not mix
explanations into the first-response questions. These translations are
participant-facing draft material, not a translation of the approved privacy
notice; obtain the native-language and qualified reviewer check before use.

| English probe | Filipino / Taglish draft |
|---|---|
| What do you think this message is? | Sa tingin mo, anong uri ng mensahe ito? |
| What do you think the score means? | Sa tingin mo, ano ang ibig sabihin ng score? |
| Does a low score guarantee the message is safe? | Kapag mababa ang score, sigurado bang ligtas ang mensahe? |
| What part of the interface influenced you? | Aling bahagi ng screen ang nakaimpluwensiya sa sagot mo? |
| What would you do next? | Ano ang susunod mong gagawin? |
| Where would you verify an unexpected bank or delivery request? | Saan mo ibe-verify ang hindi inaasahang mensahe mula sa bangko o delivery service? |
| What would you do if a message asked you for an OTP? | Ano ang gagawin mo kung humingi ng OTP ang mensahe? |

After recording all responses, explain that the score is an assistive spam
model score, not proof of fraud or safety. Remind participants that they
should verify unexpected requests through official channels obtained
independently. Do not include this explanation before the measured probes.
For the optional donation walkthrough, use only fictional text and ask
participants to explain the distinct review, sharing-authorization, and
optional research choices in their own words. Do not record real messages.

### Pending donation and interrupted-response walkthrough (fictional only)

Use the disposable service and generated text, never participant messages. Ask the participant to explain why the form cannot be edited while a submission is in progress, what an uncertain receipt means, and what they would do if a later attempt is rejected. Filipino draft: “Ano ang gagawin mo kung hindi tiyak kung natanggap ang unang ipinadalang form?” Do not give the expected answer first. Record keyboard access after the pending operation, announcement of the status, and whether the user understands that a later rejection does not establish the earlier outcome. Native-speaker and actual screen-reader evaluation remain outstanding.
