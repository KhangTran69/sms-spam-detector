# Owner decision register

This register collects the decisions that **only the project owner (and, where
noted, a qualified privacy/legal reviewer) can make**. It introduces no new
policy: every row points at the authoritative document that defines the
decision. Roadmap reference: [ROADMAP.md](ROADMAP.md), decision register D1–D6.

**How to record a decision:** fill in the Decision, Date, and Approver columns
in the table below (or link the signed document), commit, and update the
Status column in the linked authoritative doc. Do not mark a decision made
unless the named approver has actually approved it.

## Decision register

| # | Decision | Authoritative document | Status | Date | Approver |
|---|---|---|---|---|---|
| D1 | Preregister numerical release gates (FP/FN bounds per critical category, recall floors, calibration error, coverage/uncertainty widths) **before** any sealed evaluation — ratified in [docs/superpowers/specs/2026-11-28-roadmap-completion-design.md](superpowers/specs/2026-11-28-roadmap-completion-design.md) "Ratified decisions"; the interval widths, coverage minimums, and 12 campaign groups are pre-filled in [templates/consented-evaluation-plan.json](templates/consented-evaluation-plan.json) (corpus-dependent hashes stay empty until sealed-test setup) | [PH_FIELD_EVALUATION_READINESS.md](PH_FIELD_EVALUATION_READINESS.md) "Acceptance gates" + [templates/consented-evaluation-plan.json](templates/consented-evaluation-plan.json) | **Decided 2026-11-28** — pending qualified-reviewer countersign | 2026-11-28 | Project owner |
| D2 | Approve the donor-facing privacy notice version and the retention period — ratified in [docs/superpowers/specs/2026-11-28-roadmap-completion-design.md](superpowers/specs/2026-11-28-roadmap-completion-design.md): notice `2026-11-01-v4` as-is and 90-day retention (as implemented); labeling pairs the project owner with one recruited independent reviewer, and the owner adjudicates disagreements only until a third reviewer is named (dated, expiring exception recorded in [HUMAN_REVIEW.md](HUMAN_REVIEW.md) and [DATA_COLLECTION.md](DATA_COLLECTION.md)). Pilot labeling starts only after the recruited independent reviewer is onboarded | [privacy-notice.md](privacy-notice.md), [DATA_COLLECTION.md](DATA_COLLECTION.md) | **Decided 2026-11-28** | 2026-11-28 | Project owner |
| D3 | Authorize (or decline) the first consented collection round; name data steward, two labelers, independent adjudicator — ratified in [docs/superpowers/specs/2026-11-28-roadmap-completion-design.md](superpowers/specs/2026-11-28-roadmap-completion-design.md): one pilot round authorized, contingent on a rehearsed donation flow, the ratified notice, and an owner-reviewed recruitment kit; scope is 10–30 donors from the owner's personal network with no public recruitment, and the HUMAN_REVIEW/DATA_COLLECTION stop conditions apply | [DATA_COLLECTION.md](DATA_COLLECTION.md), [HUMAN_REVIEW.md](HUMAN_REVIEW.md) | **Decided 2026-11-28** — pending qualified-reviewer countersign | 2026-11-28 | Project owner |
| D4 | Transformer ensemble spike: promote as optional tier, or archive with rationale — ratified in [docs/superpowers/specs/2026-11-28-roadmap-completion-design.md](superpowers/specs/2026-11-28-roadmap-completion-design.md): the spike stays archived and local-only and is revisited only after a consented development set exists | [BENCHMARKING.md](BENCHMARKING.md) (optional local transformer spike), [MODEL_CARD.md](MODEL_CARD.md) | **Decided 2026-11-28** | 2026-11-28 | Project owner |
| D5 | Deployment target beyond local (if any) and the operator scope table (gateway, workers, monitoring custodian, incident contact) — ratified in [docs/superpowers/specs/2026-11-28-roadmap-completion-design.md](superpowers/specs/2026-11-28-roadmap-completion-design.md): local-only this cycle, no public deployment; the macOS service remains personal tooling | [DEPLOYMENT.md](DEPLOYMENT.md), [OPERATIONAL_AND_ACCESSIBILITY_REVIEW.md](OPERATIONAL_AND_ACCESSIBILITY_REVIEW.md) | **Decided 2026-11-28** | 2026-11-28 | Project owner |
| D6 | Coverage-floor targets beyond the current 78% ratchet — ratified in [docs/superpowers/specs/2026-11-28-roadmap-completion-design.md](superpowers/specs/2026-11-28-roadmap-completion-design.md): ratchet to 80% immediately and 85% by the end of the next quarter, enforced per-PR thereafter | `pyproject.toml` (coverage settings), CI quality job | **Decided 2026-11-28** | 2026-11-28 | Project owner |

## Why these cannot be auto-decided

D1–D3 gate real-data collection and any performance claim; guessing numbers or
consent terms here would fabricate governance. D4–D6 trade review effort,
dependency weight, and compute that belong to the owner's budget.

## Current state (context for deciding)

- All tracked Philippine data is synthetic; no consented corpus exists. The
  public one-person inbox diagnostic is not representative evidence.
- Engineering CI is green (pytest 549+, coverage 81.6%, lint/type/browser/
  container/wheel gates).
- The donation-intake, consented-split, and one-shot sealed-test workflows are
  implemented and rehearsed with synthetic data only.
