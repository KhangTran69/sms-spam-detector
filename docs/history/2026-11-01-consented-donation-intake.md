# Consented Donation Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an operator-enabled, separate donation flow with explicit consent, PII rejection, local SQLite storage, withdrawal, and safe normalized export.

**Architecture:** Add a dedicated static donation page and API routes without changing prediction endpoints. Store accepted records in a bootstrapped SQLite database under ignored local storage; gate every donation route behind an explicit environment opt-in and reuse the app’s existing rate-limit middleware.

**Tech Stack:** Python 3.11+, stdlib `sqlite3`/`uuid`/`datetime`, existing FastAPI/Pydantic, vanilla HTML/JS, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-01-public-sms-evaluation-and-consented-intake-design.md`

## Global Constraints

- Do not download, commit, or check real SMS into tests or Git.
- Do not change prediction scoring, thresholds, or response schema.
- Do not add heavyweight dependencies or replace the no-build frontend architecture.
- Raw SMS must never appear in logs, public reports, analytics, caches, or source control.
- Collection must remain disabled unless the operator explicitly enables it.
- A user-provided label is a hint, not an independently verified ground-truth label.

## Review Focus

- Missing, false, or stale consent must never store a record; test absent and false consent and notice version mismatch.
- PII rejection must not persist text or put it in server logs; test rejected payload and captured log output.
- Client-provided content type/length/rate abuse must receive safe bounded errors; test non-JSON, oversized message, and limit response.
- Withdrawal IDs must be unguessable and deletion must be idempotent without revealing whether another user’s record exists; test malformed, unknown, and valid IDs.
- Optional-label submissions must export as review-only/unlabeled staging data, not be accepted by model training/evaluation as truth; test export schema and eligibility fields.

---

### Task 1: Privacy notice and SQLite donation store

**Files:**
- Create: `docs/privacy-notice.md`
- Create: `api/donations.py`
- Modify: `.gitignore`
- Test: `tests/test_donations.py`

**Interfaces:**
- Produces `bootstrap_database(path: Path) -> None`, `create_donation(...) -> str`, `delete_donation(path: Path, record_id: str) -> bool`, and `export_donations(path: Path, output: Path) -> dict[str, int]`.
- Schema stores opaque record ID, raw message text, optional normalized label hint/language, notice version, UTC consent timestamp, creation timestamp, and withdrawal state/timestamp.
- Every database operation receives an injected path for test isolation; production default is ignored `data/donations/donations.sqlite3`.

- [ ] **Step 1: Write failing tests** for schema bootstrap/idempotence, accepted consent metadata persistence, no raw text in diagnostics, withdrawal/delete behavior, no-overwrite export, export header/schema, and unlabeled rows marked as pending review.
- [ ] **Step 2: Run** `pytest tests/test_donations.py -q`; confirm expected failures.
- [ ] **Step 3: Implement** SQLite bootstrap with parameterized SQL, transactions, opaque IDs, and export to a caller-selected secure path without storing donor contact details.
- [ ] **Step 4: Write** a versioned plain-language notice stating purpose, local handling, retention, withdrawal instructions, review/use limits, and that donation is optional.
- [ ] **Step 5: Run** `pytest tests/test_donations.py -q` and verify temporary database cleanup in tests.

### Task 2: Donation API validation, rate limiting, and opt-in

**Files:**
- Modify: `api/schemas.py`, `api/routes.py`, `api/main.py`
- Test: `tests/test_api.py`, `tests/test_donations_api.py`

**Interfaces:**
- `POST /donate` accepts `message`, optional `label_hint`, optional `language`, `consent: bool`, and `notice_version`.
- `DELETE /donate/{record_id}` withdraws consent and deletes the stored message; response does not disclose whether an unknown ID existed.
- `GET /donate` serves the donation page only when `SMSD_DONATIONS_ENABLED=1`.
- All donation API routes are disabled by default and return not-found while disabled.

- [ ] **Step 1: Write failing API tests** for disabled-by-default routes, false/missing consent, version mismatch, valid acceptance, PII span rejection, JSON content-type enforcement, request-length cap, route-level rate limit, safe deletion, and unchanged prediction response schema.
- [ ] **Step 2: Run** the new donation API tests and existing `tests/test_api.py`; confirm donation tests fail while prediction tests remain green.
- [ ] **Step 3: Implement** typed request/response schemas and routes that validate consent before storage, use `src.privacy.scrub.detect_pii`, return only offending spans on rejection, and never log request bodies.
- [ ] **Step 4: Add** `POST /donate` to the existing request-size/rate-limit path allowlist and apply the same configured per-IP limiter; preserve existing prediction middleware behavior.
- [ ] **Step 5: Run** donation API and full API tests, checking FastAPI error serialization contains no submitted text.

### Task 3: No-build donation page and form behavior

**Files:**
- Create: `api/web/donate.html`, `api/web/donate.js`
- Modify: `api/main.py`, `api/web/index.html`, `api/web/sw.js`, `scripts/wheel_smoke.py`, `tests/ui_modules.cjs`, `tests/browser_smoke.cjs`
- Test: `tests/test_web_contract.py`, browser smoke suite

**Interfaces:**
- Page links the versioned notice and requires an unchecked-by-default consent checkbox.
- Browser submits only after user action; no local persistence, retries, or automatic resubmission.
- Validation errors display PII categories/spans accessibly so the user can redact and retry manually.

- [ ] **Step 1: Write failing UI contract/module tests** for required consent, notice version, no persistence, explicit submit, accessible flagged-span rendering, and no automatic retry.
- [ ] **Step 2: Run** `npm run test:modules` and targeted Python UI contract tests; confirm new checks fail.
- [ ] **Step 3: Implement** standalone page and script with vanilla JS, keyboard-accessible status, client-side length check, POST request, and no message logging/storage.
- [ ] **Step 4: Wire** a link from the existing UI, serve the donation page only when enabled, and include new static assets in packaging and service-worker shell cache without caching donation POSTs.
- [ ] **Step 5: Run** module tests and Playwright browser tests for consent, successful local-fixture submission, PII rejection, disabled mode, and manual retry after correction.

### Task 4: Export and operational privacy documentation

**Files:**
- Create: `scripts/export_donations.py`, `docs/data-collection.md`
- Modify: `README.md`, `docs/DATA_COLLECTION.md`, `docs/PRIVACY.md`, `docs/MODEL_CARD.md`, `Makefile`
- Test: `tests/test_donation_export.py`, docs/repo hygiene tests

- [ ] **Step 1: Write failing tests** for export path safety, canonical normalized columns, omission/counting of withdrawn records, and clear status for records with unreviewed or missing label hints.
- [ ] **Step 2: Run** targeted export and documentation contract tests; confirm expected failures.
- [ ] **Step 3: Implement** a local-only export command that emits the shared schema and aggregate counts, with no content printed to stdout; keep output under an operator-selected secure location.
- [ ] **Step 4: Document** consent sequence, notice version, opt-in flag, database location, retention/deletion process, public availability versus consent, operational DPA considerations, export review requirements, and the HF source’s blocked status.
- [ ] **Step 5: Run** `make test`, `make lint`, `make typecheck`, UI module/service-worker/browser checks, and package smoke checks; inspect output/log fixtures for SMS leakage.

---

## Phase 2 exit criteria

Collection is disabled by default; every accepted row has explicit versioned consent; PII rejection does not persist raw input; withdrawal removes message text; exports are review-stage only; prediction behavior remains unchanged; all checked logs/reports are message-free.
