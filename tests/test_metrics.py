"""Evaluation uncertainty and score reporting tests."""

from __future__ import annotations

import pytest

from src.metrics import (
    binary_metrics,
    bootstrap_metrics,
    calibration_metrics,
    campaign_bootstrap_intervals,
    expected_calibration_error,
    per_group_metrics,
    select_threshold,
)


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

    pooled_without_ham = binary_metrics(["spam", "spam"], [0.1, 0.2], 0.5)
    assert pooled_without_ham["precision"] == 0.0
    assert pooled_without_ham["recall"] == 0.0
    assert pooled_without_ham["f1"] == 0.0
    assert pooled_without_ham["false_positive_rate"] == 0.0


def test_per_group_metrics_reports_zero_support_rates_as_none():
    import pandas as pd

    frame = pd.DataFrame(
        {
            "label": ["spam", "spam", "ham", "ham", "ham", "ham"],
            "language": [
                "spam_only",
                "spam_only",
                "ham_no_predictions",
                "ham_no_predictions",
                "ham_with_false_positive",
                "ham_with_false_positive",
            ],
        }
    )

    metrics = {
        row["language"]: row
        for row in per_group_metrics(frame, [0.9, 0.1, 0.1, 0.2, 0.9, 0.1], 0.5, group_columns=("language",))
    }

    assert metrics["spam_only"]["false_positive_rate"] is None
    assert metrics["spam_only"]["precision"] == 1.0
    assert metrics["spam_only"]["recall"] == 0.5

    ham_without_predictions = metrics["ham_no_predictions"]
    assert ham_without_predictions["precision"] is None
    assert ham_without_predictions["recall"] is None
    assert ham_without_predictions["f1"] is None
    assert ham_without_predictions["false_positive_rate"] == 0.0
    assert ham_without_predictions["confidence_intervals_95"]["false_positive_rate"] is not None

    ham_with_false_positive = metrics["ham_with_false_positive"]
    assert ham_with_false_positive["precision"] == 0.0
    assert ham_with_false_positive["recall"] is None
    assert ham_with_false_positive["f1"] == 0.0
    assert ham_with_false_positive["false_positive_rate"] == 0.5


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
    assert first["intervals"]["false_negative_rate"] == [0.0, 0.0]


def test_campaign_bootstrap_withholds_interval_when_group_support_is_small():
    import pandas as pd

    frame = pd.DataFrame({"label": ["ham", "spam"], "group": ["one", "two"]})
    result = campaign_bootstrap_intervals(frame, [0.1, 0.9], 0.5, replicates=10)
    assert result["available"] is False
    assert "at least 10 distinct group IDs" in result["reason"]


def test_bootstrap_metrics_computes_empirical_percentiles():
    labels = ["spam", "spam", "ham", "ham"] * 10
    probs = [0.9, 0.85, 0.1, 0.15] * 10
    ci = bootstrap_metrics(labels, probs, threshold=0.5, n_bootstraps=200, seed=42)
    assert ci["confidence_level"] == 0.95
    assert 0.8 <= ci["f1"][0] <= ci["f1"][1] <= 1.0
    assert 0.8 <= ci["precision"][0] <= ci["precision"][1] <= 1.0
    assert 0.8 <= ci["recall"][0] <= ci["recall"][1] <= 1.0
    assert 0.8 <= ci["accuracy"][0] <= ci["accuracy"][1] <= 1.0


def test_campaign_bootstrap_excludes_undefined_class_ratios():
    import pandas as pd

    frame = pd.DataFrame({"label": ["ham", "spam"], "group": ["a", "b"]})
    report = campaign_bootstrap_intervals(frame, [0.1, 0.9], 0.5, replicates=200, minimum_groups=2)
    assert report["intervals"]["recall"] == [1.0, 1.0]
    assert report["intervals"]["precision"] == [1.0, 1.0]
    assert report["intervals"]["false_positive_rate"] == [0.0, 0.0]
    assert 0 < report["valid_replicates"]["recall"] < 200
    assert 0 < report["valid_replicates"]["false_positive_rate"] < 200


def test_calibration_accepts_one_shot_score_iterables_and_bins_include_endpoints():
    labels = ["ham", "spam", "ham", "spam"]
    scores = [0.0, 0.5, 0.5, 1.0]
    result = calibration_metrics(labels, iter(scores), n_bins=2)
    assert result == calibration_metrics(labels, scores, n_bins=2)
    assert [entry["count"] for entry in result["bins"]] == [1, 3]
    assert result["brier_score"] == pytest.approx(0.125)
    assert result["expected_calibration_error"] == pytest.approx(0)


@pytest.mark.parametrize("scores", [[0.1], [0.1, float("nan")], [-0.1, 0.5], [0.1, 1.1], [[0.1], [0.9]]])
def test_calibration_refuses_invalid_score_vectors(scores):
    with pytest.raises(ValueError):
        calibration_metrics(["ham", "spam"], scores)


def test_calibration_rejects_empty_inputs_and_invalid_bin_counts():
    with pytest.raises(ValueError, match="at least one"):
        calibration_metrics([], [])
    with pytest.raises(ValueError, match="n_bins"):
        expected_calibration_error(["ham"], [0.0], n_bins=0)
    with pytest.raises(ValueError, match="differ in length"):
        expected_calibration_error(["ham"], [0.0, 0.1])
