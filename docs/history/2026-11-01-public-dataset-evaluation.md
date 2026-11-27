# Public Dataset Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible, privacy-conscious evaluation path for the CC BY 4.0 Philippine SMS corpus while keeping public, synthetic, and consented results separate.

**Architecture:** Extend the flat `src/` modules and canonical CSV loader rather than creating the requested but nonexistent `sms_spam_detector` package. Keep downloading, normalization, PII detection, and metric/report generation in focused modules; use existing model inference and metric helpers.

**Tech Stack:** Python 3.11+, stdlib (`urllib`, `zipfile`, `hashlib`, `dataclasses`), pandas/scikit-learn already in project dependencies, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-11-01-public-sms-evaluation-and-consented-intake-design.md`

## Global Constraints

- Do not download, commit, or check real SMS into tests or Git.
- Do not ingest the Hugging Face merged corpus until every underlying source’s usage terms are verified.
- Do not claim representative or real-world Philippine accuracy from a single-person public inbox.
- Do not change prediction scoring, thresholds, or response schema.
- Do not add heavyweight dependencies or replace the no-build frontend architecture.
- Reports contain aggregate counts and hashes only, never message excerpts.

## Review Focus

- Kaggle ZIP path traversal or unexpected archive entries must not write outside `data/external/`; test malicious member paths.
- Kaggle category changes/unknown labels must be counted and rejected or explicitly excluded; test unrecognized categories.
- Redacted/empty rows and duplicate records must have accurate aggregate counts; test category mapping and exact normalized duplicates.
- One-class evaluation data must not crash ROC-AUC/PR-AUC or emit misleading metrics; test explicit undefined values.
- Reports/manifests must not include message text or local absolute paths; test with a unique secret fixture string.

---

### Task 1: Kaggle-only download and normalized records

**Files:**
- Create: `src/public_datasets.py`
- Modify: `src/import_public_dataset.py`
- Create: `scripts/download_datasets.py`
- Modify: `.gitignore`, `Makefile`, `data/external/README.md`
- Test: `tests/test_public_datasets.py`, `tests/test_download_datasets.py`

**Interfaces:**
- Produces `MessageRecord(text: str, label: str | None, source: str, record_id: str, lang: str | None = None, received_at: str | None = None, category: str | None = None)`.
- Produces `normalize_kaggle_ph_csv(path) -> tuple[list[MessageRecord], dict[str, int]]`; summary keys include rows seen, rows loaded, blank/redacted excluded, unknown categories, exact duplicates removed.
- Produces `download_kaggle_ph(destination, username, key) -> Path`; it downloads via stdlib HTTPS and safely extracts one expected CSV to ignored storage.

- [ ] **Step 1: Write failing tests** for `spam`/`ads`→`spam`, `gov`/`notifs`/`OTP`→`ham`, blank/redacted exclusion, unknown-category count/error, stable IDs, duplicate counts, missing credentials, and malicious ZIP paths.
- [ ] **Step 2: Run** `pytest tests/test_public_datasets.py tests/test_download_datasets.py -q`; confirm failures identify missing interfaces.
- [ ] **Step 3: Implement** the record and normalizer in `src/public_datasets.py`; keep canonical output columns `message,label,source,category,language,received_at,data_kind,dataset_id,dataset_version,license` compatible with `src.dataset_loading`.
- [ ] **Step 4: Implement** a downloader using `KAGGLE_USERNAME` and `KAGGLE_KEY`, failing with a clear credential message; reject unexpected archive paths and overwrite attempts.
- [ ] **Step 5: Add** `make datasets`, ignore `data/external/*` while tracking its README, and record source URL, CC BY 4.0, attribution, retrieval date procedure, field/category rules, single-inbox caveat, redactions, and HF-blocked status.
- [ ] **Step 6: Run** the two focused test modules and `ruff check`/`mypy` on changed Python files; expect all tests to pass with no network access.

### Task 2: PII spans and redaction

**Files:**
- Create: `src/privacy/__init__.py`, `src/privacy/scrub.py`
- Test: `tests/test_pii_scrub.py`

**Interfaces:**
- Produces frozen `Span(start: int, end: int, category: str, value: str)`.
- Produces `detect_pii(text: str, *, strict: bool = True) -> list[Span]` and `redact(text: str, *, replacement: str = "[REDACTED]", strict: bool = True) -> str`.
- URLs are flagged but preserved by `redact`; other spans are redacted without corrupting offsets.

- [ ] **Step 1: Write failing tests** for PH mobile numbers with country code/local/spaces/dashes, 11/12 digit runs and OTPs, emails, URLs/short links, representative PH ID/account patterns, overlapping matches, strictness, and non-PII controls.
- [ ] **Step 2: Run** `pytest tests/test_pii_scrub.py -q`; confirm expected failures.
- [ ] **Step 3: Implement** deterministic span collection, overlap coalescing, configurable conservative patterns, and right-to-left replacement while preserving URL text.
- [ ] **Step 4: Run** `pytest tests/test_pii_scrub.py -q` and verify every span points to the exact source substring.

### Task 3: External-dataset evaluation reports

**Files:**
- Create: `src/public_evaluation.py`
- Modify: `src/evaluate.py` only to dispatch a distinct `--external-dataset` mode if that cleanly preserves legacy CLI behavior; otherwise expose `python -m src.public_evaluation` and a `smsd-evaluate-public` entry point.
- Modify: `pyproject.toml`, `Makefile`
- Test: `tests/test_public_evaluation.py`

**Interfaces:**
- Produces `evaluate_public_dataset(dataset_path, model_path, output_dir, *, operating_fpr: float = 0.05) -> dict[str, Any]`.
- Produces `<dataset>_<model_version>.json` and `<dataset>.md` without storing examples.
- Uses `src.dataset_loading.load_dataset`, `src.predict.load_model`/`spam_probabilities`, and `src.metrics` where applicable.

- [ ] **Step 1: Write failing tests** for all required report metadata, confusion counts/FNR, AUC/calibration/threshold fields, per-language/source breakdown, undefined single-class metrics, distinct provenance groups, and absence of message text/absolute paths.
- [ ] **Step 2: Run** `pytest tests/test_public_evaluation.py -q`; confirm expected failures.
- [ ] **Step 3: Implement** a standalone evaluator that loads the existing model and dataset, hashes artifacts/inputs, records git SHA/dirty state/config/dependencies/timestamp, and emits privacy-safe per-source/per-language summaries.
- [ ] **Step 4: Add** calibration bins and threshold analysis for the highest threshold meeting the configured false-positive bound; report `unavailable` when sample counts cannot support the estimate.
- [ ] **Step 5: Add** CLI and `make eval DATA=... MODEL=...`; prevent public, synthetic, and consented records from being aggregated into one headline result.
- [ ] **Step 6: Run** focused evaluation tests, legacy `tests/test_evaluate.py`, and CLI help smoke tests.

### Task 4: Public-evaluation documentation and verification

**Files:**
- Create: `docs/evaluation.md`
- Modify: `README.md`, `docs/MODEL_CARD.md`, `docs/DATASET_INVENTORY.md`, `docs/DATA_COLLECTION.md`
- Test: `tests/test_repo_hygiene.py` or targeted docs contract test

- [ ] **Step 1: Write failing documentation contract checks** for Kaggle-only source status, attribution, single-inbox limitation, blocked HF source, and no claims of representative accuracy.
- [ ] **Step 2: Run** the targeted tests and confirm the needed docs are absent/outdated.
- [ ] **Step 3: Document** setup, downloader credentials, normalized schema/category mapping, evaluation command/report fields, limitations, source attribution, and reproducibility.
- [ ] **Step 4: Run** the targeted docs tests plus `make test`, `make lint`, `make typecheck`, and relevant package smoke tests.

---

## Phase 1 exit criteria

No real dataset is committed or downloaded by CI; synthetic fixtures cover all transformations; the evaluator produces separate, privacy-safe reports; Hugging Face remains explicitly blocked until all constituent licenses are verified.
