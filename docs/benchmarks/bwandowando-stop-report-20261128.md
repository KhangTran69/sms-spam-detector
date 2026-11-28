# bwandowando corpus — STOP: personal data beyond SMS text — 2026-11-28

Message-free record: no SMS content, sender number, hash, or timestamp value
from this archive is quoted anywhere in this report.

## What was attempted

The gap-closure brief directed: fetch + normalize + diagnose the
`bwandowando/philippine-spam-sms-messages` Kaggle corpus (CC BY-NC-SA 4.0,
verified via the Kaggle API), integrate it into the approved downloader, and
run a message-free diagnostic — **unless the archive contains real personal
data beyond SMS text, in which case STOP and report instead of normalizing.**

License verification (Kaggle API, 2026-11-28):

- Dataset: `bwandowando/philippine-spam-sms-messages` ("Philippine Spam/Scam
  SMS — spam and scam messages I personally received").
- License declared by the publisher: **CC BY-NC-SA 4.0** — non-commercial use
  with attribution and share-alike; diagnostic use was pre-cleared by the
  owner ruling "Kaggle is only public data" (2026-11-28), with the corpus to
  stay local-only and never redistributed.
- Archive size 88 KB zipped / 234 KB uncompressed; last publisher update
  2026-11-02.

## What the archive contains (structure only)

One CSV, 1,023 rows, 5 columns:

| Column | Content class |
|---|---|
| `masked_celphone_number` | sender identifier, partially masked — a real PH mobile prefix and suffix with the middle digits starred out |
| `hashed_cellphone_number` | a hash of the sender's phone number |
| `date` | per-message receive timestamp |
| `text` | the SMS body |
| `carrier` | sender brand / short-code label (e.g. bank and telco brand names) |

No ham/spam label column exists; per the dataset description every row is a
message the publisher received as spam or scam, so the corpus could only ever
have served as a one-sided (spam-recall) probe.

## Why the stop rule fires

The brief's condition — "real personal data beyond SMS text" — is met:

1. **Partially-masked real phone numbers.** Each row carries a sender mobile
   number with 4 middle digits masked but the leading and trailing digits
   real. Masking 4 digits of a 10-digit PH mobile space leaves a small
   candidate set per prefix; this is de-identification by hiding, not
   anonymization.
2. **Phone-number hashes.** A 10-digit phone space is trivially enumerable;
   a per-number hash can be inverted by dictionary construction. A hash of an
   identifier is pseudonymous personal data, not anonymous data.
3. **Inconsistent masking.** At least one sender identifier in the archive
   appears entirely unmasked. The publisher's masking is not uniform, so
   "the masked column protects senders" cannot be assumed row-by-row.
4. **Per-message timestamps.** A receive-time activity pattern for the
   publisher's own number; metadata beyond SMS text.

The corpus is the publisher's personal inbox. The SMS text itself is the
sanctioned payload of any SMS corpus; the sender identifiers, hashes, and
timestamps are the personal data beyond it, and they are present.

## What was done instead

- The archive was downloaded once to git-ignored `data/external/` for
  structural inspection only. **It stays local-only, is not redistributed,
  and was never normalized, evaluated, hashed into any sidecar, or quoted.**
- **No downloader integration was made**: adding `DATASET_OPTIONS` plumbing
  for a corpus the project has decided not to process would only create a
  fetch path with no permitted use. No changes to
  `scripts/download_datasets.py` or `src/public_datasets.py`.
- **No diagnostic was run** and **no cross-corpus transfer check was run**
  (Tagalog-SMS-trained model vs. this corpus): both require normalization,
  which the stop rule forbids.
- The downloaded inspection copy can be deleted by the owner at any time; the
  structural facts above are all this record needs.

## What would unblock this corpus

1. **Publisher-side**: a text-only variant (columns: text + label or an
   explicit statement that senders/timestamps are synthetic), or removal of
   the sender-identifier and timestamp columns.
2. **Owner ruling**: a decision that publisher-masked + hashed sender
   metadata falls outside the stop rule, with the normalizer dropping sender
   columns exactly as the tagalog-sms path does. That is an owner decision,
   not an agent ruling — this record deliberately does not make it.

## Precedent note, stated plainly for that future ruling

The Tagalog-SMS corpus (processed 2026-11-28 under a ratified owner ruling)
carries the same metadata class — sender field and timestamps — and its
normalizer drops the sender field. This corpus's sender metadata is *better*
protected by the publisher (masking + hashing) than that precedent's, except
for the inconsistent-masking defect above. The stop here rests on the brief's
explicit per-corpus stop clause, not on a claim that this corpus is worse
than the accepted one; an owner ruling can reverse it the same way the
Tagalog-SMS processing was ratified.

Until one of those happens, this corpus stays blocked, and the cross-corpus
transfer question (does real-data training benefit transfer to a second
independent Philippine corpus?) remains answered only for the PH-inbox
corpus: partially (precision holds, recall does not — see
[v2-1-0-gates-not-met-20261128.md](v2-1-0-gates-not-met-20261128.md)).
