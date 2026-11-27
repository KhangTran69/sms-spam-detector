# Owner decision register

This register collects the decisions that **only the project owner (and, where
noted, a qualified privacy/legal reviewer) can make**. It introduces no new
policy: every row points at the authoritative document that defines the
decision. Roadmap reference: [ROADMAP.md](ROADMAP.md), decision register D1–D6.

**How to record a decision:** fill in the Decision, Date, and Approver columns
in the table below (or link the signed document), commit, and update the
Status column in the linked authoritative doc. Do not mark a decision made
unless the named approver has actually approved it.

## Pending decisions

| # | Decision | Authoritative document | Status | Date | Approver |
|---|---|---|---|---|---|
| D1 | Preregister numerical release gates (FP/FN bounds per critical category, recall floors, calibration error, coverage/uncertainty widths) **before** any sealed evaluation | [PH_FIELD_EVALUATION_READINESS.md](PH_FIELD_EVALUATION_READINESS.md) "Acceptance gates" + [templates/consented-evaluation-plan.json](templates/consented-evaluation-plan.json) | **Not preregistered** — no numbers signed | | |
| D2 | Approve the donor-facing privacy notice version and the retention period | [privacy-notice.md](privacy-notice.md), [DATA_COLLECTION.md](DATA_COLLECTION.md) | Notice exists and is versioned; retention period owner-set pending | | |
| D3 | Authorize (or decline) the first consented collection round; name data steward, two labelers, independent adjudicator | [DATA_COLLECTION.md](DATA_COLLECTION.md), [HUMAN_REVIEW.md](HUMAN_REVIEW.md) | **No authorization; no participants contacted** | | |
| D4 | Transformer ensemble spike: promote as optional tier, or archive with rationale | [BENCHMARKING.md](BENCHMARKING.md) (optional local transformer spike), [MODEL_CARD.md](MODEL_CARD.md) | Spike is local-only, disabled by default; promotion gate not passed | | |
| D5 | Deployment target beyond local (if any) and the operator scope table (gateway, workers, monitoring custodian, incident contact) | [DEPLOYMENT.md](DEPLOYMENT.md), [OPERATIONAL_AND_ACCESSIBILITY_REVIEW.md](OPERATIONAL_AND_ACCESSIBILITY_REVIEW.md) | Local-only; no public deployment authorized | | |
| D6 | Coverage-floor targets beyond the current 78% ratchet | `pyproject.toml` (coverage settings), CI quality job | Floor 78%, current 81.6%; target owner-set | | |

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
