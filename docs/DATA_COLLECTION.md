# Data Collection and Labeling

This document defines how SMS data may enter the project. It applies to the
synthetic files currently in `data/raw/` and, more importantly, to any real
Philippine messages added later.

> **Status:** the repository currently contains the public UCI SMS Spam
> Collection (English) plus **synthetic** Philippine template files. No representative
> real Philippine traffic has been collected or evaluated. The
> synthetic files exist to test the pipeline, not to estimate real-world
> performance. See [MODEL_CARD.md](MODEL_CARD.md).

## 1. Principles

1. **Consent and lawful basis first.** Do not collect a message without a clear
   basis: informed consent from the person who received/sent it, or a documented
   legal basis approved by whoever owns the deployment. Consent must be
   specific (SMS research / model improvement), recorded, and revocable.
2. **Data minimization.** Collect only the fields needed. Never ask donors for
   bank details, OTPs, full account numbers, or identity documents.
3. **No live OTPs or active codes.** A message containing a still-valid one-time
   code must not be collected or stored; wait until it has expired or mask it.
4. **Separate synthetic from real.** Synthetic templates and real messages use
   different files, metadata (`source`), and evaluation reporting. Never mix
   them silently.
5. **Real data stays local.** Real message text never goes to Git, never goes
   into notebooks that are committed, and never into issue trackers or chat.

## 2. Consent workflow

For any non-synthetic donation:

1. Explain purpose (training/benchmarking an assistive spam classifier), what is
   stored, who can access it, retention period, and how to withdraw.
2. Record consent in a separate consent log (not in the message CSV): donor
   pseudonym, date, scope, channel, version of the consent text, withdrawal
   status. Keep the consent log out of Git.
3. Assign a donor/group pseudonym so messages can be removed on request.
4. On withdrawal, delete the donor's rows (or re-run the masking job) and
   regenerate any derived artifacts; record the deletion in the audit log.

Do not rely on "publicly posted" as consent for re-publishing someone's private
messages. Do not scrape private groups or inboxes.

## 3. De-identification and masking

Before a message is written to any dataset file, replace personal data. Prefer
replacement tokens over deletion so text patterns stay intact:

| Data | Replacement |
|---|---|
| Names, usernames, email addresses | `PERSONTOKEN` / `EMAILTOKEN` |
| Mobile / landline numbers | `PHONETOKEN` (keep a masked last-2 marker only if needed for grouping, e.g. `PHONETOKEN_89`) |
| URLs / short links | `URLTOKEN` (keep the scheme only if it matters) |
| Exact amounts tied to a person | `MONEYTOKEN` when the amount could identify a transaction |
| Account / card / reference numbers | `ACCOUNTTOKEN` |
| Addresses, landmarks, barangay + house details | `ADDRESSTOKEN` |
| OTP / verification codes | `CODETOKEN` (never keep the live code) |
| Device identifiers, IMEI, IP | `DEVICETOKEN` |
| Dates of birth, government IDs | remove or `IDTOKEN` |

Rules:

- Mask `message` **before** it is stored, not at training time.
- Run a second automated pass (regex for PH phone numbers, emails, URLs, long
  digit runs) and a manual spot-check of every newly added batch.
- Keep the reversible mapping (if any) encrypted and outside the dataset repo;
  normally there is no need for one.
- Screenshots/source exports are raw personal data: store them in the same
  protected location as the unmasked text and delete them after masking.

## 4. Labeling protocol

Label each message as `spam` (scam/spam/unsolicited) or `ham`
(legitimate/transactional/personal), then record how sure the labeler was.

**Labeling checklist**

1. Read the full message, including sender ID if available (sender IDs are not
   stored; capture a generic category such as "bank sender ID" in `notes`).
2. Decide `spam` when the message is unsolicited and/or attempts to defraud:
   prizes, impersonation, credential/OTP phishing, fake fees, job/investment
   lures, threat/urgency to act. Decide `ham` for legitimate OTPs, transaction
   alerts, delivery notices, bills, appointment reminders, and personal texts.
