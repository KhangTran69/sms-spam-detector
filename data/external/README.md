# External datasets (local only)

Dataset files and downloaded SMS content in this directory are ignored by Git.
Do not add them to commits, CI artifacts, reports, screenshots, or issue text.

## PH Spam + Marketing SMS (w/ timestamps)

- **Source:** [Kaggle dataset page](https://www.kaggle.com/datasets/scottleechua/ph-spam-marketing-sms-w-timestamps); download uses the publisher's [raw GitHub CSV](https://raw.githubusercontent.com/scottleechua/data/main/spam-and-marketing-sms/text-messages.csv) and [dataset README](https://github.com/scottleechua/data/tree/main/spam-and-marketing-sms).
- **License/terms:** Creative Commons Attribution 4.0 International (CC BY 4.0), as stated by the dataset publisher. Attribute Scott Lee Chua and link the license; identify modifications. The dataset license does not settle privacy or other rights concerns.
- **Retrieval date:** Fetched locally on 1 November 2026 at `2026-11-01T00:41:10.218013Z`. The raw-file SHA-256 is in the ignored `ph-spam-marketing-sms-raw.csv.metadata.json` sidecar.
- **Rows:** The retrieved raw file contains 8,895 data rows, matching the publisher README's 20 August 2026 snapshot count. Normalization loaded 1,664 unique labeled rows; 6,887 blank/redacted rows and 344 duplicates were excluded. Upstream content may change.
- **Supplied-file check:** The uncompressed CSV in the supplied archive and the standalone CSV have matching SHA-256 digests; they are one copy of this snapshot and must be counted once.
- **Caveats:** One person's inbox, not a representative Philippine sample. The source includes sender metadata and partially masked numbers; the normalized file drops the sender column. Categories are `spam`, `ads`, `gov`, `notifs`, and `OTP`; `ads` maps to this project's `spam` class, while `gov`, `notifs`, and `OTP` map to `ham`. Empty and fully redacted records are excluded and counted. Some categories are redacted by the publisher; campaign/language coverage is limited. Use results as diagnostics for this corpus, not as evidence of population-level accuracy.
- **Attribution:** Scott Lee Chua, *PH Spam + Marketing SMS (w/ timestamps)*, CC BY 4.0. Note any normalization or filtering in derived reports.

Download the publisher's current raw CSV with `make datasets`; this PH source does not require Kaggle credentials. The raw file and metadata are created with owner-only permissions under ignored `data/external/`.

## Tagalog-SMS

- **Source:** [Kaggle dataset](https://www.kaggle.com/datasets/onzero0/tagalog-sms), published by ZERO (`onzero0`).
- **License/terms:** Kaggle dataset metadata reports `CC0: Public Domain` (checked 1 November 2026). This label does not settle third-party privacy or data-protection rights in personal messages or sender metadata.
- **Retrieval date:** Not downloaded in this repository checkout. A local fetch writes the UTC retrieval time and CSV SHA-256 to `tagalog-sms-raw.csv.metadata.json`.
- **Rows:** The exact fetched and normalized counts are written to the local metadata and aggregate report sidecars; no messages are included in those files.
- **Caveats:** The publisher describes a personal inbox with date, sender, text, and category fields. Raw sender information may identify a person or service. The normalized importer intentionally discards the sender field and retains only message text, category, and date. It maps `spam` and `ads` to `spam`, and `gov`, `notifs`, and `otp` to `ham`; unknown labels, blank/redacted messages, and duplicates are excluded and counted. Treat the raw download as sensitive local data. Public availability and a CC0 label do not constitute consent or remove other privacy obligations. This is one inbox, not representative Philippine traffic.
- **Attribution:** ZERO (`onzero0`), *Tagalog-SMS*, Kaggle. The downloader records the source URL and declared license in its message-free metadata.

Download and normalize this corpus with `make datasets DATASET=tagalog-sms`. Its results must be evaluated separately from every other dataset.

## `DATA103_filipino_spam_detection` on Hugging Face — blocked

License/source review checked on 1 November 2026; recheck publisher terms before
any retrieval. The Space exposes a merged file at
`src/cleaned_sms_text_labels_only_v2.csv`.

The [Space README](https://huggingface.co/spaces/ferds003/DATA103_filipino_spam_detection/blob/main/README.md)
declares `license: mit` for the Space and says its merged message set combines
three upstream corpora. Its [data-curation code](https://huggingface.co/spaces/ferds003/DATA103_filipino_spam_detection/blob/main/app.py)
identifies these sources:

| Upstream source | Published terms found | Status for the merged export |
|---|---|---|
| [PH Spam + Marketing SMS (w/ timestamps)](https://www.kaggle.com/datasets/scottleechua/ph-spam-marketing-sms-w-timestamps) | CC BY 4.0, per publisher documentation | Terms identified; the corpus remains a one-person inbox with separate privacy considerations. |
| [Philippine Spam/Scam SMS](https://www.kaggle.com/datasets/bwandowando/philippine-spam-sms-messages) | CC BY-NC-SA 4.0, per Kaggle dataset metadata | Non-commercial/share-alike restrictions apply to this source; compatibility and downstream obligations have not been reviewed for this project. |
| [Filipino-Spam-SMS-Detection-Model](https://github.com/Yissuh/Filipino-Spam-SMS-Detection-Model) | BSD 3-Clause license in the source repository | Repository terms are visible, but the Space's repackaged message rows' provenance, authorization, and relationship to those terms need confirmation. |

The Space-level MIT tag does not establish that all merged message contents
were relicensed under MIT. Keep this corpus **blocked**: its components have
different terms, the reuse/share-alike implications have not been reviewed,
and public availability does not establish donor consent or resolve rights in
the messages. Do not download, normalize, evaluate, or redistribute the merged
SMS files until the dataset owner documents source-level permissions, consent
or another suitable basis, and compatible downstream terms. No Hugging Face
message files are included in CI or this repository.

## Other submitted resources — not ingested

Reviewed on 1 November 2026. These resources are useful for provenance review
or follow-up, but are not approved additions to the download/evaluation path:

| Resource | Review result |
|---|---|
| [Philippine Spam/Scam SMS by BwandoWando](https://www.kaggle.com/datasets/bwandowando/philippine-spam-sms-messages) | Kaggle metadata identifies CC BY-NC-SA 4.0. The non-commercial/share-alike conditions have not been approved for this project's dataset workflow, so it is not downloaded or transformed here. |
| [Filipino Gossip Dataset](https://huggingface.co/datasets/jhenberthf/filipino-gossip-dataset) | The Hugging Face card reports MIT and describes a 263-row text-generation dialogue dataset with gossip categories, not labeled SMS spam/ham examples. It is out of scope for detector evaluation. |
| [Filipino-ScamSMS-Detector](https://github.com/RJCed/Filipino-ScamSMS-Detector) | Its README calls the project experimental and paused, says its data needs cleaning/validation, and lists the Tagalog-SMS, BwandoWando, and gossip sources above. The repository root has no license file. Its CSVs are not independent evidence and are not imported. |
| [SMS Scam Detection in English Filipino Texts](https://github.com/Notanne1305/SMS-Scam-Detection-in-English-Filipino-Texts) | The repository contains data/results/source directories but no root license file. Its right to redistribute and the provenance of included/combined SMS files are therefore unclear. Do not fetch or reuse its data until licensing and source permissions are documented. |

Recheck these sources before any later use. Do not infer a dataset license from
a repository's public visibility or from a license attached to a different
upstream source.
