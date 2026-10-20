"""Evaluation uncertainty and score reporting tests."""

from __future__ import annotations

import pytest

from src.metrics import binary_metrics, campaign_bootstrap_intervals, select_threshold


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


def test_user_supplied_error_costs_choose_threshold_without_implying_policy():
    labels = ["spam", "ham", "spam", "ham"]
    probabilities = [0.9, 0.8, 0.2, 0.1]
    fp_expensive = select_threshold(labels, probabilities, false_positive_cost=10, false_negative_cost=1)
    fn_expensive = select_threshold(labels, probabilities, false_positive_cost=1, false_negative_cost=10)
    assert fp_expensive.threshold > fn_expensive.threshold
    assert "not an approved production policy" in fp_expensive.note


def test_costs_must_be_provided_as_a_pair():
    with pytest.raises(ValueError, match="provided together"):
        select_threshold(["ham", "spam"], [0.1, 0.9], false_positive_cost=1)
    with pytest.raises(ValueError, match="must be positive"):
        select_threshold(["ham", "spam"], [0.1, 0.9], false_positive_cost=float("nan"), false_negative_cost=1)


def test_campaign_bootstrap_resamples_whole_groups_and_is_reproducible():
    import pandas as pd

    frame = pd.DataFrame(
        {
            "label": ["ham", "spam"] * 12,
            "group": [f"campaign-{index}" for index in range(12) for _ in range(2)],
        }
    )
    probabilities = [0.1, 0.9] * 12
    first = campaign_bootstrap_intervals(frame, probabilities, 0.5, replicates=100, seed=7)
    second = campaign_bootstrap_intervals(frame, probabilities, 0.5, replicates=100, seed=7)
    assert first["available"] is True
    assert first["method"].startswith("percentile cluster bootstrap")
    assert first["intervals"] == second["intervals"]
    assert first["group_count"] == 12


def test_campaign_bootstrap_withholds_interval_when_group_support_is_small():
    import pandas as pd

    frame = pd.DataFrame({"label": ["ham", "spam"], "group": ["one", "two"]})
    result = campaign_bootstrap_intervals(frame, [0.1, 0.9], 0.5, replicates=10)
    assert result["available"] is False
    assert "at least 10 distinct group IDs" in result["reason"]