3. Watch the hard cases: legitimate bank alerts often contain a link, an amount,
   urgency word ("expires", "now"), and a brand name. A link/amount/phone alone
   is **not** spam. If it is plausibly legitimate but suspicious, label `ham`
   with low confidence rather than inflating the spam class.
4. Avoid inferring intent from who the sender is alone; use content.
5. Two-person labeling for any new batch: independent first pass, then resolve
   disagreements by discussion; record the resolution.

**Confidence scale** (stored in `labeling_confidence`, 0.0–1.0):

| Value | Meaning |
|---|---|
| `0.95`–`1.00` | Obvious; both labelers agree without discussion |
| `0.80`–`0.94` | Clear pattern; minor ambiguity (sender, context) |
| `0.60`–`0.79` | Plausible but uncertain; keep for error analysis, down-weight if it conflicts |
| `< 0.60` | Do not use for training/evaluation; move to a review queue |

Also record `labeler` (pseudonym), `labeled_at` (ISO date), and `labeling_notes`
for ambiguous cases. Do not silently fix labels after the fact; append a new
label record/version and note why.

The current training loader reads `labeling_confidence` as metadata for analysis
but does **not** weight examples by it. Keep low-confidence rows out of training
(§4) rather than assuming the model will discount them. `labeler`, `labeled_at`,
and `labeling_notes` remain in the CSV for provenance/audit; the loader does not
use them for training.

## 5. CSV schema

Required columns:

| Column | Type | Rules |
|---|---|---|
| `label` | string | `spam` or `ham` (loader also accepts `legit`, `scam` and Kaggle `v1`; prefer canonical values). |
| `message` | string | Masked text, UTF-8, non-empty, no leading/trailing junk. |

Optional columns (recommended for real data; ignored by the trainer except for
grouping/analysis):

| Column | Type | Purpose |
|---|---|---|
| `source` | string | Provenance, e.g. `uci`, `synthetic_template`, `donor_2026`, `public_bank_alert_example`. |
| `category` | string | Semantic group, e.g. `prize_scam`, `bank_impersonation`, `otp_legit`, `delivery`. |
| `language` | string | `en`, `tl`, `taglish`, `mixed`; free text if unsure. |
| `labeling_confidence` | float | `0.0`–`1.0` per the scale above. |
| `labeler` | string | Pseudonym of the labeler. |
| `labeled_at` | string | ISO-8601 date. |
| `group` / `template_family` | string | Campaign/template grouping (see §6); rows in the same group must not straddle splits. |
| `notes` | string | Short, non-PII diagnostic note. |

The loader maps the first recognized alias for each optional field:
`source`/`data_source`, `category`/`message_type`/`type`/`scam_type`,
`language`/`lang`, `labeling_confidence`/`label_confidence`/`confidence`,
`group`/`template_family`/`campaign`/`family`. `labeler`, `labeled_at`, and
`notes` are kept in the file for provenance but are not used by training.

Requirements:

- Same header for supplement files; a file that has only `label,message` is
  valid.
- One message per row; do not put multiple messages in one cell.
- Do not add extra index columns (an unnamed `Unnamed: 0` column is harmless but
  avoid it).
- Encoding UTF-8; `₱`, `ñ`, and other Philippine characters must survive. The
  loader falls back to latin-1 for legacy Kaggle exports, but new files must be
  UTF-8.
- Keep the base corpus (`data/raw/spam.csv`) separate from Philippine files.

The current training loader requires both classes across the full dataset,
rejects blank/duplicate problems with actionable errors, and drops exact
duplicate messages after merging. See `src/train.py` / `src/data.py` and the
README for the current CLI.

## 6. Template families and campaign grouping

Scam messages come in near-identical variants ("template families") and
campaigns. Treat each family/campaign as a **group**:

- Set `group` (or `template_family`) to a stable identifier, e.g.
  `parcel_fee_lbc_2026q3` or `synthetic_prize_gma`.
- All rows from one group go to **one** split (train/validation/holdout). The
  trainer uses grouped splitting so the same template never appears on both
  sides; a holdout that overlaps training template families is flagged in the
  evaluation report, and those scores must be treated as optimistic.
