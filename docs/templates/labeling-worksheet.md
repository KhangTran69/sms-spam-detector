# Labeling worksheet (donation review export)

Ready-to-run worksheet for the independent SMS labeling protocol in
[HUMAN_REVIEW.md](../HUMAN_REVIEW.md). It carries the spam/ham label outcomes
for a batch exported from donation intake, and its review columns match the
consented intake schema in `src/consented_data.py`. This is a blank template:
**no consented batch exists yet and nothing has been labeled.**

## Header row (copy this into the working sheet)

```
record_id | message | label_hint | language | labeling_confidence | labeler_1_label | labeler_2_label | adjudicated_label | adjudicator
```

## Columns

| Column | Filled by | What goes in it |
|---|---|---|
| `record_id` | Export | The randomized record ID from the donation export. No donor identity anywhere in the sheet. |
| `message` | Export | The de-identified message text exactly as exported (already PII-screened). Do not add sender details or notes here. |
| `label_hint` | Coordinator (from export) | The donor's optional hint (`ham`/`spam`). It is **not ground truth**. Mask or remove this column on the sheets given to labeler 1 and labeler 2: HUMAN_REVIEW requires reviewers to work without the donor hint, and the reviewer-facing export omits it. |
| `language` | Export | Short code from the export (`en`, `fil`, `tl-en`, `unknown`). |
| `labeling_confidence` | Coordinator (from export when present) | Optional donor-side labeling confidence as a number between 0.0 and 1.0 (optional column in `src/consented_data.py`). Leave blank when absent. This is not a reviewer confidence. |
| `labeler_1_label` | Labeler 1 | First-pass spam/ham target: `spam` or `ham`. |
| `labeler_2_label` | Labeler 2 | First-pass spam/ham target: `spam` or `ham`, recorded before any discussion. |
| `adjudicated_label` | Adjudicator | Final spam/ham target after adjudication. Later becomes the row's `label` on intake. |
| `adjudicator` | Coordinator | Pseudonymous ID of the adjudicator (for example `reviewer_03`). Required whenever the two first-pass labels disagree; must differ from both reviewer IDs. |

The two reviewers also record scam assessment (`suspected` / `not_suspected`
/ `unclear`), a short category code, and their own `low`/`medium`/`high`
confidence per HUMAN_REVIEW. Those outcomes are kept on the reviewer sheets
and land in the matching intake columns (`reviewer_a_scam_assessment`,
`reviewer_a_label_confidence`, and so on); this worksheet deliberately keeps
only the columns above.

## Worked fictional example

The example message is a tracked synthetic fixture (`ph_holdout.csv` row 138,
`data_kind=synthetic`). It is fictional; it is not a real message. It shows a
disagreement resolved by an independent adjudicator:

```
record_id | message | label_hint | language | labeling_confidence | labeler_1_label | labeler_2_label | adjudicated_label | adjudicator
3b9c1f7e84a2d6505c4e0b1a92fd7364 | Hi po, si Bea ito. Na-send ko sa number mo yung code ko by mistake. Pakibalik yung 6 digits? | ham | tl-en | 0.8 | spam | ham | spam | reviewer_03
```

Labeler 1 read the code request as spam-like OTP theft; labeler 2 read the
message as personal. Labeler 2's sheet would have shown no `label_hint`
column, and the two never saw each other's labels. The adjudicator, who is
neither labeler, resolved to `spam`.

## Adjudication rules

1. Both labelers label the same masked message independently and return their
   sheets before any discussion. Neither sees the other's labels, the donor
   hint, the detector's prediction or score, or model explanations.
2. If `labeler_1_label` and `labeler_2_label` **agree**, `adjudicated_label`
   must equal that shared label.
3. If they **disagree**, a third person who made neither first-pass label
   adjudicates; `adjudicator` is then required and must differ from both
   reviewer IDs, and `adjudicated_label` must resolve to one of the two
   first-pass labels. A disagreement left unresolved keeps the row out of
   imports entirely.
4. **Dated, expiring exception (owner-ratified 2026-11-28):** until a third
   independent reviewer is named, the project owner may serve as the second
   first-pass reviewer alongside one recruited independent reviewer and
   adjudicate disagreements. Rows adjudicated under this exception are
   recorded as owner-adjudicated, and the exception expires when a third
   reviewer is onboarded. Recorded in [HUMAN_REVIEW.md](../HUMAN_REVIEW.md)
   and [DATA_COLLECTION.md](../DATA_COLLECTION.md); pilot labeling starts only
   after the recruited independent reviewer is onboarded (owner decision D2).
5. Reviewers' low/medium/high confidence is recorded with their outcomes.
   Low-confidence rows stay out of model imports, and the intake validator
   rejects an adjudicated final confidence of `low`.
6. Never overwrite review history silently. Only resolved rows are marked
   `review_status=adjudicated`; unresolved, withdrawn, expired consent,
   privacy-flagged, and low-confidence rows are excluded from any dataset.
7. Only messages whose active, versioned consent record covers the planned
   use may be labeled. Verify authorization to share, withdrawal status, and
   retention against the restricted consent register before labeling.

## From worksheet to intake

When a batch is approved for import, the outcomes above are copied into the
consented intake CSV whose exact columns are `REQUIRED_COLUMNS` and
`OPTIONAL_COLUMNS` in `src/consented_data.py` (`reviewer_a_id`,
`reviewer_a_label`, `reviewer_b_*`, `adjudicator_id`, `adjudicated_label`,
`review_status`, and the rest). The intake validator enforces the rules above
(distinct reviewers, independent adjudication on disagreement, adjudication
matching agreeing reviewers, no low-confidence finals) and rejects
unrecognized extra columns, including prediction fields.


### Independent review evidence sidecar (version 2)

The import command's `--scam-assessments` option requires separate per-record
reviewer outcomes and actual adjudication. Populate from the two separately
returned reviewer sheets, not a common default. This example is fictional.

```json
{
  "schema_version": 2,
  "records": {
    "fictional_record": {
      "reviewer_a": {"scam": "suspected", "confidence": "medium", "category": "bank_alert"},
      "reviewer_b": {"scam": "not_suspected", "confidence": "high", "category": "bank_alert"},
      "adjudicated": {"scam": "not_suspected", "confidence": "high", "category": "bank_alert"}
    }
  }
}
```

Record the third reviewer's pseudonymous ID whenever the labels, scam
assessments or category disagree. The dated owner exception continues to
exclude affected rows pending independent review. Do not invent missing
outcomes or infer reviewer confidence from the donor's number. Preserve
historical imports but reconcile earlier default-based assessments against
actual reviewer sheets before future model use. Keep these files private.


For a batch intended for chronological holdout preparation, include
`group` and `received_at` in the master worksheet. Record the minimized,
verified reception date in ISO format, not the donation submission date.
An explicit campaign group is required when the date column is supplied;
the importer does not invent a chronological grouping from a receipt ID.
Do not fabricate missing timestamps. The training-purpose importer remains
distinct from the later sealed evaluation preflight.
