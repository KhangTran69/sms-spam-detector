# Contributing to Philippine SMS Spam and Scam Detector

Thank you for your interest in contributing to the **Philippine SMS Spam and Scam Detector** (`philippine-sms-spam-detector`). This project provides an assistive spam/scam classifier, API, and web interface for Philippine English, Filipino, and Taglish text.

Because this tool processes personal and potentially sensitive SMS communications, **privacy, reproducible evaluation, and strict security** are first-class engineering requirements.

---

## Code of Conduct & Core Privacy Invariants

Every contribution must preserve these core invariants:

1. **Zero Server-Side Message Retention**: Never store, log, serialize, or persist SMS message bodies, excerpts, or derived tokens on the server, in log sinks, or in databases.
2. **Privacy-Preserving Logs**: Structured logs record only operational metadata (request ID, path, HTTP status, latency, client IP). Never log request payloads.
3. **No Real PII in Git**: Never commit personal phone numbers, names, email addresses, OTP codes, or real-world user messages to this repository. All Philippine data fixtures in git must be synthetic.
4. **Assistive Classifier Scope**: Predictions are advisory. The model score is not a legal finding of fraud.

---

## Development Setup

### Prerequisites

- Python 3.11, 3.12, or 3.13
- Node.js 20+ and npm (for browser and UI testing)
- Make (optional, but recommended)

### 1. Virtual Environment & Dependencies

```bash
git clone https://github.com/KhangTran69/sms-spam-detector.git
cd sms-spam-detector

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies using pinned constraints
pip install -r constraints/py3.12.txt -e ".[dev]"
```

### 2. Browser & Frontend Test Setup

```bash
npm ci
npx playwright install --with-deps chromium
```

---

## Quality Gates & Verification

Before opening a pull request, ensure all local verification checks pass cleanly:

```bash
# 1. Run all Python unit and integration tests
pytest -q

# 2. Check and enforce code style and formatting
ruff check .
ruff format --check .

# 3. Static type checking
mypy src api

# 4. Run UI module and browser behavior tests
npm run test:modules
npm run test:browser

# Or run the make target
make test
```

To auto-format code with `ruff`:
```bash
ruff format .
```

---

## Working with Data & Training

### Synthetic Philippine Fixtures

- Synthetic training supplements reside under `data/raw/synthetic/` and `data/raw/eval/`.
- Synthetic messages are created to test specific fraud patterns (e.g., OTP phishing, lottery scams, fake delivery notices).
- When adding new synthetic patterns, ensure template families are grouped properly so that group-aware cross-validation prevents leakage between train, validation, and test splits.

### Consented Philippine Messages

Real Philippine messages can **only** be added under strict revocable consent:
- Use the blank template at `data/templates/consented_ph_sms_template.csv`.
- Work exclusively in an approved encrypted workspace.
- Redact all personal phone numbers, names, and transaction references before ingestion.
- Run the consent preflight validator:
  ```bash
  python -m src.consented_data /secure/workspace/consented_batch.csv --purpose training
  python -m src.import_consented --input /secure/workspace/consented_batch.csv --purpose training --output-dir /secure/workspace/approved
  ```
- See [docs/DATA_COLLECTION.md](docs/DATA_COLLECTION.md) for full compliance protocols.

---

## Submitting Pull Requests

1. **Branch Naming**:
   - `feat/<feature-name>` for new features or capabilities
   - `fix/<bug-description>` for bug fixes
   - `refactor/<scope>` for code restructuring
   - `docs/<topic>` for documentation improvements
2. **Commit Messages**:
   - Follow standard Conventional Commits: `feat(scope): short description`, `fix(scope): short description`, `test(scope): ...`, `docs: ...`.
3. **Tests Required**:
   - Any new feature, regex pattern, or API route must be accompanied by comprehensive tests in `tests/`.
   - Ensure the regression suite (`tests/test_model.py`) remains intact without regressions on canonical templates.
4. **Documentation**:
   - Update relevant documents under `docs/` (such as `docs/ARCHITECTURE.md`, `docs/MODEL_CARD.md`, or `README.md`) if interfaces, configuration flags, or dependencies change.
