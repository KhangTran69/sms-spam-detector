# Archived plans (executed)

These design/spec/plan documents were the inputs to already-merged work. They
are kept for provenance only — **do not execute them again**; every task list
below is complete.

| Document | Status | Landed in |
|---|---|---|
| [2026-11-01-public-sms-evaluation-and-consented-intake-design.md](2026-11-01-public-sms-evaluation-and-consented-intake-design.md) | Implemented (both phases) | PR #22 (`codex/public-ph-sms-evaluation`, 2026-11-01) and follow-ups #23–#34 |
| [2026-11-01-public-dataset-evaluation.md](2026-11-01-public-dataset-evaluation.md) | Implemented (Phase 1) | PR #22: `src/public_datasets.py`, `src/public_evaluation.py`, `scripts/download_datasets.py`, `data/external/README.md`, `docs/evaluation.md` |
| [2026-11-01-consented-donation-intake.md](2026-11-01-consented-donation-intake.md) | Implemented (Phase 2) | PR #22 + #24/#25 fixes: `api/donations.py`, donate page, `scripts/export_donations.py`, `docs/DONATION_INTAKE.md`, `docs/privacy-notice.md` |

Deviations from the plans that reviewers should know about:

- The plans assumed flat `src/` modules; later architecture work (PRs #19/#25)
  introduced `src/dataset_loading.py` / `dataset_schema.py` / `dataset_splits.py`
  as the canonical loader path. The plan text's module names are historical.
- The Hugging Face merged corpus remains blocked pending source-level license
  verification, exactly as the spec required.

New forward work is tracked in [../ROADMAP.md](../ROADMAP.md) and governed by
[../PH_FIELD_EVALUATION_READINESS.md](../PH_FIELD_EVALUATION_READINESS.md).
