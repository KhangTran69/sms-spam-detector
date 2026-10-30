"""Tests for active learning and feedback triage."""

from __future__ import annotations

from src.active_learning import triage_feedback


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
