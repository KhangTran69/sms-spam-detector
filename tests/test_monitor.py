"""Tests for prediction score distribution monitoring and drift detection."""

from __future__ import annotations

import concurrent.futures

import numpy as np
import pytest

from src.monitor import (
    PredictionMonitor,
    compute_distribution_summary,
    compute_drift,
    compute_psi,
)


def test_distribution_summary_empty():
    summary = compute_distribution_summary([])
    assert summary["count"] == 0
    assert summary["mean"] == 0.0
    assert summary["percentiles"]["p50"] == 0.0


def test_distribution_summary_values():
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    summary = compute_distribution_summary(scores)
    assert summary["count"] == 9
    assert pytest.approx(summary["mean"], 0.01) == 0.5
    assert pytest.approx(summary["min"], 0.01) == 0.1
    assert pytest.approx(summary["max"], 0.01) == 0.9
    assert pytest.approx(summary["percentiles"]["p50"], 0.01) == 0.5


def test_psi_identical_distributions():
    np.random.seed(42)
    dist1 = np.random.beta(2, 5, size=500).tolist()
    dist2 = np.random.beta(2, 5, size=500).tolist()
    psi = compute_psi(dist1, dist2)
    assert psi < 0.10


def test_psi_drifted_distributions():
    # Low scores vs high scores
    dist1 = [0.05, 0.08, 0.12, 0.15, 0.09] * 50
    dist2 = [0.85, 0.92, 0.88, 0.95, 0.89] * 50
    psi = compute_psi(dist1, dist2)
    assert psi > 0.20


def test_psi_edge_cases():
    assert compute_psi([], [0.5]) == 0.0
    assert compute_psi([0.5], [0.5]) == 0.0


def test_drift_status():
    np.random.seed(42)
    baseline = np.random.normal(0.2, 0.05, size=500).clip(0, 1).tolist()
    current_stable = np.random.normal(0.2, 0.05, size=500).clip(0, 1).tolist()
    drift_stable = compute_drift(baseline, current_stable)
    assert drift_stable["drift_status"] == "stable"
    assert not drift_stable["ks_drift_detected"]

    current_drifted = np.random.normal(0.8, 0.05, size=500).clip(0, 1).tolist()
    drift_flagged = compute_drift(baseline, current_drifted)
    assert drift_flagged["drift_status"] == "significant_drift"
    assert drift_flagged["ks_drift_detected"]


def test_prediction_monitor():
    monitor = PredictionMonitor(window_size=100)
    baseline = [0.1, 0.2, 0.15, 0.05, 0.12] * 20
    monitor.set_baseline(baseline)

    for _i in range(30):
        monitor.record(score=0.1, label="ham")
    for _i in range(10):
        monitor.record(score=0.9, label="spam")

    metrics = monitor.get_metrics()
    assert metrics["samples_in_window"] == 40
    assert metrics["spam_ratio"] == 0.25
    assert metrics["score_distribution"]["count"] == 40
    assert "drift" in metrics
    assert metrics["baseline_samples"] == 100

    monitor.clear()
    assert monitor.get_metrics()["samples_in_window"] == 0


def test_prediction_monitor_thread_safety():
    monitor = PredictionMonitor(window_size=200)

    def worker(score, label):
        for _ in range(50):
            monitor.record(score, label)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(worker, 0.1, "ham"),
            executor.submit(worker, 0.9, "spam"),
            executor.submit(worker, 0.2, "ham"),
            executor.submit(worker, 0.8, "spam"),
        ]
        concurrent.futures.wait(futures)

    metrics = monitor.get_metrics()
    assert metrics["samples_in_window"] == 200
