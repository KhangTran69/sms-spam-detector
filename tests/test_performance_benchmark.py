"""Regression tests for the inference performance benchmark entrypoint."""

from __future__ import annotations

import sys

from scripts import benchmark_performance


def test_performance_budget_rejects_slow_p95():
    from scripts.check_performance_budget import check_budget

    result = {"model_load": {"load_time_ms": 100.0}, "single_prediction_latency_ms": {"p95": 50.0}}

    failures = check_budget(result, max_p95_ms=25.0, max_load_ms=500.0)

    assert failures
    assert any("p95" in failure for failure in failures)


def test_performance_budget_accepts_within_budget():
    from scripts.check_performance_budget import check_budget

    result = {"model_load": {"load_time_ms": 100.0}, "single_prediction_latency_ms": {"p95": 10.0}}

    assert check_budget(result, max_p95_ms=25.0, max_load_ms=500.0) == []


def test_missing_model_does_not_train_or_create_artifacts(monkeypatch, tmp_path, capsys):
    model_path = tmp_path / "missing.pkl"
    output_dir = tmp_path / "benchmark-reports"
    monkeypatch.setattr(
        sys,
        "argv",
        ["benchmark_performance.py", "--model", str(model_path), "--output-dir", str(output_dir)],
    )

    assert benchmark_performance.main() == 1
    assert "Model artifact not found" in capsys.readouterr().err
    assert not model_path.exists()
    assert not output_dir.exists()


def test_benchmark_default_model_path_honors_environment(monkeypatch, tmp_path, capsys):
    model_path = tmp_path / "custom-model.pkl"
    monkeypatch.setenv("SMSD_MODEL_PATH", str(model_path))
    monkeypatch.setattr(sys, "argv", ["benchmark_performance.py"])

    assert benchmark_performance.main() == 1
    assert str(model_path) in capsys.readouterr().err
    assert not model_path.exists()
