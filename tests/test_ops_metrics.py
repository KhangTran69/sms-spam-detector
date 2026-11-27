"""Tests for bounded operational telemetry."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from api.ops_metrics import OperationsMonitor


def test_aggregates_counts_latency_without_request_identifiers():
    monitor = OperationsMonitor(window_size=3)
    monitor.record("POST", "/predict", 200, 10)
    monitor.record("POST", "/v1/predict", 429, 20)
    monitor.record("POST", "/secret-fixture-SMS", 503, 30)
    monitor.record("GET", "/health", 200, 40)
    snapshot = monitor.snapshot()
    assert snapshot["request_count"] == 4
    assert snapshot["route_groups"]["prediction"] == 2
    assert snapshot["route_groups"]["other"] == 1
    assert snapshot["status_classes"] == {"2xx": 2, "4xx": 1, "5xx": 1}
    assert snapshot["latency_window_samples"] == 3
    assert snapshot["latency_p50_ms"] == 30
    assert "secret-fixture-SMS" not in str(snapshot)
    assert "/predict" not in str(snapshot)


def test_concurrent_updates_and_reset():
    monitor = OperationsMonitor(window_size=12)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: monitor.record("POST", "/analyze", 200, i), range(100)))
    snapshot = monitor.snapshot()
    assert snapshot["request_count"] == 100
    assert snapshot["latency_window_samples"] == 12
    monitor.clear()
    assert monitor.snapshot()["request_count"] == 0
    assert monitor.snapshot()["latency_p95_ms"] is None
