"""Operations-baseline checks in scripts/doctor.py, with synthetic payloads only.

doctor.check_operations_baseline() must report the optional local API's
content-free operations telemetry (/metrics/operations), the monitor's drift
status and score summary (/metrics/distribution), and the served model_version
against the expected artifact sidecar: WARN (never FAIL) when the service is
unreachable, OK when operations respond and the served version matches the
sidecar, WARN with measured values on disagreement or an unexpected drift
status, and never print message text or sender data.

The FIXTURE_* strings below are tracked synthetic fixtures (nothing real);
they are planted inside otherwise content-free payloads exactly so the
message-free assertions can prove the doctor never echoes payload fields.
"""

from __future__ import annotations

import copy
import importlib
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from scripts import doctor

BASE = "http://doctor-fixtures.test:8000"

# Synthetic fixture strings only: no digits-plus-domains, no senders, nothing real.
FIXTURE_MESSAGE = "Synthetic doctor fixture alpha: unsolicited prize claim template for output-hygiene assertions only."
FIXTURE_SENDER = "synthetic_doctor_sender_alpha"
FORBIDDEN_VALUES = (FIXTURE_MESSAGE, FIXTURE_SENDER)

RELEASE_VERSION = "spam_detector_v1-2026-11-28"
DEMO_VERSION = "synthetic-demo"

OPERATIONS_SNAPSHOT: dict[str, Any] = {
    "scope": "one_process_since_start",
    "request_count": 930,
    "status_classes": {"2xx": 592, "4xx": 336, "5xx": 2},
    "route_groups": {"status": 362, "prediction": 16},
    "latency_window_samples": 512,
    "latency_p50_ms": 4.18,
    "latency_p95_ms": 25.63,
    # A payload field the doctor must never echo, even if a future endpoint carried it.
    "operator_notes": FIXTURE_MESSAGE,
}

SCORE_SUMMARY: dict[str, Any] = {
    "count": 120,
    "mean": 0.2314,
    "std": 0.3102,
    "min": 0.0,
    "max": 0.9812,
    "percentiles": {"p10": 0.0012, "p25": 0.0104, "p50": 0.0481, "p75": 0.4013, "p90": 0.8125, "p99": 0.9688},
}

DISTRIBUTION_SNAPSHOT: dict[str, Any] = {
    "window_size": 1000,
    "samples_in_window": 120,
    "spam_ratio": 0.25,
    "score_distribution": SCORE_SUMMARY,
    "baseline_status": "configured",
    "baseline_model_version": RELEASE_VERSION,
    "baseline_source_kind": "synthetic_diagnostic",
    "baseline_samples": 264,
    "drift": {
        "psi": 0.0,
        "drift_status": "insufficient_data",
        "ks_statistic": 0.0,
        "ks_pvalue": 1.0,
        "ks_drift_detected": False,
    },
    # Another never-echo field carrying fixture text and a synthetic sender value.
    "recent_examples": [FIXTURE_MESSAGE],
    "recent_senders": [FIXTURE_SENDER],
}

MODEL_INFO_SNAPSHOT: dict[str, Any] = {
    "model_version": RELEASE_VERSION,
    "probability_calibrated": True,
    "decision_threshold": 0.5,
    "flags": [],
}


@pytest.fixture(autouse=True)
def _hermetic_doctor(monkeypatch):
    """Point every doctor fetch at the fixture base and isolate its ledgers."""
    monkeypatch.setattr(doctor, "OPERATIONS_API_BASE", BASE)
    monkeypatch.setattr(doctor, "WARNINGS", [])
    monkeypatch.setattr(doctor, "FAILURES", [])


def _patch_endpoints(
    monkeypatch,
    *,
    operations: dict[str, Any] | None = OPERATIONS_SNAPSHOT,
    distribution: dict[str, Any] | None = DISTRIBUTION_SNAPSHOT,
    model_info: dict[str, Any] | None = MODEL_INFO_SNAPSHOT,
    unreachable: bool = False,
) -> None:
    """Replace doctor._fetch_json with synthetic payloads or a refused connection."""
    if unreachable:

        def fetch(url: str) -> Any:
            raise urllib.error.URLError("connection refused")

    else:
        payloads = {
            f"{BASE}/metrics/operations": operations,
            f"{BASE}/metrics/distribution": distribution,
            f"{BASE}/model-info": model_info,
        }

        def fetch(url: str) -> Any:
            if url not in payloads:
                raise AssertionError(f"unexpected doctor fetch: {url}")
            return payloads[url]

    monkeypatch.setattr(doctor, "_fetch_json", fetch)


def _point_sidecar(monkeypatch, tmp_path: Path, version: str | None) -> None:
    """Set SMSD_MODEL_PATH to a tmp artifact and optionally write its sidecar."""
    monkeypatch.setenv("SMSD_MODEL_PATH", str(tmp_path / "spam_detector_v1.pkl"))
    if version is not None:
        sidecar = tmp_path / "spam_detector_v1.metadata.json"
        sidecar.write_text(json.dumps({"model_version": version}), encoding="utf-8")


def test_unreachable_endpoint_is_warn_not_fail(monkeypatch, capsys) -> None:
    _patch_endpoints(monkeypatch, unreachable=True)
    doctor.check_operations_baseline()
    assert doctor.FAILURES == []
    assert doctor.WARNINGS == ["ops-baseline"]
    out = capsys.readouterr().out
    assert "WARN  ops-baseline" in out
    assert f"no local API answering at {BASE}" in out


