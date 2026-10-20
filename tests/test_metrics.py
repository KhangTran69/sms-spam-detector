"""Evaluation uncertainty and score reporting tests."""

from __future__ import annotations

import pytest

from src.metrics import binary_metrics


def test_binary_metrics_include_wilson_intervals_with_support():
    result = binary_metrics(["spam", "spam", "ham", "ham"], [0.9, 0.2, 0.8, 0.1], 0.5)
    intervals = result["confidence_intervals_95"]
    assert intervals["method"].startswith("Wilson score")
    expected = [0.0945, 0.9055]
    assert intervals["precision"] == pytest.approx(expected, abs=0.001)
    assert intervals["recall"] == pytest.approx(expected, abs=0.001)
    assert intervals["false_positive_rate"] == pytest.approx(expected, abs=0.001)


def test_binary_metrics_empty_denominator_has_no_interval():
    result = binary_metrics(["ham", "ham"], [0.1, 0.2], 0.5)
    assert result["confidence_intervals_95"]["precision"] is None
    assert result["confidence_intervals_95"]["recall"] is None
    assert result["confidence_intervals_95"]["false_positive_rate"] == pytest.approx([0.0, 0.6576], abs=0.001)
