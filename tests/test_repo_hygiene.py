"""Repository hygiene checks for deployment, dependencies, CI, docs, and secrets.

Fast and deterministic: no training, no network, no base data, and no model
artifact are required. These tests verify that the files added alongside the
model/service stay consistent with each other (bounded dependencies, non-root
container, CI quality gates, no committed secrets) and that the documentation
keeps the synthetic-only evidence caveat.

They intentionally do not assert on measured metrics or on README content: the
Lead owns the README and its numbers change whenever the artifact is retrained.
"""

from __future__ import annotations

import fnmatch
import re
import tomllib
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "Dockerfile",
    ".dockerignore",
    "docker-compose.yml",
    "Makefile",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "constraints.txt",
    ".github/workflows/ci.yml",
    "docs/README.md",
    "docs/DATA_COLLECTION.md",
    "docs/DATASET_INVENTORY.md",
    "docs/DEPLOYMENT.md",
    "docs/MODEL_CARD.md",
    "docs/RETRAINING.md",
    "docs/PRIVACY.md",
    "docs/HUMAN_REVIEW.md",
    "tests/test_repo_hygiene.py",
]

MAKEFILE_TARGETS = [
    "install",
    "dev-install",
    "test",
    "lint",
    "format",
    "typecheck",
    "train",
    "evaluate",
    "serve",
    "docker-build",
    "docker-run",
    "clean",
]

SECRET_PATTERNS = {
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
}

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".cfg",
    ".ini",
    ".sh",
    ".html",
    ".css",
    ".js",
}
TEXT_NAMES = {"Dockerfile", "Makefile", ".dockerignore", ".gitignore"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "models",
    "data",
    "notebooks",
    ".zwork",
    "htmlcov",
}


def _doc(relative_path: str) -> str:
    """Read a Markdown doc with line-wrapping normalized to single spaces."""
    return " ".join(_text(relative_path).split())


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8", errors="replace")


def _requirement_specs(relative_path: str) -> dict[str, str]:
    """Map package name -> version specifier string for a requirements file."""
    specs: dict[str, str] = {}
    for raw in _text(relative_path).splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?\s*(?P<specs>.*)$", line)
        assert match, f"{relative_path}: unparseable requirement line: {raw!r}"
        specs[match.group("name").lower()] = match.group("specs").strip()
    return specs


def _gitignore_lines() -> list[str]:
    return [
        line.strip() for line in _text(".gitignore").splitlines() if line.strip() and not line.strip().startswith("#")
    ]


def _is_git_ignored(relative_path: str) -> bool:
    rel = relative_path.replace("\\", "/")
    basename = Path(rel).name
    ignored = False
    for raw_pattern in _gitignore_lines():
        negated = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negated else raw_pattern
        pattern = pattern.rstrip("/")
        matches = fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(basename, pattern)
        matches = matches or ("/" not in pattern and (rel == pattern or rel.startswith(pattern + "/")))
        if matches:
            ignored = not negated
    return ignored


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            files.append(path)
    return files


@pytest.mark.parametrize("relative_path", REQUIRED_FILES)
def test_required_files_exist(relative_path: str) -> None:
    path = ROOT / relative_path
    assert path.is_file(), f"required file is missing: {relative_path}"
    assert path.stat().st_size > 0, f"required file is empty: {relative_path}"


def test_requirements_are_bounded() -> None:
    runtime = _requirement_specs("requirements.txt")
    expected = {
        "numpy",
        "pandas",
        "scikit-learn",
        "joblib",
        "fastapi",
        "uvicorn",
        "pydantic",
        "matplotlib",
    }
    assert expected <= set(runtime), f"missing runtime dependencies: {sorted(expected - set(runtime))}"
    for name, specs in runtime.items():
        assert ">=" in specs, f"{name} needs a lower bound in requirements.txt: {specs!r}"
        assert "<" in specs, f"{name} needs an upper bound in requirements.txt: {specs!r}"

    dev = _requirement_specs("requirements-dev.txt")
    assert {"ruff", "mypy", "pytest", "httpx"} <= set(dev)
    for name, specs in dev.items():
        assert ">=" in specs and "<" in specs, f"{name} must be bounded in requirements-dev.txt: {specs!r}"


