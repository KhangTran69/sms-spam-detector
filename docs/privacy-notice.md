# Philippine SMS Spam Detector donation privacy notice

**Notice version:** `2026-11-01-v4`
**Effective:** 1 November 2026

**Local service operator/contact:** shown on the donation page. Do not submit a
donation if the operator is not identifiable or cannot be contacted.

Donating is optional. The detector works without a donation. The form is for a
local service operated on the same computer; it is not a public research
service. Collection is off unless the local operator enables it. The form
accepts requests only from the same computer and is unavailable in production
mode.

## Your separate choices

To submit, you must separately confirm that you are authorized to share the
message and consent to local storage for human review and labeling. Submit only
a message sent directly to you or one you wrote. Do not submit someone else's
private conversation, a live OTP, password, PIN, account credential, or full
sender details.

You may separately opt in to having the message considered for future model
research, including training or evaluation. This choice is
optional. Without it, the message is restricted to local review and will not be
considered for model research. Even with the opt-in, a message is not used
automatically: the operator must separately verify the consent record, screen
the message, obtain two independent reviews, resolve disagreements, and approve
a campaign/time-separated dataset. A donor-provided label is only a hint.

## What the local service stores

After you submit, the service stores the message, optional label hint and
language, this notice version, the server-recorded UTC consent time, your
authorization and consent choices, and a random withdrawal ID in a local
SQLite database. The form does not ask for names, phone numbers, email
addresses, account numbers, contact lists, or sender identifiers. A
conservative scanner checks for likely personal details, URLs, and codes before
storage and again before review export. It can miss information; inspect and
redact the message yourself before submitting.

The database is stored only on the operator's computer with restrictive file
permissions. The operator must keep the computer encrypted, restrict account
access, protect backups, and keep this local service bound to localhost without
a public reverse proxy. This application does not encrypt the database itself.

The service retains an active message for **90 days** from consent, then
purges it the next time the database is accessed. The operator must delete
backups on the same schedule. Message text is not written to application logs,
browser storage, analytics, or public reports.

## Withdrawal and limits

After a successful submission, the page shows a random withdrawal ID and an
immediate erase action. The browser does not save the ID. Keep it somewhere
private if you may need to withdraw later. Withdrawal erases the message,
label hint, and language; only a content-free tombstone with the consent notice
version, timestamps, and withdrawal status remains until its expiry. Contact
the local operator about copies in backups or any downstream dataset. If
consented data has already been used in a separately approved model or report,
the operator must assess deletion of derived copies and explain any limits.

The privacy screen is a best-effort aid, not proof that text is anonymous or
safe to share. The operator must independently review consent, privacy, labels,
and campaign/date separation before any research use. This notice and software
do not establish legal compliance; the operator must obtain appropriate
privacy and legal review for the actual deployment.

The detector provides assistive spam-versus-ham signals, not a finding of fraud
or a safety guarantee. Verify suspicious requests through trusted official
channels.
