from src.benchmark import BENCHMARK_BANNER, run_benchmark


def test_fixed_synthetic_benchmark_is_deterministic_and_has_stable_schema() -> None:
    first = run_benchmark()
    second = run_benchmark()

    assert first == second
    assert first["schema_version"] == 1
    assert first["banner"] == BENCHMARK_BANNER
    assert first["real_world_performance_claim"] is False
    assert first["seed"] == 42
    assert first["split_method"] == "group"
    assert set(first["data_kind_counts"]) == {"synthetic"}
    assert first["input_files"] == [
        "ph_supplement.csv",
        "ph_supplement_2.csv",
        "ph_supplement_3.csv",
        "ph_supplement_4.csv",
        "ph_supplement_5.csv",
    ]
    assert set(first["split_summary"]) == {"train", "val", "test"}
    assert first["holdout_file"] == "ph_holdout.csv"
    assert len(first["holdout_sha256"]) == 64
    assert {"precision", "recall", "f1", "accuracy", "support"} <= set(first["test_metrics"])
    assert {"precision", "recall", "f1", "accuracy", "support"} <= set(first["synthetic_holdout_metrics"])