def test_constraints_match_bounded_ranges() -> None:
    constraints_text = _text("constraints.txt")
    assert "pip freeze" in constraints_text
    assert "3.13" in constraints_text, "constraints.txt must state it is the tester's Python 3.13 environment"

    pins: dict[str, str] = {}
    for raw in constraints_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        assert "==" in line, f"constraints.txt should contain exact == pins, got {raw!r}"
        name, version = line.split("==", 1)
        pins[name.strip().lower()] = version.strip()

    assert len(pins) >= 20, "constraints.txt looks incomplete for a full pip freeze"
    for name, specs in _requirement_specs("requirements.txt").items():
        assert name in pins, f"constraints.txt is missing the {name} pin"
        assert Version(pins[name]) in SpecifierSet(specs), (
            f"pinned {name}=={pins[name]} does not satisfy requirements.txt range {specs!r}"
        )


def test_pyproject_configures_pytest_ruff_and_mypy() -> None:
    config = tomllib.loads(_text("pyproject.toml"))

    project = config["project"]
    assert project["requires-python"] == ">=3.11"
    assert str(project["version"])

    pytest_options = config["tool"]["pytest"]["ini_options"]
    assert pytest_options["testpaths"] == ["tests"]
    assert pytest_options["addopts"] == "-ra"

    ruff = config["tool"]["ruff"]
    assert ruff["target-version"] == "py311"
    assert ruff["line-length"] == 120
    selected = set(ruff["lint"]["select"])
    assert {"E", "F", "I", "UP", "B", "SIM"} <= selected
    assert ruff["lint"]["isort"]["known-first-party"] == ["src", "api"]

    mypy = config["tool"]["mypy"]
    assert mypy["python_version"] == "3.11"
    assert mypy["files"] == ["src", "api"]
    assert mypy["ignore_missing_imports"] is True
    assert mypy["warn_unused_ignores"] is True


def test_dockerfile_is_nonroot_and_has_stdlib_healthcheck() -> None:
    dockerfile = _text("Dockerfile")

    # Pinned slim runtime base (the ARG is overridable, default 3.12).
    assert re.search(r"(?m)^ARG PYTHON_VERSION=3\.12$", dockerfile)
    assert re.search(r"(?m)^FROM python:\$\{PYTHON_VERSION\}-slim", dockerfile)

    users = re.findall(r"(?m)^USER\s+(\S+)", dockerfile)
    assert users, "Dockerfile must switch to a non-root USER"
    assert users[-1] not in {"root", "0", "0:0"}, f"final USER is root: {users[-1]}"
    assert not users[-1].startswith("root")

    assert re.search(r"(?m)^HEALTHCHECK\b", dockerfile)
    assert "/health" in dockerfile
    assert "urllib.request" in dockerfile, "healthcheck must use the Python stdlib (curl is absent in slim)"
    assert "EXPOSE 8000" in dockerfile
    assert "uvicorn" in dockerfile and "api.main:app" in dockerfile
    assert "org.opencontainers.image.title" in dockerfile

    # The artifact/data must never be copied into the image; they are mounted.
    copy_lines = [line for line in dockerfile.splitlines() if line.strip().upper().startswith("COPY")]
    for line in copy_lines:
        assert "models/" not in line and " data/" not in line, f"artifact/data copied into image: {line!r}"


