# Countersign packet — preregistered gates and consent terms (D1–D3)

> **Status:** DRAFT for reviewer completion. The owner ratified these values on
> 2026-11-28 (record: `docs/superpowers/specs/2026-11-28-roadmap-completion-design.md`,
> ratified in conversation). This packet is what a qualified reviewer signs to
> convert D1/D3 from "pending qualified-reviewer countersign" to fully decided,
> per `docs/PH_FIELD_EVALUATION_READINESS.md` ("a number-filled plan must be
> justified and signed") and `docs/DATA_COLLECTION.md` (privacy review before
> any collection).

## What the reviewer is certifying

By signing, the reviewer asserts they have independently reviewed the items
below and consider each internally consistent, feasible for the stated pilot
scope, and honest about its limitations. The reviewer is **not** endorsing any
model's accuracy — all Philippine data in the repository is synthetic.

## Items to review (source documents)

| Item | What to check | Where |
|---|---|---|
| Release gates (D1) | FPR/recall/calibration numbers are coherent with the pilot's sample sizes and the evaluator's actual checks | Spec §Ratified decisions; [PH_FIELD_EVALUATION_READINESS.md](../PH_FIELD_EVALUATION_READINESS.md) acceptance-gates table; [templates/consented-evaluation-plan.json](templates/consented-evaluation-plan.json) pre-filled widths |
| Consent terms (D2) | Notice `2026-11-01-v4`, 90-day retention, withdrawal mechanics match the implemented donation flow | [privacy-notice.md](privacy-notice.md); [DONATION_INTAKE.md](DONATION_INTAKE.md) |
| Pilot authorization scope (D3) | 10–30 personal-network donors; no public recruitment; stop conditions | [HUMAN_REVIEW.md](HUMAN_REVIEW.md); [DATA_COLLECTION.md](DATA_COLLECTION.md) |
| Governance exception (D2) | The dated, expiring owner-adjudication arrangement is acceptable for pilot labeling only | [HUMAN_REVIEW.md](HUMAN_REVIEW.md) and [DATA_COLLECTION.md](DATA_COLLECTION.md) exception paragraphs |
| Honesty framing | No real-world accuracy claims; synthetic-data caveats present | [MODEL_CARD.md](MODEL_CARD.md) §4; [evaluation.md](evaluation.md) |

## Reviewer certifications (check each)

- [ ] The preregistered gates in the table above are internally consistent and
      feasible for the pilot's stated scope (10–30 donors), or I have marked the
      specific number(s) to change in the comments block.
- [ ] The consent terms (notice `2026-11-01-v4`, 90-day retention, withdrawal)
      satisfy the privacy requirements for a local-only pilot round.
- [ ] The owner-adjudication exception is acceptable for pilot labeling only,
      with the expiry condition (third-reviewer onboarding) clearly recorded.
- [ ] I understand the countersign takes effect at sealed-test setup and pilot
      start, and does not authorize public recruitment or public deployment.

## Sign-off

```
Reviewer name:      ______________________________
Capacity:           qualified privacy/legal reviewer
Review date:        ______________________________
D1 gates:           ☐ countersigned  ☐ changes required (see comments)
D2 consent terms:   ☐ countersigned  ☐ changes required
D3 pilot scope:     ☐ countersigned  ☐ changes required
Comments:           ______________________________
                    ______________________________
```

## How to record

After signing: set the D1/D3 Status rows in
[../OWNER_DECISIONS.md](../OWNER_DECISIONS.md) to
"Decided 2026-11-28 — countersigned <date> by <name>", commit, and note the
countersign in the recruitment-kit readiness checklist. Until then, D1/D3
remain "pending qualified-reviewer countersign" and pilot collection must not
start.
