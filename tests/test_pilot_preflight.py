"""Tests for the synthetic pilot preflight (scripts/pilot_preflight.py).

The preflight must pass on generated fixtures only, fail when the donation
flow is disabled or the enforced PII rule is bypassed, and keep the report
and every log line free of message text and PII patterns.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest
from scripts.pilot_preflight import (
    DONATION_FIXTURE_MESSAGE,
    FIXTURE_MESSAGES,
    PII_FIXTURE_MESSAGE,
    PII_FIXTURE_VALUES,
    _validate_output_path,
    main,
    run_preflight,
    write_report,
)

import api.donations
import api.main as api_main
from api import routes
from src.privacy.scrub import detect_pii

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CHECKS = {
    "donation_page_and_intake_gated_when_disabled",
    "donation_page_gated_without_operator_contact",
    "donation_page_rejects_remote_clients",
    "donation_page_available_locally_when_enabled",
    "consent_gate_requires_explicit_opt_in",
    "pii_intake_rejection_enforced",
    "donation_intake_accepts_consented_synthetic_record",
    "withdrawal_erases_the_synthetic_record",
    "run_logs_are_message_free",
}

# Server-generated request ids are random hex, not personal data; stripping
# them keeps the independent pattern scan free of false positives.
REQUEST_ID_RE = re.compile(r"\b[0-9a-f]{32}\b")


def _assert_message_free(text: str) -> None:
    normalized = REQUEST_ID_RE.sub("", text)
    for forbidden in (*FIXTURE_MESSAGES, *PII_FIXTURE_VALUES):
        assert forbidden not in text
    assert not detect_pii(normalized, strict=True)


def test_preflight_fixtures_match_the_enforced_pii_rule():
    categories = {span.category for span in detect_pii(PII_FIXTURE_MESSAGE, strict=True)}
    assert {"email", "phone"} <= categories
    assert not detect_pii(DONATION_FIXTURE_MESSAGE, strict=True)


def test_preflight_passes_on_synthetic_fixtures(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SMSD_DONATIONS_ENABLED", "1")
    monkeypatch.delenv("SMSD_DONATIONS_OPERATOR_CONTACT", raising=False)
    output = tmp_path / "pilot-preflight.json"

    exit_code = main(["--output", str(output)])

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert {check["name"] for check in report["checks"]} == EXPECTED_CHECKS
    assert all(check["passed"] for check in report["checks"])
    assert report["logs"]["records_captured"] > 0
    assert report["logs"]["message_free"] is True
    assert report["cleanup"]["temporary_workspace_removed"] is True
    assert report["environment"]["donations_enabled"] is True
    stdout = capsys.readouterr().out
    _assert_message_free(stdout)
    _assert_message_free(output.read_text(encoding="utf-8"))


def test_preflight_run_logs_stay_message_free(monkeypatch, caplog):
    monkeypatch.setenv("SMSD_DONATIONS_ENABLED", "1")
    with caplog.at_level(logging.DEBUG):
        report = run_preflight()

    assert report["status"] == "passed"
    assert caplog.records, "the dry run must produce log records to scan"
    for record in caplog.records:
        line = record.getMessage()
        for forbidden in (*FIXTURE_MESSAGES, *PII_FIXTURE_VALUES):
            assert forbidden not in line
        assert not detect_pii(REQUEST_ID_RE.sub("", line), strict=True)


def test_preflight_fails_when_donations_are_disabled(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SMSD_DONATIONS_ENABLED", "0")
    output = tmp_path / "pilot-preflight.json"

    exit_code = main(["--output", str(output)])

    assert exit_code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "donation_page_available_locally_when_enabled" in failed
    assert {"consent_gate_requires_explicit_opt_in", "pii_intake_rejection_enforced"} <= failed
    assert report["logs"]["message_free"] is True
    _assert_message_free(capsys.readouterr().out)
    _assert_message_free(output.read_text(encoding="utf-8"))


def test_preflight_fails_when_the_pii_guard_is_bypassed(monkeypatch, tmp_path):
    monkeypatch.setenv("SMSD_DONATIONS_ENABLED", "1")
    monkeypatch.setattr(routes, "detect_pii", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(api.donations, "detect_pii", lambda *_args, **_kwargs: [])
    output = tmp_path / "pilot-preflight.json"

    report = run_preflight()

    assert report["status"] == "failed"
    pii_check = next(check for check in report["checks"] if check["name"] == "pii_intake_rejection_enforced")
    assert pii_check["passed"] is False
    assert "http_201" in pii_check["detail"], "the synthetic PII payload was accepted instead of rejected"
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (*FIXTURE_MESSAGES, *PII_FIXTURE_VALUES):
        assert forbidden not in serialized
    assert not output.exists()


def test_preflight_report_refuses_repository_tree_output(tmp_path):
    with pytest.raises(ValueError, match="outside the repository"):
        _validate_output_path(ROOT / "docs" / "pilot-preflight.json")
    assert (
        _validate_output_path(ROOT / "data" / "donations" / "pilot-preflight.json")
        == (ROOT / "data" / "donations" / "pilot-preflight.json").resolve()
    )
    assert (
        _validate_output_path(tmp_path / "private" / "pilot-preflight.json")
        == (tmp_path / "private" / "pilot-preflight.json").resolve()
    )


def test_preflight_main_rejects_repository_output_with_usage_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--output", str(ROOT / "pilot-preflight-report.json")])
    assert exit_info.value.code == 2
    assert "outside the repository" in capsys.readouterr().err


def test_write_report_refuses_message_like_payloads(tmp_path):
    leaked = {
        "status": "failed",
        "checks": [{"name": "pii_intake_rejection_enforced", "passed": False, "detail": PII_FIXTURE_MESSAGE}],
    }
    with pytest.raises(ValueError, match="message text"):
        write_report(leaked, tmp_path / "pilot-preflight.json")
    assert not (tmp_path / "pilot-preflight.json").exists()


def test_preflight_api_state_is_restored_after_runs(monkeypatch):
    monkeypatch.setenv("SMSD_DONATIONS_ENABLED", "1")
    original = {
        "enabled": api_main.DONATIONS_ENABLED,
        "contact": api_main.DONATIONS_OPERATOR_CONTACT,
        "database": api_main.DONATION_DB_PATH,
        "limit": api_main.DONATION_RATE_LIMIT_PER_MINUTE,
        "environment": api_main.SMSD_ENV,
        "notice": api_main.DONATION_NOTICE_VERSION,
    }
    run_preflight()
    restored = {
        "enabled": api_main.DONATIONS_ENABLED,
        "contact": api_main.DONATIONS_OPERATOR_CONTACT,
        "database": api_main.DONATION_DB_PATH,
        "limit": api_main.DONATION_RATE_LIMIT_PER_MINUTE,
        "environment": api_main.SMSD_ENV,
        "notice": api_main.DONATION_NOTICE_VERSION,
    }
    assert original == restored