def test_dockerignore_excludes_data_models_and_secrets() -> None:
    entries = [
        line.strip()
        for line in _text(".dockerignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for expected in (".git", ".venv", "data/", "models/", ".env"):
        assert expected in entries, f".dockerignore must exclude {expected}"
    assert "*.pkl" in entries
    assert "*.joblib" in entries


def test_compose_mounts_model_read_only_and_sets_env() -> None:
    compose = _text("docker-compose.yml")
    assert "8000" in compose
    assert "./models:/app/models:ro" in compose
    assert "SMSD_MODEL_PATH" in compose
    assert "SMSD_CORS_ORIGINS" in compose
    assert "healthcheck:" in compose
    assert "restart:" in compose
    assert "cap_drop:" in compose
    assert "no-new-privileges" in compose


def test_ci_runs_quality_gates_on_supported_versions() -> None:
    workflow = _text(".github/workflows/ci.yml")
    assert '"3.11"' in workflow and '"3.12"' in workflow
    assert "matrix:" in workflow
    assert "pip install -r requirements.txt -r requirements-dev.txt" in workflow
    assert "ruff check ." in workflow
    assert "ruff format --check ." in workflow
    assert "mypy src api" in workflow
    assert "pytest -q" in workflow
    assert "docker build" in workflow and "deployment-smoke" in workflow
    assert "permissions:" in workflow and "contents: read" in workflow
    assert "secrets." not in workflow, "CI must not reference repository secrets"


def test_makefile_phony_and_targets() -> None:
    makefile = _text("Makefile")
    phony_lines = [line for line in makefile.splitlines() if line.startswith(".PHONY:")]
    assert phony_lines, "Makefile needs a .PHONY declaration"
    phony = set(phony_lines[0].replace(".PHONY:", "").split())
    assert set(MAKEFILE_TARGETS) <= phony, f"missing .PHONY targets: {sorted(set(MAKEFILE_TARGETS) - phony)}"
    for target in MAKEFILE_TARGETS:
        assert re.search(rf"(?m)^{re.escape(target)}:", makefile), f"Makefile target missing: {target}"


def test_gitignore_keeps_docs_tests_tracked_and_artifacts_ignored() -> None:
    gitignore = _text(".gitignore")
    assert "models/*.pkl" in gitignore
    assert "models/*.joblib" in gitignore
    assert "data/raw/*" in gitignore
    assert ".env" in gitignore

    for path in ("docs/README.md", "docs/DEPLOYMENT.md", "tests/test_repo_hygiene.py", "tests/test_api.py"):
        assert not _is_git_ignored(path), f".gitignore unexpectedly ignores {path}"
    for path in (
        "models/spam_detector_v1.pkl",
        "models/spam_detector_v1.joblib",
        "data/raw/spam.csv",
        "data/feedback/reports.jsonl",
        ".env",
    ):
        assert _is_git_ignored(path), f".gitignore should ignore {path}"
    assert not _is_git_ignored("data/templates/consented_ph_sms_template.csv")
    assert not _is_git_ignored("data/raw/ph_supplement_4.csv")
    assert not _is_git_ignored("data/raw/ph_supplement_5.csv")


def test_required_docs_are_present_and_linked_from_index() -> None:
    index = _text("docs/README.md")
    for relative_path in REQUIRED_FILES:
        if not relative_path.startswith("docs/") or relative_path == "docs/README.md":
            continue
        doc_name = Path(relative_path).name
        assert relative_path in REQUIRED_FILES
        assert doc_name in index, f"docs/README.md does not link {doc_name}"
        assert len(_text(relative_path)) > 500, f"{relative_path} looks empty"


def test_docs_state_synthetic_only_and_privacy_limits() -> None:
    data = _doc("docs/DATA_COLLECTION.md").lower()
    assert "synthetic" in data
    assert "consent" in data
    assert "mask" in data
    assert re.search(r"no\W+representative\W+real\W+philippine", data)

    model_card = _doc("docs/MODEL_CARD.md").lower()
    assert "synthetic" in model_card
    assert "no real philippine traffic has been evaluated" in model_card
    assert "assistive" in model_card
    assert re.search(r"no\W+representative\W+real\W+philippine", model_card)
    assert "dataset_inventory.md" in model_card, "model card metrics source must link the dated evaluation inventory"

    privacy = _doc("docs/PRIVACY.md").lower()
    assert "no server-side message persistence" in privacy
    assert "localstorage" in privacy
    assert "opt-in" in privacy

    deployment = _doc("docs/DEPLOYMENT.md")
    assert "SMSD_MODEL_PATH" in deployment
    assert "SMSD_CORS_ORIGINS" in deployment
    assert "HEALTHCHECK" in deployment
    assert "TLS" in deployment
    assert "rollback" in deployment.lower()

    retraining = _doc("docs/RETRAINING.md").lower()
    assert "rollback" in retraining
    assert "holdout" in retraining
    assert "monitor" in retraining


def test_no_obvious_secrets_committed() -> None:
    findings: list[str] = []
    for path in _iter_text_files():
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{path.relative_to(ROOT)}: possible {label}")
    assert not findings, "possible secrets committed:\n" + "\n".join(findings)
