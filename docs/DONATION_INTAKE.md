# Optional local message donations

Donation intake is a separate, optional local workflow. Prediction and analysis
continue to process messages in memory; donation storage stays **disabled by
default**. This page describes the implementation, not a legal determination
that any particular collection is lawful.

## Enable only for a reviewed local service

Before enabling collection, the project owner must complete and sign the
pre-collection go/no-go record in [`DATA_COLLECTION.md`](DATA_COLLECTION.md)
after qualified privacy/legal review. Resolve controller/contact, lawful
basis, access, retention, withdrawal, backup deletion, and incident handling;
appoint a data steward, two independent labelers, and a separate sealed-test
custodian. An unresolved item keeps collection off. The form is disabled unless both
`SMSD_DONATIONS_ENABLED=1` and `SMSD_DONATIONS_OPERATOR_CONTACT` are set. The
contact is shown on both the form and notice. The optional settings are:

| Setting | Default | Purpose |
|---|---|---|
| `SMSD_DONATIONS_ENABLED` | off | Explicitly enables the page and API routes |
| `SMSD_DONATIONS_OPERATOR_CONTACT` | empty | Required contact displayed to donors; without it collection stays off |
| `SMSD_DONATIONS_PATH` | `data/donations/donations.sqlite3` | Local SQLite file path |
| `SMSD_DONATION_RATE_LIMIT_PER_MINUTE` | `5` | In-process per-client donation request limit |

The app has no authentication. CORS does not provide access control. Donation
routes accept only loopback clients, and the intake is unavailable when
`SMSD_ENV=production`. Keep it on localhost without a public reverse proxy;
do not expose or deploy the intake publicly. Run the service with
`python -m api.cli` / `smsd-serve`. Withdrawal IDs are sent in a JSON body,
not a URL path; the CLI disables Uvicorn access logs for a single sanitized
log stream.

## Consent and processing sequence

The form uses version [`privacy-notice.md`](privacy-notice.md),
`2026-11-01-v4`. It requires two separate affirmative choices: consent to local
human review/labeling, and confirmation that the submitter is authorized to
share the message. The form says to submit only messages sent directly to the
donor or written by them. Do not solicit another person's private conversation,
live codes, credentials, or complete sender details. A third, **optional and
unchecked** choice separately allows the message to be considered for future
model research, including training or evaluation. The server records each
choice, the notice version, and its own UTC consent timestamp. A request without
review consent or sharing authorization is rejected. A message with review-only
consent cannot be used for model research. Earlier notice versions remain as
recorded; they are never silently relabeled as version 4.

Message text is length-bounded and screened with the strict PII scanner before
SQLite storage. The storage layer repeats that check, and review export screens
again. If likely PII appears, the API rejects the submission and returns only
the flagged spans needed for manual redaction. URLs are flagged; the scanner can
miss information, so donors must review and redact messages themselves.

The form collects only message text, an optional `spam`/`ham` hint, an optional
language code, consent choices/version/time, and a random withdrawal ID. It does
not request names, phone numbers, email addresses, account numbers, contact
lists, or sender identifiers. Donor hints are never shown in the reviewer
export and are not ground truth. Submissions are held for local review and are
not automatically used in training, evaluation, analytics, or model updates.
Never submit a live OTP, password, credential, someone else's private
conversation, or full sender details.

The response shows a withdrawal ID in the page only. The page does not put it or
the SMS in localStorage, sessionStorage, caches, or analytics. Copy or note the
ID somewhere private if you may withdraw later; after reopening the page, paste
it into the withdrawal form. Losing the ID means the service cannot recover it.
Withdrawal erases the stored message, label hint, and language, vacuums the
database, then keeps only a content-free tombstone until its 90-day expiry. The
app purges expired rows on the next donation database access. Active records
expire 90 days from consent. The operator must delete backups on the same
schedule. The database is not encrypted by the application; keep it on an
encrypted, access-controlled device and outside cloud-synced folders. The v1 to
v2 database migration marks previous rows as lacking the new sharing and model
research choices; those legacy rows are excluded from reviewer export.

