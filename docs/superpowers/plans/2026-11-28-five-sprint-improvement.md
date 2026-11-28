# Five-Sprint Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the project's trust, reliability, operations, frontend, and evaluation gaps across five independently shippable sprints.

**Architecture:** Keep the existing FastAPI + scikit-learn + no-build vanilla JS architecture. Add focused modules, tests, and configuration rather than restructuring the system. Every behavioral change is covered by a test that fails first.

**Tech Stack:** Python 3.11+ (verified 3.13), FastAPI, scikit-learn, joblib, pytest, ruff, mypy, Playwright, Node.js.

**Spec:** `docs/superpowers/specs/2026-11-28-five-sprint-improvement-design.md`

## Global Constraints

- Python >= 3.11; verified on 3.13.
- Ruff line length 120; lint select E,F,I,UP,B,SIM; mypy on src and api.
- No message bodies, spans, or direct client IPs in application logs.
- No real-message collection or field-performance claims.
- Anonymous feedback never triggers automatic training.
- Tests must not require data/raw/spam.csv or models/*.pkl.
- Keep the no-build UI; no frontend framework.

## Review Focus

- A container deployment must not log client IPs even though `api.cli` disables Uvicorn access logs.
- A production model must not load without a verified sidecar hash.
- A drift monitor must have a baseline after a model loads, or say why it does not.
- A reload must not expose a half-loaded model or lose the previous one on failure.
- An accessibility scan must run against the real UI and fail on serious violations.

---

## Sprint 1 — Truth and trust

### Task 1: Container access logs are content-free

**Files:**
- Modify: `Dockerfile`
- Modify: `tests/test_repo_hygiene.py`
- Test: `tests/test_repo_hygiene.py::test_dockerfile_disables_uvicorn_access_log`

**Interfaces:**
- Produces: a Docker `CMD` that includes `--no-access-log`.

- [ ] **Step 1: Write the failing test**

```python
def test_dockerfile_disables_uvicorn_access_log() -> None:
    dockerfile = _text("Dockerfile")
    cmd_lines = [line for line in dockerfile.splitlines() if line.strip().startswith("CMD ")]
    assert cmd_lines, "Dockerfile must declare a CMD"
    assert any("--no-access-log" in line for line in cmd_lines), (
        "container deployments must not emit Uvicorn access logs with client IPs"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repo_hygiene.py::test_dockerfile_disables_uvicorn_access_log -q`
Expected: FAIL because the Docker CMD lacks `--no-access-log`.

- [ ] **Step 3: Add `--no-access-log` to the Docker CMD**

Change the final CMD to:
```dockerfile
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_repo_hygiene.py::test_dockerfile_disables_uvicorn_access_log -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile tests/test_repo_hygiene.py
git commit -m "fix: keep container access logs content-free"
```

### Task 2: Architecture documentation matches the code

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `docs/IMPROVEMENT_EXECUTION.md`
- Test: `tests/test_repo_hygiene.py::test_architecture_docs_do_not_describe_unimplemented_behavior`

**Interfaces:**
- Produces: docs that describe the actual feedback contract, candidate list, message limit, artifact name, and opt-in run logging.

- [ ] **Step 1: Write the failing test**

```python
def test_architecture_docs_do_not_describe_unimplemented_behavior() -> None:
    architecture = _doc("docs/ARCHITECTURE.md")
    for stale in (
        "deduplication.py",
        "HistGradientBoosting",
        "RandomForest",
        "max_length=1600",
        "sms_spam_model.joblib",
        "masked text, confidence, consent",
        "Generate candidate retraining batch",
    ):
        assert stale not in architecture, f"stale architecture claim: {stale}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repo_hygiene.py::test_architecture_docs_do_not_describe_unimplemented_behavior -q`
Expected: FAIL on the first stale claim.

- [ ] **Step 3: Rewrite the stale sections**

Update `docs/ARCHITECTURE.md` to say:
- deduplication lives in `src/data.py` / `src/dataset_loading.py`;
- candidates are LogisticRegression, LinearSVC, SGDClassifier, and a MultinomialNB baseline;
- the message limit is 10,000 characters (configurable via `SMSD_MAX_MESSAGE_LENGTH`);
- the default artifact is `models/spam_detector_v1.pkl`;
- `/feedback` accepts labels, category, and model version only, never text or confidence;
- `src/active_learning.py` triages aggregate reports and never generates training CSVs;
- run logs are written only with `--track-run`.

Update `README.md` to name the current benchmark report or remove the stale
"latest" commit claim. Update `docs/IMPROVEMENT_EXECUTION.md` with the current
test count and date, or mark the older numbers as historical.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_repo_hygiene.py::test_architecture_docs_do_not_describe_unimplemented_behavior -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/ARCHITECTURE.md README.md docs/IMPROVEMENT_EXECUTION.md tests/test_repo_hygiene.py
git commit -m "docs: align architecture claims with runtime behavior"
```

### Task 3: Production requires a verified model sidecar hash

**Files:**
- Modify: `src/predict.py`
- Test: `tests/test_model.py::test_production_requires_verified_model_sidecar`

**Interfaces:**
- Consumes: `verify_artifact_sidecar(..., require_hash=...)`.
- Produces: `load_model` rejects a missing sidecar hash when `SMSD_ENV=production`.

- [ ] **Step 1: Write the failing test**

```python
def test_production_requires_verified_model_sidecar(tmp_path, monkeypatch):
    path = tmp_path / "model.pkl"
    joblib.dump({"artifact_schema_version": 2, "model": object()}, path)
    monkeypatch.setenv("SMSD_ENV", "production")
    with pytest.raises(ModelArtifactError, match="sidecar"):
        load_model(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_model.py::test_production_requires_verified_model_sidecar -q`
Expected: FAIL because the missing sidecar only produces a warning.

- [ ] **Step 3: Make production require the sidecar hash**

In `load_model`, require a hash when the environment is production:
```python
require_hash = bool(metadata_path_value) or os.environ.get("SMSD_ENV", "").strip().lower() == "production"
```
Pass that value to `verify_artifact_sidecar`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_model.py::test_production_requires_verified_model_sidecar -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/predict.py tests/test_model.py
git commit -m "security: require a verified model sidecar in production"
```

### Task 4: Fix the threshold-selection docstring

**Files:**
- Modify: `src/metrics.py`

- [ ] **Step 1: Update the docstring**

Replace "choose the lowest threshold" with "choose the best precision-weighted
F0.5 among thresholds that meet the target".

- [ ] **Step 2: Run the metrics tests**

Run: `python -m pytest tests/test_metrics.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/metrics.py
git commit -m "docs: correct threshold selection description"
```

## Sprint 2 — Tests, feedback workflow, and CI

### Task 5: Wire feedback triage into developer workflows

**Files:**
- Modify: `Makefile`
- Modify: `pyproject.toml`
- Test: `tests/test_repo_hygiene.py::test_feedback_targets_are_wired`

**Interfaces:**
- Produces: `make feedback-summary`, `make triage-feedback`, and `smsd-feedback` / `smsd-triage` entry points.

- [ ] **Step 1: Write the failing test**

```python
def test_feedback_targets_are_wired() -> None:
    makefile = _text("Makefile")
    assert "feedback-summary:" in makefile
    assert "triage-feedback:" in makefile
    pyproject = _text("pyproject.toml")
    assert 'smsd-feedback = "src.feedback:_main"' in pyproject
    assert 'smsd-triage = "src.active_learning:main"' in pyproject
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repo_hygiene.py::test_feedback_targets_are_wired -q`
Expected: FAIL.

- [ ] **Step 3: Add the targets and entry points**

Add Makefile targets that run `python -m src.feedback` and
`python -m src.active_learning` with an optional `PATH` variable. Add the
two `[project.scripts]` entries.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_repo_hygiene.py::test_feedback_targets_are_wired -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Makefile pyproject.toml tests/test_repo_hygiene.py
git commit -m "feat: expose feedback triage workflows"
```

### Task 6: Add CI security and dependency checks

**Files:**
- Create: `.github/dependabot.yml`
- Create: `.github/workflows/security.yml`
- Modify: `tests/test_repo_hygiene.py`

**Interfaces:**
- Produces: scheduled and pull-request dependency/security checks without repository secrets.

- [ ] **Step 1: Write the failing test**

```python
def test_security_workflow_and_dependabot_exist() -> None:
    workflow = _text(".github/workflows/security.yml")
    assert "pip-audit" in workflow
    assert "permissions:" in workflow
    assert "contents: read" in workflow
    dependabot = _text(".github/dependabot.yml")
    assert "pip" in dependabot and "npm" in dependabot
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repo_hygiene.py::test_security_workflow_and_dependabot_exist -q`
Expected: FAIL.

- [ ] **Step 3: Add the workflow and Dependabot config**

Create a least-privilege security workflow that installs dependencies and runs
`python -m pip_audit -r requirements.txt` plus `npm audit --omit=dev`.
Add weekly Dependabot updates for pip and npm.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_repo_hygiene.py::test_security_workflow_and_dependabot_exist -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/dependabot.yml .github/workflows/security.yml tests/test_repo_hygiene.py
git commit -m "ci: add dependency and security checks"
```

### Task 7: Add a performance budget check

**Files:**
- Create: `scripts/check_performance_budget.py`
- Test: `tests/test_performance_benchmark.py::test_performance_budget_rejects_slow_p95`

**Interfaces:**
- Produces: `check_budget(result: dict, *, max_p95_ms: float, max_load_ms: float) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
def test_performance_budget_rejects_slow_p95():
    from scripts.check_performance_budget import check_budget

    result = {"model_load": {"load_time_ms": 100.0}, "single_prediction_latency_ms": {"p95": 50.0}}
    assert check_budget(result, max_p95_ms=25.0, max_load_ms=500.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_performance_benchmark.py::test_performance_budget_rejects_slow_p95 -q`
Expected: FAIL with an import error.

- [ ] **Step 3: Implement the checker**

Read the benchmark JSON, compare p95 and load time, print failures, and exit 1
when a budget is exceeded. Use generous defaults suitable for CI.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_performance_benchmark.py::test_performance_budget_rejects_slow_p95 -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_performance_budget.py tests/test_performance_benchmark.py
git commit -m "test: add an inference performance budget"
```

### Task 8: Raise the coverage floor

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_repo_hygiene.py`

- [ ] **Step 1: Update the expected floor in the repo hygiene test**

Change the expected `--cov-fail-under` value from 78 to 82.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_repo_hygiene.py::test_pyproject_configures_pytest_ruff_and_mypy -q`
Expected: FAIL because pyproject still says 78.

- [ ] **Step 3: Raise the floor**

Set `--cov-fail-under=82` in `pyproject.toml`.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS with coverage at or above 82%.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_repo_hygiene.py
git commit -m "test: raise the coverage ratchet to 82 percent"
```

## Sprint 3 — Operations

### Task 9: Configure the drift monitor from the artifact

**Files:**
- Modify: `src/train.py`
- Modify: `api/main.py`
- Test: `tests/test_api.py::test_model_load_configures_monitor_baseline`

**Interfaces:**
- Produces: artifact key `monitor_baseline_scores` (list of floats) and a
  `configure_monitor(bundle)` helper in `api.main`.

- [ ] **Step 1: Write the failing test**

```python
def test_model_load_configures_monitor_baseline(monkeypatch, bundle):
    from src.monitor import default_monitor

    default_monitor.clear()
    bundle.metadata["monitor_baseline_scores"] = [0.1, 0.2, 0.3, 0.4, 0.5]
    api_main._model = None
    monkeypatch.setattr(api_main, "load_model", lambda: bundle)
    api_main.get_model()
    metrics = default_monitor.get_metrics()
    assert metrics["baseline_samples"] == 5
    default_monitor.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py::test_model_load_configures_monitor_baseline -q`
Expected: FAIL because the monitor is never configured.

- [ ] **Step 3: Store and load the baseline**

In `src/train.py`, add
`"monitor_baseline_scores": [round(float(value), 6) for value in val_probabilities[:1000]]`
to the artifact. In `api/main.py`, import `default_monitor`, add
`configure_monitor(bundle)`, and call it after a successful `load_model`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api.py::test_model_load_configures_monitor_baseline -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/train.py api/main.py tests/test_api.py
git commit -m "feat: configure drift monitoring from the model artifact"
```

### Task 10: Add a token-gated model reload

**Files:**
- Modify: `api/main.py`
- Modify: `api/routes.py`
- Test: `tests/test_api.py::test_admin_reload_requires_token_and_swaps_model`

**Interfaces:**
- Produces: `POST /admin/reload-model` requiring `X-SMSD-Admin-Token`.
- Produces: `api.main.reload_model() -> str`.

- [ ] **Step 1: Write the failing test**

```python
def test_admin_reload_requires_token_and_swaps_model(client, monkeypatch):
    monkeypatch.setattr(api_main, "ADMIN_TOKEN", "secret")
    assert client.post("/admin/reload-model").status_code == 404
    monkeypatch.setattr(api_main, "reload_model", lambda: "test-bundle-1.0")
    response = client.post("/admin/reload-model", headers={"X-SMSD-Admin-Token": "secret"})
    assert response.status_code == 200
    assert response.json()["model_version"] == "test-bundle-1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py::test_admin_reload_requires_token_and_swaps_model -q`
Expected: FAIL because the route does not exist.

- [ ] **Step 3: Implement reload**

Add `ADMIN_TOKEN = os.environ.get("SMSD_ADMIN_TOKEN", "").strip()`, a
`reload_model()` function that loads into a temporary variable and swaps
`_model` under `_model_lock`, and the token-gated route. Return 404 when the
token is unset or wrong, 503 on load failure.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api.py::test_admin_reload_requires_token_and_swaps_model -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/main.py api/routes.py tests/test_api.py
git commit -m "feat: add token-gated model reload"
```

### Task 11: Add Prometheus-format operations metrics

**Files:**
- Modify: `api/routes.py`
- Test: `tests/test_api.py::test_prometheus_metrics_are_content_free`

**Interfaces:**
- Produces: `GET /metrics` as `text/plain` with fixed metric names.

- [ ] **Step 1: Write the failing test**

```python
def test_prometheus_metrics_are_content_free(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "smsd_requests_total" in body
    assert "smsd_latency_p95_ms" in body
    assert "message" not in body.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py::test_prometheus_metrics_are_content_free -q`
Expected: FAIL with 404.

- [ ] **Step 3: Implement the endpoint**

Build the text format from `operations_monitor.snapshot()` and
`default_monitor.get_metrics()`. Use only fixed names and numeric values.
Apply `_authorize_metrics` in production.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api.py::test_prometheus_metrics_are_content_free -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routes.py tests/test_api.py
git commit -m "feat: expose content-free Prometheus metrics"
```

### Task 12: Support a trusted reverse proxy for client identity

**Files:**
- Modify: `api/main.py`
- Test: `tests/test_api.py::test_trusted_proxy_uses_forwarded_client_identity`

**Interfaces:**
- Produces: `SMSD_TRUSTED_PROXIES` (comma-separated CIDRs) and
  `_client_ip(scope)` that uses the first forwarded address only from a trusted peer.

- [ ] **Step 1: Write the failing test**

```python
def test_trusted_proxy_uses_forwarded_client_identity(monkeypatch):
    monkeypatch.setattr(api_main, "TRUSTED_PROXIES", (ipaddress.ip_network("127.0.0.1/32"),))
    scope = {"client": ("127.0.0.1", 1234), "headers": [(b"x-forwarded-for", b"203.0.113.9, 127.0.0.1")]}
    assert api_main._client_ip(scope) == "203.0.113.9"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py::test_trusted_proxy_uses_forwarded_client_identity -q`
Expected: FAIL because `TRUSTED_PROXIES` does not exist.

- [ ] **Step 3: Implement trusted-proxy parsing**

Parse the env var at import time, validate CIDRs, and only trust the header
when the direct peer is in the trusted set. Fall back to the direct peer.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api.py::test_trusted_proxy_uses_forwarded_client_identity -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_api.py
git commit -m "feat: support trusted reverse-proxy client identity"
```

### Task 13: Harden the container defaults

**Files:**
- Modify: `docker-compose.yml`
- Modify: `tests/test_repo_hygiene.py`

- [ ] **Step 1: Write the failing test**

```python
def test_compose_hardening() -> None:
    compose = _text("docker-compose.yml")
    assert "pids_limit:" in compose
    assert "read_only: true" in compose
    assert "tmpfs:" in compose
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repo_hygiene.py::test_compose_hardening -q`
Expected: FAIL.

- [ ] **Step 3: Add the hardening settings**

Add `pids_limit: 256`, `read_only: true`, and a writable `/tmp` tmpfs to the
API service. Add a writable donations volume if donations are enabled.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_repo_hygiene.py::test_compose_hardening -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml tests/test_repo_hygiene.py
git commit -m "security: harden container defaults"
```

## Sprint 4 — Frontend

### Task 14: Enforce i18n key parity

**Files:**
- Test: `tests/test_web_contract.py::test_i18n_languages_have_the_same_keys`

- [ ] **Step 1: Write the failing test**

Parse the `I18N` object from `api/web/i18n.js` with a small Node script or
regex and assert `set(I18N.en) == set(I18N.taglish)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web_contract.py::test_i18n_languages_have_the_same_keys -q`
Expected: FAIL if any key is missing.

- [ ] **Step 3: Add missing keys or fix the test parser**

Use the existing web-contract test helpers to read the module.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web_contract.py::test_i18n_languages_have_the_same_keys -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_web_contract.py api/web/i18n.js
git commit -m "test: enforce i18n key parity"
```

### Task 15: Add an axe-core accessibility smoke check

**Files:**
- Modify: `package.json`
- Modify: `tests/browser_smoke.cjs`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add the dependency**

Add `@axe-core/playwright` to devDependencies and install it.

- [ ] **Step 2: Write the failing check**

In the browser smoke test, run `AxeBuilder` against the loaded page and fail on
serious or critical violations.

- [ ] **Step 3: Run the browser test**

Run: `npm run test:browser`
Expected: PASS or reveal real violations to fix.

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json tests/browser_smoke.cjs .github/workflows/ci.yml
git commit -m "test: add axe-core accessibility smoke check"
```

### Task 16: Add JavaScript linting

**Files:**
- Create: `eslint.config.js`
- Modify: `package.json`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_repo_hygiene.py`

- [ ] **Step 1: Write the failing test**

Assert `package.json` has a `lint:js` script and `eslint.config.js` exists.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repo_hygiene.py::test_javascript_lint_is_wired -q`
Expected: FAIL.

- [ ] **Step 3: Add ESLint**

Add `eslint` to devDependencies, a flat config for browser ES modules, and run
it in CI after `npm ci`.

- [ ] **Step 4: Run the check**

Run: `npm run lint:js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eslint.config.js package.json package-lock.json .github/workflows/ci.yml tests/test_repo_hygiene.py
git commit -m "test: add JavaScript linting"
```

## Sprint 5 — Evaluation tooling

### Task 17: Add a message-free error-analysis tool

**Files:**
- Create: `src/error_analysis.py`
- Test: `tests/test_error_analysis.py`

**Interfaces:**
- Produces: `analyze_errors(frame, probabilities, threshold, *, group_columns) -> dict`
  with counts by category, language, and error type, plus redacted examples.

- [ ] **Step 1: Write the failing test**

```python
def test_error_analysis_counts_and_redacts():
    from src.error_analysis import analyze_errors

    frame = pd.DataFrame(
        {
            "label": ["ham", "spam", "ham", "spam"],
            "category": ["otp", "prize", "otp", "prize"],
            "language": ["english", "taglish", "english", "taglish"],
            "message": ["OTP 123456", "Win 1000", "OTP 654321", "Win 2000"],
        }
    )
    result = analyze_errors(frame, [0.9, 0.8, 0.1, 0.2], 0.5)
    assert result["false_positives"] == 1
    assert result["false_negatives"] == 1
    assert "123456" not in json.dumps(result)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_error_analysis.py::test_error_analysis_counts_and_redacts -q`
Expected: FAIL with an import error.

- [ ] **Step 3: Implement the analyzer**

Use `src.preprocess.redact_message` for examples. Return aggregate counts and
redacted snippets only. Add a CLI that reads a CSV and writes JSON.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_error_analysis.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/error_analysis.py tests/test_error_analysis.py
git commit -m "feat: add message-free error analysis"
```

### Task 18: Add a synthetic hard-negative challenge set

**Files:**
- Create: `data/raw/ph_hard_negatives.csv`
- Test: `tests/test_synthetic_ph.py::test_hard_negatives_are_synthetic_and_labeled`

- [ ] **Step 1: Write the failing test**

Assert the CSV exists, has `label,message,category,language,group`, contains
only `ham` rows for OTP/bank/delivery/personal categories, and uses reserved
example domains or masked values.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthetic_ph.py::test_hard_negatives_are_synthetic_and_labeled -q`
Expected: FAIL because the file is missing.

- [ ] **Step 3: Create the fixture**

Add 20-30 clearly synthetic legitimate messages covering OTP, bank alerts,
delivery notices, bills, promotions, and personal Taglish. Use `[CODE]`,
`[AMOUNT]`, `example.com`, and fictional senders. Mark `data_kind=synthetic`
if the schema supports it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synthetic_ph.py::test_hard_negatives_are_synthetic_and_labeled -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data/raw/ph_hard_negatives.csv tests/test_synthetic_ph.py
git commit -m "test: add synthetic hard-negative challenge set"
```

### Task 19: Add a repeated group-aware CV report

**Files:**
- Create: `scripts/repeated_cv_report.py`
- Test: `tests/test_model_selection.py::test_repeated_cv_report_is_deterministic`

- [ ] **Step 1: Write the failing test**

Assert the report runs two seeds on a tiny dataset and returns stable keys:
`seeds`, `f1_mean`, `f1_std`, `fold_scores`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_model_selection.py::test_repeated_cv_report_is_deterministic -q`
Expected: FAIL with an import error.

- [ ] **Step 3: Implement the report**

Reuse `src.model_selection.select_classifier` and `cv_splits`. Emit JSON only;
no message text.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_model_selection.py::test_repeated_cv_report_is_deterministic -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/repeated_cv_report.py tests/test_model_selection.py
git commit -m "feat: add repeated group-aware CV report"
```
