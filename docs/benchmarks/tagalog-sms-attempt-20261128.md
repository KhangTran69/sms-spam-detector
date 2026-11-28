# Tagalog-SMS download attempt — 2026-11-28

Message-free attempt record: no SMS content, sender metadata, or other corpus
text is quoted here. The blocked attempt produced no rows, no CSV, and no
hashes to report; the corpus was not fetched, normalized, or evaluated.

## What was attempted

On 2026-11-28 at 07:33:44 UTC, this workspace attempted to fetch the
Tagalog-SMS corpus (Kaggle `onzero0/tagalog-sms`; Kaggle metadata reports
CC0: Public Domain) with the repository's approved downloader:

```
make datasets DATASET=tagalog-sms
```

Run from the repository root of the `chore/roadmap-t0-hygiene` worktree
(`the repository root of the `chore/roadmap-t0-hygiene` worktree`) with no
`KAGGLE_USERNAME`/`KAGGLE_KEY` exported in the environment.

## Result: blocked before any network access

- **Exit status:** 2.
- **Exact error:** `download_datasets.py: error: Kaggle credentials are required; set KAGGLE_USERNAME and KAGGLE_KEY in the environment.`
- **Failure class:** deterministic credential gate in
  `scripts/download_datasets.py`. The CLI verifies Kaggle credentials before
  attempting any download, so the refusal is reproducible, not a transient
  network failure. No bytes were fetched, and no raw CSV, normalized CSV,
  metadata sidecar, or normalization report was created under ignored
  `data/external/`.
- **Rows fetched:** 0. **Rows normalized:** 0. **SHA-256 recorded:** none —
  nothing was downloaded, so there is no artifact to hash.

## Credential requirement

Fetching this corpus requires the operator's own Kaggle API credentials
(`KAGGLE_USERNAME` and `KAGGLE_KEY` exported in the environment). The
downloader refuses to proceed without them rather than trying to obtain the
dataset some other way. Credentials themselves are never written to Git,
reports, or sidecars; a successful local fetch records only the UTC retrieval
time, source URL, declared license, and CSV SHA-256 in the message-free
`tagalog-sms-raw.csv.metadata.json` sidecar.

## Unblock paths

1. **Operator exports credentials.** The operator exports `KAGGLE_USERNAME`
   and `KAGGLE_KEY`, then re-runs `make datasets DATASET=tagalog-sms`. The
   raw and normalized CSVs stay in ignored `data/external/`, the normalized
   row counts and CSV SHA-256 are recorded message-free, and any evaluation
   runs through `make eval DATA=... MODEL=...` with its report written to an
   ignored output path — never Git.
2. **Credential-free re-host after license verification.** The corpus is
   re-hosted from a source that does not require Kaggle authentication, and
   only after a license/provenance review confirms the CC0 declaration and
   the re-host's own terms. The downloader's non-Kaggle path (the one
   `ph-spam-marketing-sms` already uses) would then be pointed at the
   verified URL.

## Standing caveats (unchanged by this attempt)

Even once unblocked, this corpus remains one publisher's personal inbox, not
consented participant data and not representative Philippine SMS traffic.
Normalization intentionally discards the sender field, but the raw download
must still be treated as sensitive local data, and a successful fetch would
not by itself establish any real-world accuracy claim. See
[data/external/README.md](../../data/external/README.md) and the Tagalog-SMS
row in [DATASET_INVENTORY.md](../DATASET_INVENTORY.md).
