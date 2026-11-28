#!/usr/bin/env python3
"""Repository-state doctor for the Philippine SMS spam/scam detector.

Fast (<60s), read-only checks that catch the drift this project actually
experiences: a stale checkout, untracked plan files re-appearing, dangling
model-artifact references, a served model that no metadata sidecar knows,
operations/drift telemetry from the optional local API, and docs that are not
linked from the documentation index.

Exit codes: 0 = no failures (warnings allowed), 1 = at least one failure.
Run locally with `make doctor`. It never trains, downloads, or writes. The
operations checks only read content-free telemetry endpoints and set
SMSD_DOCTOR_ENDPOINT to override the default local base URL.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OPERATIONAL_MODEL_FILES = (ROOT / "Makefile", ROOT / "docker-compose.yml", ROOT / "Dockerfile")
DOCS_INDEX = ROOT / "docs" / "README.md"
LOCAL_API = "http://127.0.0.1:8000/health"
# Opt-in override for the served-API checks; failure of the service is always
# a WARN because it is optional, never a FAIL.
OPERATIONS_API_BASE = os.environ.get("SMSD_DOCTOR_ENDPOINT", "").strip().rstrip("/") or "http://127.0.0.1:8000"
CANONICAL_MODEL_SIDECAR = ROOT / "models" / "spam_detector_v1.metadata.json"
# Drift statuses the monitor reports that need no operator attention.
DRIFT_OK_STATUSES = frozenset({"insufficient_data", "stable"})

FAILURES: list[str] = []
WARNINGS: list[str] = []


def check(name: str, ok: bool, detail: str, *, warn_only: bool = False) -> None:
    label = "OK  " if ok else ("WARN" if warn_only else "FAIL")
    print(f"{label}  {name}: {detail}" if detail else f"{label}  {name}")
    if not ok:
        (WARNINGS if warn_only else FAILURES).append(name)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def check_python_constraints() -> None:
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    constraint = ROOT / "constraints" / f"py{version}.txt"
    check(
        "python-constraints",
        constraint.is_file(),
        f"venv Python {version}; constraints/py{version}.txt {'found' if constraint.is_file() else 'MISSING'}",
    )


def check_git_state() -> None:
    try:
        behind = int(_git("rev-list", "--count", "main..origin/main") or 0)
        ahead = int(_git("rev-list", "--count", "origin/main..main") or 0)
    except subprocess.CalledProcessError:
        behind, ahead = 0, 0
        check("git-state", False, "could not compare main with origin/main", warn_only=True)
        return
    if behind:
        check(
            "git-ff",
            False,
            f"main is {behind} commit(s) behind origin/main; run: git merge --ff-only origin/main",
            warn_only=True,
        )
    else:
        check("git-ff", True, "main is up to date with origin/main")
    if ahead:
        check("git-unpushed", False, f"main has {ahead} unpushed commit(s); push when ready", warn_only=True)
    else:
        check("git-unpushed", True, "no unpushed main commits")
    untracked = [line for line in _git("status", "--porcelain").splitlines() if line.startswith("?? ")]
    # Active specs/plans live tracked under docs/superpowers/ (committed with their PR);
    # only untracked plan files are drift. Executed plans belong in docs/history/ --
    # enforced by review, not here.
    if untracked:
        check("plan-archive", False, f"untracked files present: {[line[3:] for line in untracked[:5]]}", warn_only=True)
    else:
        check("plan-archive", True, "no untracked plan files or stale directories")


REGENERATION_HINTS = (
    ("demo", "run: make demo"),
    ("train", "run: make train"),
)


def check_artifact_references() -> None:
    referenced: set[Path] = set()
    for source in OPERATIONAL_MODEL_FILES:
        for token in source.read_text(encoding="utf-8").split():
            # Globs in comments (.gitignore examples) are not concrete artifacts.
            if (
                token.startswith("models/")
                and "*" not in token
                and (token.endswith(".pkl") or token.endswith(".joblib"))
            ):
                referenced.add(ROOT / token)
    missing: list[str] = []
    for path in sorted(referenced):
        if path.exists():
            continue
        name = path.name
        hint = next(
            (command for needle, command in REGENERATION_HINTS if needle in name), "retrain or rebuild the artifact"
        )
        missing.append(f"{path.relative_to(ROOT)} ({hint})")
    if missing:
        check("artifact-refs", False, f"referenced artifacts not on disk yet: {missing}", warn_only=True)
    else:
        check("artifact-refs", True, f"all {len(referenced)} referenced model artifacts exist")


def _known_model_versions() -> set[str]:
    versions: set[str] = set()
    for metadata in ROOT.glob("models/*.metadata.json"):
        try:
            value = json.loads(metadata.read_text(encoding="utf-8")).get("model_version")
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, str) and value:
            versions.add(value)
    return versions


def check_served_model() -> None:
    try:
        with urllib.request.urlopen(LOCAL_API, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        check(
            "served-model",
            False,
            f"no local API answering at {LOCAL_API} (optional; start with make serve)",
            warn_only=True,
        )
        return
    served = payload.get("model_version") if isinstance(payload, dict) else None
    known = _known_model_versions()
    if served in known:
        check("served-model", True, f"server reports {served!r}, which has a metadata sidecar in models/")
    else:
        check(
            "served-model",
            False,
            f"server reports {served!r}, which matches no models/*.metadata.json "
            f"(known: {sorted(known) or 'none'}); rebuild via make demo or retrain",
        )


def _fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _expected_sidecar() -> Path:
    """Sidecar of the artifact the local API is expected to serve.

    ``SMSD_MODEL_PATH`` (the serving override used by docker/rollback drills)
    wins; otherwise the canonical ``make train`` output slot is expected.
    """
    override = os.environ.get("SMSD_MODEL_PATH", "").strip()
    if not override:
        return CANONICAL_MODEL_SIDECAR
    path = Path(override)
    if not path.is_absolute():
        path = ROOT / path
    return path.with_suffix(".metadata.json")


def _sidecar_model_version(sidecar: Path) -> str | None:
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8")).get("model_version")
    except (OSError, ValueError):
        return None
    return value if isinstance(value, str) and value else None


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check_operations_baseline() -> None:
    """Report the served model's content-free operations and drift signals.

    The local API is optional, so every outcome here stays warn_only. All
    reported values are monitor aggregates (counts, latencies, drift status,
    score summary) -- never message text or sender data -- and nothing is
    acted on automatically.
    """
    try:
        operations = _fetch_json(f"{OPERATIONS_API_BASE}/metrics/operations")
        distribution = _fetch_json(f"{OPERATIONS_API_BASE}/metrics/distribution")
        model_info = _fetch_json(f"{OPERATIONS_API_BASE}/model-info")
    except (OSError, ValueError):
        check(
            "ops-baseline",
            False,
            f"no local API answering at {OPERATIONS_API_BASE} (optional; start with make serve)",
            warn_only=True,
        )
        return

    snapshot = operations if isinstance(operations, dict) else {}
    check(
        "ops-metrics",
        snapshot.get("request_count") is not None,
        f"request_count={snapshot.get('request_count')} latency_p50_ms={snapshot.get('latency_p50_ms')} "
        f"latency_p95_ms={snapshot.get('latency_p95_ms')} (content-free /metrics/operations)",
        warn_only=True,
    )

    served = model_info.get("model_version") if isinstance(model_info, dict) else None
    sidecar = _expected_sidecar()
    expected = _sidecar_model_version(sidecar)
    sidecar_label = _display_path(sidecar)
    if expected is None:
        check(
            "ops-served-version",
            False,
            f"served model_version is {served!r}; expected sidecar {sidecar_label} is missing or records none",
            warn_only=True,
        )
    elif served == expected:
        check("ops-served-version", True, f"served model_version is {served!r}, matching {sidecar_label}")
    else:
        check(
            "ops-served-version",
            False,
            f"served model_version is {served!r} but the expected sidecar {sidecar_label} records {expected!r}",
            warn_only=True,
        )

    payload = distribution if isinstance(distribution, dict) else {}
    drift = payload.get("drift")
    drift = drift if isinstance(drift, dict) else {}
    summary = payload.get("score_distribution")
    summary = summary if isinstance(summary, dict) else {}
    percentiles = summary.get("percentiles")
    percentiles = percentiles if isinstance(percentiles, dict) else {}
    status = drift.get("drift_status")
    measured = (
        f"psi={drift.get('psi')} window_samples={payload.get('samples_in_window')} "
        f"score mean={summary.get('mean')} p50={percentiles.get('p50')} p90={percentiles.get('p90')}"
    )
    if status == "no_baseline_configured":
        check(
            "ops-drift",
            False,
            f"monitor reports drift_status=no_baseline_configured (baseline_status={payload.get('baseline_status')!r}; "
            f"{measured}); export a reference with python -m src.train --monitor-baseline-output <new private file> "
            "--monitor-baseline-source synthetic_diagnostic|approved_development and serve it via SMSD_MONITOR_BASELINE_PATH",
            warn_only=True,
        )
    elif status in DRIFT_OK_STATUSES:
        check("ops-drift", True, f"drift_status={status!r} ({measured})")
    else:
        check(
            "ops-drift",
            False,
            f"drift_status={status!r} reported for review ({measured}); measured values only, never auto-act",
            warn_only=True,
        )


def check_docs_index() -> None:
    if not DOCS_INDEX.is_file():
        check("docs-index", False, f"{DOCS_INDEX.relative_to(ROOT)} is missing")
        return
    index = DOCS_INDEX.read_text(encoding="utf-8")
    unlinked = sorted(
        doc.name for doc in ROOT.glob("docs/*.md") if doc.name != DOCS_INDEX.name and f"({doc.name})" not in index
    )
    if unlinked:
        check("docs-index", False, f"docs not linked from docs/README.md: {unlinked}")
    else:
        check("docs-index", True, "every docs/*.md is linked from the documentation index")


def main() -> int:
    check_python_constraints()
    check_git_state()
    check_artifact_references()
    check_served_model()
    check_operations_baseline()
    check_docs_index()
    print()
    if FAILURES:
        print(f"doctor: {len(FAILURES)} failure(s): {FAILURES}")
        return 1
    print(f"doctor: passed with {len(WARNINGS)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
