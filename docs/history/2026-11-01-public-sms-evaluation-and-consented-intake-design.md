# Public SMS Evaluation and Consented Intake Design

## Intent

Extend the Philippine SMS detector with a reproducible evaluation path for approved Philippine public SMS data and a separate, consent-based route for future donations. The work should make the evidence stronger without implying that one person’s inbox or public availability establishes general Philippine performance or consent from every message participant.

## Current state

The repository uses flat `src/` modules, not `src/sms_spam_detector/`. `src.dataset_loading` owns canonical CSV loading, label normalization, duplicate removal, source manifests, and group-leakage checks. `src.import_public_dataset` currently normalizes UCI input. `src.evaluate` and `src.benchmark` already produce reproducible model reports. `src.consented_data` and `src.import_consented` provide local-only CSV preflight/import workflows.

FastAPI routes are in `api/routes.py`, with middleware and rate limiting in `api/main.py`. Prediction endpoints must retain their existing behavior and response schema. There is no donation endpoint, persistent donation store, or general PII-span utility. The README and model card currently state that Philippine fixtures are synthetic and real-world Philippine performance is unproven.

The owner’s dataset README identifies `spam-and-marketing-sms` as CC BY 4.0, and describes redactions, categories, and single-person sampling. The Hugging Face Space’s MIT metadata does not establish reuse terms for its merged source corpora, so that source is out of scope and will be documented as blocked until source-level terms are verified.

## Goals

- Add a privacy-conscious downloader/importer for the owner-licensed Kaggle SMS corpus, writing only to ignored external-data storage and preserving required attribution.
- Normalize dataset records and labels to the project’s existing `ham`/`spam` vocabulary, report dropped and unmappable rows, and report deduplication.
- Evaluate the existing trained model against normalized approved data, with reproducible machine- and human-readable reports, per-source/language coverage, error metrics, uncertainty, calibration, and operating-threshold analysis.
- Add a configurable PII detector/redactor and tests, while keeping public evaluation ingestion distinct from consented message storage.
- Add a separate, explicit-consent donation UI/API with versioned notice, timestamp, validation, rate limiting, PII rejection, local SQLite persistence, withdrawal, and normalized export.
- Keep raw SMS out of Git, logs, public reports, analytics, caches, and ordinary API behavior. Add accurate dataset status and limitation documentation.

## Non-goals

- Do not download, commit, or check real SMS into tests or Git.
- Do not ingest the Hugging Face merged corpus until every underlying source’s usage terms are verified.
- Do not claim representative or real-world Philippine accuracy from a single-person public inbox.
- Do not change prediction scoring, thresholds, or response schema.
- Do not make legal determinations about the DPA; document operational considerations and the need for appropriate review.
- Do not add heavyweight dependencies or replace the no-build frontend architecture.

## Approaches considered

1. **One integrated release:** build data ingestion, evaluation, scrubbing, and live donation storage together. This completes the full feature set in one review, but combines public benchmark work with new sensitive-data persistence.
2. **Two reviewable phases (recommended):** first land public Kaggle ingestion, evaluation, PII utility, and source/benchmark documentation; then add consent intake, SQLite lifecycle, and its dedicated UI/API tests. This lets the loader and scrubbing behavior be inspected before persistent message storage is introduced.

The implementation will use approach 2. Each phase should be independently testable and reviewable, while preserving the requested end-to-end objective.

## Data and label policy

The shared normalized record must include message text, canonical label, source identifier, optional language/date, and stable record ID. Existing project fields and loader conventions take precedence over introducing a parallel package hierarchy.

For the Kaggle owner dataset, source categories need an explicit mapping into `ham`/`spam`. The proposed mapping is `spam` and `ads` to `spam`, and `gov`, `notifs`, and `OTP` to `ham`; fully redacted or blank text is excluded and counted. This reflects the project’s existing definition that spam may include advertising, but must be clearly disclosed in reports. Any unknown category is counted and excluded or causes an actionable validation error; it is never silently discarded. Reports retain only aggregate counts and hashes, never message excerpts.

Deduplication should preserve the first deterministic record after exact normalized-text matching. Optional near-duplicate handling must use a documented hashed key and report removals; it must not expose message text in manifests. Dataset files remain outside version control under `data/external/`.

## Evaluation design

Extend the existing evaluator rather than creating a competing metric stack. A CLI and Make target should load one or more normalized datasets, score the selected existing model, and emit per-dataset JSON and Markdown summaries. Results from public, synthetic, and consented sources remain separate. Reports record model/version/hash, git revision and dirty state, dataset hash, timestamp, split or evaluation membership fingerprint, dependency/configuration metadata, sample/label counts, false positives, false negatives, false-negative rate, precision/recall/F1, ROC-AUC/PR-AUC when defined, uncertainty, language/source/category coverage, calibration bins, and threshold operating points. Undefined metrics for one-class/small subsets are represented explicitly.

The benchmark must distinguish a public corpus sourced from one inbox from a representative independently labeled cohort. Its results support diagnostic comparisons on that corpus only.

## PII and donation design

The PII utility returns typed spans with offsets and categories, plus a redaction helper. Strictness is configurable. It flags Philippine mobile formats, long numeric runs, emails, URLs/short links, and conservative government/account identifiers. URLs are flagged rather than silently removed because they are relevant smishing signals. Tests include overlapping patterns, OTP-like number runs, allowlisted non-identifiers, and offset correctness.

Donation intake is a distinct route and page, separate from prediction. Consent is required and bound to a versioned notice; accepted submissions persist the notice version and UTC consent timestamp with an opaque record ID. Server validation enforces content type, bounded message length, existing rate-limit conventions, and PII rejection. Rejections may return only the flagged text spans to the submitter; raw input must not enter logs. Accepted text is stored only in local SQLite under ignored `data/donations/`, with bootstrap/migration, export, withdrawal/deletion, and documented retention. Donation routes must not be exposed unless the operator explicitly enables collection, unless repository review identifies an existing secure opt-in convention.

## Privacy, safety, and documentation

No message content may appear in diagnostics, generated reports, CI artifacts, cache entries, or source control. Downloader reports include retrieval date, license/terms, hashes, counts, and caveats. Public availability is not treated as consent. The Kaggle dataset’s CC BY 4.0 attribution is retained, but license terms do not by themselves resolve privacy or other rights concerns. The donation notice describes purpose, retention, withdrawal, and local handling in plain language. UI copy must maintain the existing assistive-use and trusted-official-channel guidance.

## Validation

Use small synthetic fixtures only. Add tests for source-label mapping, unknown labels, duplicate accounting, downloader credential/URL errors where applicable, evaluation report fields and metric edge cases, PII span/redaction behavior, absent/false consent, rate limiting, invalid content type/length, withdrawal, export schema, and unchanged prediction response behavior. Run pytest, Ruff lint/format, mypy, frontend module/service-worker/browser checks, and package smoke checks appropriate to changed files. Do not make claims of full accessibility or multi-browser coverage beyond checks actually performed.

## Implementation sequence

1. Kaggle-only record normalization, downloader metadata, ignored external storage, and synthetic fixtures.
2. PII span detection/redaction and unit tests.
3. Public-corpus evaluation CLI/reports and reproducibility tests.
4. Separate consent notice and donation UI/API/SQLite lifecycle/export/withdrawal.
5. Dataset status, evaluation, privacy/collection documentation, Make/CI wiring, and full validation.

The Hugging Face merge remains listed as blocked unless licenses for all underlying SMS sources are established before implementation.
