# Five-Sprint Improvement Design

**Date:** 2026-11-28
**Status:** Approved by the project owner; implementation in progress.

## Intent

Improve the Philippine SMS spam/scam detector without overstating its evidence.
The project already has a green baseline (549 tests, 81.5% coverage, lint and
mypy clean). The work closes trust, reliability, maintainability, and evaluation
gaps rather than rewriting the system.

## Goals

1. Make documentation and runtime behavior agree, especially privacy and
   feedback claims.
2. Protect the most trust-critical code with tests and production safeguards.
3. Make monitoring, model reload, and deployment behavior operable.
4. Make the browser UI safer to change and more accessible.
5. Add evaluation tooling that helps future model work without claiming
   Philippine field accuracy from synthetic data.

## Non-goals

- No real-message collection, participant recruitment, or field-performance
  claim.
- No automatic training from anonymous feedback.
- No microservice split or frontend framework rewrite.
- No synthetic-score chasing.

## Constraints

- Python >= 3.11, verified on 3.13; ruff line length 120; mypy on src and api.
- Existing privacy guarantees: no message bodies, spans, or direct client IPs
  in application logs.
- Model artifacts remain deployment data, never committed.
- Tests must run without data/raw/spam.csv or a models/*.pkl artifact.

## Approaches considered

1. **Truth and reliability first** (chosen): fix docs/code drift, privacy
   logging, artifact verification, and test gaps. Low risk, high trust payoff.
2. **Product/UX first**: split the 1,941-line app.js and add accessibility
   automation. Valuable but lower urgency than incorrect claims.
3. **ML research first**: error analysis, calibration, transformer benchmarks.
   Blocked from real evidence by the absence of consented data.

The chosen plan runs the truth/reliability work first, then operations,
frontend, and evaluation tooling. Each sprint is independently shippable.

## Sprint map

| Sprint | Theme | Main deliverables |
|---|---|---|
| 1 | Truth and trust | Docker access-log fix, architecture docs, production artifact hash, docs consistency test |
| 2 | Tests and CI | feedback CLI wiring, evaluation tests, coverage ratchet, security workflow, performance budget |
| 3 | Operations | drift baseline, model reload, Prometheus metrics, trusted proxy identity, container hardening |
| 4 | Frontend | i18n parity, axe-core accessibility check, ESLint |
| 5 | Evaluation | error-analysis tool, synthetic hard-negative challenge set, repeated group-aware CV report |