## Export for independent review

The operator may export a new CSV outside the repository or into ignored
`data/donations/` storage:

```bash
make export-donations OUTPUT=/secure/local/review-staging.csv
# Or choose the database explicitly:
make export-donations DATABASE=/secure/local/donations.sqlite3 OUTPUT=/secure/local/review-staging.csv
```

The command prints aggregate counts only, refuses to overwrite, and refuses a
destination inside tracked repository paths. It omits withdrawn, expired,
unauthorized, and newly PII-flagged rows. File and directory permissions are
restricted where the filesystem supports POSIX modes. The CSV is a **review
staging export**, not a model dataset: `label` is blank, `review_status` is
`pending_review`, no donor label hint or model prediction is included, and
`eligible_for_modeling=false`. It cannot be loaded as training/evaluation
ground truth. Reviewers work independently without model outputs or donor
hints. Only a separate consent-register-verified, independently adjudicated,
campaign/time-separated batch may pass [`DATA_COLLECTION.md`](DATA_COLLECTION.md)
and enter research use. Keep exports/backups private and outside Git and public
CI.

Campaign grouping uses message/campaign evidence rather than sender IDs to
reduce leakage. It cannot prove contributor-level independence. The repository
sets no real-study sample-size target; coverage and uncertainty criteria must be
justified and registered before the sealed test is opened.

## Philippine Data Privacy Act considerations

The Data Privacy Act of 2012 (Republic Act No. 10173), its Implementing Rules
and Regulations, and National Privacy Commission issuances may apply to
processing message content and identifiers. The operator must assess the role
of personal information controller/processor, the purpose, the appropriate
lawful basis, transparency, proportionality, safeguards, retention, data
subject requests, and any applicable registration or breach duties. This code
does not establish legal compliance; obtain qualified privacy/legal review for
the deployment and actual dataset.

**Public availability is not consent.** The NPC's 2026 Advisory No. 2026-01
states that publicly available personal data do not become consent for
processing beyond purposes reasonably contemplated, and that scraping must
still satisfy DPA obligations and a suitable lawful basis. **Scraping public
pages is not automatically exempt** from the DPA. A license answers a separate
copyright/contract question; it does not by itself answer privacy or data
protection requirements. Review each dataset's terms and collection context
before downloading, processing, or redistributing it. In this repository the
Kaggle corpus is documented as CC BY 4.0, but it is one person's inbox and has
not yet been fetched or evaluated. The merged
`DATA103_filipino_spam_detection` corpus remains **blocked**: its Space-level
MIT tag coexists with upstream CC BY 4.0, CC BY-NC-SA 4.0, and BSD 3-Clause
sources. The merged message rows' provenance, authorization, and compatible
downstream terms are unresolved. See
[`data/external/README.md`](../data/external/README.md) and
[`evaluation.md`](evaluation.md).

Primary references: [Republic Act No. 10173 (Official Gazette)](https://officialgazette.gov.ph/2012/15/republic-act-no-10173),
[Data Privacy Act Implementing Rules and Regulations (NPC)](https://privacy.gov.ph/implementing-rules%20regulations-data-privacy-act-2012/),
[NPC Circular No. 2023-04, Guidelines on Consent](https://privacy.gov.ph/wp-content/uploads/2023/11/NPC-Circular-No.-2023-04_Guidelines-on-Consent_07Nov2023.pdf),
[NPC data-subject rights](https://privacy.gov.ph/data-subject-rights/),
and [NPC Advisory No. 2026-01 on scraping publicly available personal data](https://privacy.gov.ph/wp-content/uploads/2026/04/SGD_A_1.pdf). RA 10173 §11 addresses purpose limitation and retention, §12 sets lawful-processing criteria including consent, and §16 describes data-subject rights; the IRR elaborates transparency, legitimate purpose, proportionality, and revocable/time-bounded consent. The operator must assess how these rules apply; the software does not make that legal determination.