- For synthetic templates, one template family = one synthetic campaign, even if
  wording variants exist. Do not claim independence between variants.
- Real messages from the same donor or same sender campaign should share a
  group so donor/sender style does not leak across splits.

If grouping metadata is missing for real data, add it before training. When
`group` is absent the loader derives a template-family signature from the message
text (folding in `category` when present); that is a safety net, not a substitute
for curated campaign/donor groups. Never evaluate on random splits of the same
family and report the result as generalization to new scams.

## 7. Synthetic vs. real data separation

| | Synthetic (tracked) | Real (never tracked) |
|---|---|---|
| Location | `data/raw/ph_supplement*.csv`, `data/raw/ph_holdout.csv` | a protected local path / private store |
| Git | allowed (template text only, no personal data) | **never** — `data/raw/*` is git-ignored except the whitelisted synthetic CSVs |
| `source` | `synthetic_template` | donor/pseudonym or `real_holdout` |
| Reporting | clearly labeled synthetic; never described as real-world performance | report only aggregate metrics; no message excerpts in public docs |
| Splits | grouped by template family | grouped by donor/campaign; keep a real holdout completely held out |

Do not tune thresholds or prompts on the synthetic holdout and then present the
same file as an unbiased test. Pick the threshold on a validation split, then
report once on the held-out synthetic set and (when it exists) the real holdout.

## 8. Adding a supplement or holdout

1. Pick the destination: `ph_supplement*.csv` (training) or `ph_holdout.csv`
   (evaluation only). They must stay disjoint; tests enforce this.
2. Mask every message first (§3). Add metadata columns (§5).
3. Add both classes: a supplement with only scams teaches the model that any
   link/amount/brand is spam, which is exactly the failure we must avoid. Add
   legitimate OTPs, bank transaction alerts, delivery notices, bills, and
   ordinary Taglish as `ham`.
4. Group the rows by template family; extend an existing family rather than
   creating near-duplicates.
5. Do not copy the three diagnostic examples from the project brief into any
   data file; they are leakage guards and are asserted absent.
6. For a holdout: keep it completely out of training and threshold tuning; record
   `source`, `category`, `language`, and confidence; aim for balance across
   scam categories and legitimate message types.
7. Run the data tests: `python -m pytest tests/test_data.py -q`.
8. Retrain *after* the holdout is frozen; evaluate separately. Never evaluate on
   data used to choose thresholds and report it as held-out.
9. Update this document and the README dataset section with provenance, counts,
   and known sampling bias. Do not publish performance numbers from synthetic
   data without the synthetic-only caveat.

## 9. Storage, access, and retention

- **Raw/unmasked** real messages: encrypted at rest, access limited to named
  maintainers, local only, never in cloud Git/notebook services. Keep a shared
  access log.
- **Masked** datasets: still sensitive; store in the same protected location.
  Do not upload to public hubs.
- **Retention:** keep the minimum needed. A default of 12 months after the last
  training run, or 30 days for messages not accepted into a dataset, is
  reasonable — record the chosen period in the deployment runbook and revisit
  annually.
- **Deletion:** deleting rows from the source file is not enough; regenerated
  model artifacts may retain traces. Record deletions, retrain only if needed,
  and document the residual risk. For data-subject requests see
  [PRIVACY.md](PRIVACY.md).
- **Backups:** encrypted, access-controlled, same retention rules. Do not back
  up to shared/public storage.

## 10. Checklist for a new data batch

- [ ] Consent/legal basis recorded (real data only)
- [ ] Masking pass + manual spot-check done; no live OTPs
- [ ] Required/optional columns correct; UTF-8; one message per row
- [ ] Labeling done with confidence, labeler, date; disagreements resolved
- [ ] Grouped by template family / campaign / donor
- [ ] Supplement vs. holdout destination is correct and disjoint from other files
- [ ] No PII or secrets in the file
- [ ] File classification (synthetic vs. real) recorded in `source` and docs
- [ ] Data tests pass; retrain/evaluate plan agreed
- [ ] Known sampling bias and provenance written down