@pytest.mark.parametrize("drift_status", ["insufficient_data", "stable"])
def test_reachable_and_matching_sidecar_reports_ok(monkeypatch, capsys, tmp_path, drift_status: str) -> None:
    _point_sidecar(monkeypatch, tmp_path, RELEASE_VERSION)
    distribution = copy.deepcopy(DISTRIBUTION_SNAPSHOT)
    distribution["drift"]["drift_status"] = drift_status
    _patch_endpoints(monkeypatch, distribution=distribution)
    doctor.check_operations_baseline()
    assert doctor.FAILURES == []
    assert doctor.WARNINGS == []
    out = capsys.readouterr().out
    assert "OK    ops-metrics" in out and "request_count=930" in out
    assert "OK    ops-drift" in out and f"drift_status='{drift_status}'" in out
    assert "OK    ops-served-version" in out and f"{RELEASE_VERSION!r}" in out


def test_served_version_mismatch_warns_with_measured_values(monkeypatch, capsys, tmp_path) -> None:
    _point_sidecar(monkeypatch, tmp_path, RELEASE_VERSION)
    model_info = copy.deepcopy(MODEL_INFO_SNAPSHOT)
    model_info["model_version"] = DEMO_VERSION
    _patch_endpoints(monkeypatch, model_info=model_info)
    doctor.check_operations_baseline()
    assert doctor.FAILURES == []
    assert "ops-served-version" in doctor.WARNINGS
    out = capsys.readouterr().out
    assert "WARN  ops-served-version" in out
    assert f"{DEMO_VERSION!r}" in out and f"{RELEASE_VERSION!r}" in out


def test_missing_expected_sidecar_warns_with_served_version(monkeypatch, capsys, tmp_path) -> None:
    # Today's live state: a server is up but the canonical sidecar slot is empty.
    _point_sidecar(monkeypatch, tmp_path, version=None)
    model_info = copy.deepcopy(MODEL_INFO_SNAPSHOT)
    model_info["model_version"] = DEMO_VERSION
    _patch_endpoints(monkeypatch, model_info=model_info)
    doctor.check_operations_baseline()
    assert doctor.FAILURES == []
    assert "ops-served-version" in doctor.WARNINGS
    out = capsys.readouterr().out
    assert "WARN  ops-served-version" in out
    assert f"{DEMO_VERSION!r}" in out and "missing or records none" in out


def test_no_baseline_configured_warns(monkeypatch, capsys, tmp_path) -> None:
    _point_sidecar(monkeypatch, tmp_path, RELEASE_VERSION)
    distribution = copy.deepcopy(DISTRIBUTION_SNAPSHOT)
    distribution["baseline_status"] = "not_configured"
    distribution["baseline_model_version"] = None
    distribution["baseline_source_kind"] = None
    distribution["baseline_samples"] = 0
    distribution["drift"] = {
        "psi": 0.0,
        "drift_status": "no_baseline_configured",
        "ks_statistic": 0.0,
        "ks_pvalue": 1.0,
        "ks_drift_detected": False,
    }
    _patch_endpoints(monkeypatch, distribution=distribution)
    doctor.check_operations_baseline()
    assert doctor.FAILURES == []
    assert "ops-drift" in doctor.WARNINGS
    out = capsys.readouterr().out
    assert "WARN  ops-drift" in out
    assert "drift_status=no_baseline_configured" in out
    assert "not_configured" in out
    assert "SMSD_MONITOR_BASELINE_PATH" in out


@pytest.mark.parametrize(
    ("drift_status", "psi"),
    [("moderate_drift", 0.1305), ("significant_drift", 0.2412), ("invalid_baseline", 0.0)],
)
def test_unexpected_drift_status_warns_with_measured_value(
    monkeypatch, capsys, tmp_path, drift_status: str, psi: float
) -> None:
    _point_sidecar(monkeypatch, tmp_path, RELEASE_VERSION)
    distribution = copy.deepcopy(DISTRIBUTION_SNAPSHOT)
    if drift_status == "invalid_baseline":
        distribution["baseline_status"] = "invalid_baseline"
    distribution["drift"] = {
        "psi": psi,
        "drift_status": drift_status,
        "ks_statistic": 0.0,
        "ks_pvalue": 1.0,
        "ks_drift_detected": False,
    }
    _patch_endpoints(monkeypatch, distribution=distribution)
    doctor.check_operations_baseline()
    assert doctor.FAILURES == []
    assert "ops-drift" in doctor.WARNINGS
    out = capsys.readouterr().out
    assert "WARN  ops-drift" in out
    assert f"drift_status='{drift_status}'" in out
    assert f"psi={psi}" in out


def test_doctor_stdout_stays_message_free(monkeypatch, capsys, tmp_path) -> None:
    """Full main() run: fixture message/sender values planted in payloads never leak."""
    _point_sidecar(monkeypatch, tmp_path, RELEASE_VERSION)
    model_info = copy.deepcopy(MODEL_INFO_SNAPSHOT)
    model_info["model_version"] = DEMO_VERSION
    _patch_endpoints(monkeypatch, model_info=model_info)
    for name in (
        "check_python_constraints",
        "check_git_state",
        "check_artifact_references",
        "check_served_model",
        "check_docs_index",
    ):
        monkeypatch.setattr(doctor, name, lambda: None)
    exit_code = doctor.main()
    out = capsys.readouterr().out
    assert exit_code == 0  # only warnings; the service checks are never failures
    assert "ops-baseline" not in out  # endpoints answered, so no unreachable warning
    for forbidden in FORBIDDEN_VALUES:
        assert forbidden not in out


def test_endpoint_env_override_is_read_at_import(monkeypatch) -> None:
    monkeypatch.setenv("SMSD_DOCTOR_ENDPOINT", "http://override-fixture.test:9999/")
    importlib.reload(doctor)
    assert doctor.OPERATIONS_API_BASE == "http://override-fixture.test:9999"
    monkeypatch.undo()
    importlib.reload(doctor)  # restore the module constant from the process environment
