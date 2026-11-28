"""Tests for active learning and feedback triage."""

from __future__ import annotations

import json

from src.active_learning import main, triage_feedback


def test_cli_writes_a_json_report(tmp_path, capsys):
    path = tmp_path / "reports.jsonl"
    path.write_text(
        json.dumps(
            {
                "predicted_label": "spam",
                "expected_label": "ham",
                "category": "otp",
                "server_model_version": "v2.0",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "triage.json"

    assert main(["--path", str(path), "--output", str(output)]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["false_positive_count"] == 1
    assert "Triage report written" in capsys.readouterr().out


def test_cli_prints_an_empty_report_to_stdout(tmp_path, capsys):
    assert main(["--path", str(tmp_path / "missing.jsonl")]) == 0
    assert json.loads(capsys.readouterr().out)["total_reports"] == 0


def test_triage_empty_reports():
    triage = triage_feedback([])
    assert triage["total_reports"] == 0
    assert triage["false_positive_count"] == 0
    assert triage["false_negative_count"] == 0
    assert triage["privacy_verified"] is True
    assert len(triage["recommendations"]) == 1


def test_triage_flags_critical_false_positives():
    reports = [
        {
            "predicted_label": "spam",
            "expected_label": "ham",
            "category": "bank_alert",
            "server_model_version": "v2.0",
        },
        {
            "predicted_label": "spam",
            "expected_label": "ham",
            "category": "otp",
            "server_model_version": "v2.0",
        },
    ]
    triage = triage_feedback(reports)
    assert triage["total_reports"] == 2
    assert triage["false_positive_count"] == 2
    assert "bank_alert" in triage["false_positives_by_category"]
    assert "otp" in triage["false_positives_by_category"]
    assert any("critical categories" in rec for rec in triage["recommendations"])


def test_triage_flags_missed_scams():
    reports = [
        {
            "predicted_label": "ham",
            "expected_label": "spam",
            "category": "phishing",
            "server_model_version": "v2.0",
        }
    ]
    triage = triage_feedback(reports)
    assert triage["total_reports"] == 1
    assert triage["false_negative_count"] == 1
    assert "phishing" in triage["false_negatives_by_category"]
    assert any("Evasion detected" in rec for rec in triage["recommendations"])
