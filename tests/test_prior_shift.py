"""Tests for scenario projection from previously published aggregate counts."""

from __future__ import annotations

import json

import pytest

from src.prior_shift import DEFAULT_REPORT, analyze_report, main, project_confusion


def test_expected_counts_and_precision():
    result = project_confusion({"tp": 90, "fp": 10, "tn": 90, "fn": 10}, 0.05)
    assert result["expected_true_positive_per_1000"] == 45
    assert result["expected_false_positive_per_1000"] == 95
    assert result["expected_false_negative_per_1000"] == 5
    assert result["expected_true_negative_per_1000"] == 855
    assert result["expected_precision"] == pytest.approx(45 / 140, abs=1e-6)


def test_no_predicted_positives_has_undefined_precision():
    result = project_confusion({"tp": 0, "fp": 0, "tn": 100, "fn": 100}, 0.1)
    assert result["expected_precision"] is None


@pytest.mark.parametrize(
    "confusion",
    [
        {"tp": 1, "fp": 1, "tn": 0, "fn": -1},
        {"tp": 1, "fp": 0, "tn": 0, "fn": 1},
        {"tp": True, "fp": 1, "tn": 1, "fn": 1},
        {"tp": 1, "fp": 1, "tn": 1},
    ],
)
def test_invalid_counts_refused(confusion):
    with pytest.raises(ValueError):
        project_confusion(confusion, 0.1)


@pytest.mark.parametrize("prevalence", [0, 1, -0.1, float("nan"), True])
def test_invalid_prevalence_refused(prevalence):
    with pytest.raises(ValueError, match="prevalence"):
        project_confusion({"tp": 1, "fp": 1, "tn": 1, "fn": 1}, prevalence)


def test_published_report_projection_preserves_public_sources_and_frozen_threshold(capsys):
    assert main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert set(result["public_diagnostics"]) == {"tagalog_heldout_groups", "ph_inbox"}
    candidate = result["public_diagnostics"]["tagalog_heldout_groups"]["new_model"]
    assert candidate["threshold"] == 0.5
    assert candidate["observed_confusion"] == {"tp": 97, "fp": 12, "tn": 258, "fn": 5}
    assert candidate["scenarios"][1]["expected_precision"] == pytest.approx(0.529669, abs=1e-6)
    assert len(result["source_sha256"]) == 64


def test_inconsistent_aggregate_counts_refused_without_echoing_input(tmp_path, capsys):
    report = json.loads(DEFAULT_REPORT.read_text(encoding="utf-8"))
    report["frozen_sets"]["ph_inbox"]["new_model"]["n"] = 1
    report["private_marker"] = "fictional private marker"
    path = tmp_path / "private-input.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert main(["--report", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "fictional private marker" not in captured.err
    assert path.name not in captured.err


def test_missing_report_is_clean_error(tmp_path):
    assert main(["--report", str(tmp_path / "missing.json")]) == 2


def test_unequal_thresholds_are_not_compared(tmp_path):
    report = json.loads(DEFAULT_REPORT.read_text(encoding="utf-8"))
    report["frozen_sets"]["ph_inbox"]["new_model"]["decision_threshold"] = 0.6
    path = tmp_path / "different-threshold.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="identical class support and threshold"):
        analyze_report(path)
