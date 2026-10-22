"""Privacy and provenance regressions for evaluation reports."""

import hashlib
from types import SimpleNamespace

import pandas as pd

from src.data import Dataset, FileRecord
from src.evaluate import (
    _benchmark_run_info,
    _data_hash_warnings,
    _errors,
    _length_strata,
    _provenance_banner,
    _score_interpretation,
    _threshold_diagnostic,
)
from src.predict import ModelBundle


def _bundle(**kwargs) -> ModelBundle:
    return ModelBundle(
        pipeline=SimpleNamespace(predict_proba=lambda _: None, classes_=["ham", "spam"]),
        **kwargs,
    )


def test_benchmark_run_info_binds_artifact_without_exposing_its_path(tmp_path) -> None:
    private_path = tmp_path / "private-workspace" / "candidate.pkl"
    private_path.parent.mkdir()
    artifact = b"fixture model bytes"
    private_path.write_bytes(artifact)

    info = _benchmark_run_info(private_path)

    assert info["model_sha256"] == hashlib.sha256(artifact).hexdigest()
    assert str(private_path) not in str(info)
    assert "source_revision" in info
    assert "scikit-learn" in info["libraries"]


def test_misclassification_records_never_contain_message_text() -> None:
    private_text = "MIRA account 123456 OTP 987654 call 09171234567"
    frame = pd.DataFrame(
        [
            {
                "message": private_text,
                "label": "ham",
                "category": "otp",
                "language": "en",
            }
        ]
    )
    errors = _errors(Dataset(frame), [0.99], 0.5)
    assert len(errors) == 1
    assert private_text not in str(errors)
    assert not any("message" in record for record in errors)
    assert errors[0]["category"] == "otp"
    assert errors[0]["spam_score"] == 0.99
    assert errors[0]["probability_calibrated"] is False


def test_evaluation_banner_reflects_declared_provenance() -> None:
    synthetic = Dataset(pd.DataFrame({"data_kind": ["synthetic", "synthetic"]}))
    unknown = Dataset(pd.DataFrame({"data_kind": ["unknown"]}))
    public = Dataset(pd.DataFrame({"data_kind": ["public"]}))

    assert "SYNTHETIC" in _provenance_banner(synthetic)
    assert "UNVERIFIED" in _provenance_banner(unknown)
    assert "PUBLIC-CORPUS" in _provenance_banner(public)


def test_message_length_metrics_use_documented_codepoint_ranges() -> None:
    frame = pd.DataFrame({"message": ["a" * 70, "b" * 71, "c" * 161]})
    assert _length_strata(frame)["message_length_range"].tolist() == ["1-70", "71-160", "161+"]


def test_artifact_hash_report_does_not_expose_private_source_paths() -> None:
    record = FileRecord(
        path="/secure/participant-name/private-messages.csv",
        role="base",
        sha256="current-hash",
        rows_in=2,
        rows_loaded=2,
        duplicates_removed=0,
    )
    dataset = Dataset(pd.DataFrame(), records=[record])
    bundle = SimpleNamespace(metadata={"data_sources": [{"role": "base", "path": "base:old", "sha256": "old-hash"}]})

    warnings = _data_hash_warnings(bundle, dataset)

    assert any("differs from the training manifest hash" in warning for warning in warnings)
    assert "participant-name" not in str(warnings)
    assert "private-messages.csv" not in str(warnings)


def test_threshold_diagnostic_recognizes_intentionally_retained_cv_default() -> None:
    bundle = _bundle(
        threshold=0.5,
        metadata={
            "threshold_selection": {
                "threshold": 0.4,
                "target_precision": 0.98,
                "min_recall": 0.0,
                "decision": {
                    "policy": "cv-robust",
                    "candidate_threshold": 0.4,
                    "threshold": 0.5,
                    "default_threshold": 0.5,
                    "fold_f1_gains": [-0.01, 0.02],
                    "mean_f1_gain": 0.005,
                    "min_required_mean_gain": 0.02,
                    "adopted": False,
                },
            },
            "training_config": {"threshold_policy": "cv-robust", "target_precision": 0.98, "min_recall": 0.0},
        },
    )

    diagnostic = _threshold_diagnostic(bundle, 0.4)

    assert diagnostic["status"] == "default_intentionally_retained"
    assert diagnostic["policy"] == "cv-robust"


def test_threshold_diagnostic_does_not_blame_data_for_policy_mismatch() -> None:
    bundle = _bundle(
        threshold=0.5,
        metadata={
            "threshold_selection": {
                "threshold": 0.4,
                "target_precision": 0.98,
                "min_recall": 0.0,
                "decision": {
                    "policy": "cv-robust",
                    "candidate_threshold": 0.4,
                    "threshold": 0.5,
                    "adopted": False,
                },
            },
            "training_config": {"threshold_policy": "validation", "target_precision": 0.98, "min_recall": 0.0},
        },
    )

    diagnostic = _threshold_diagnostic(bundle, 0.4)

    assert diagnostic["status"] == "validation_policy_mismatch"


def test_threshold_diagnostic_requires_recorded_candidate_to_match_validation() -> None:
    bundle = _bundle(
        threshold=0.5,
        metadata={
            "threshold_selection": {
                "threshold": 0.35,
                "target_precision": 0.98,
                "min_recall": 0.0,
                "decision": {
                    "policy": "cv-robust",
                    "candidate_threshold": 0.35,
                    "threshold": 0.5,
                    "default_threshold": 0.5,
                    "fold_f1_gains": [-0.01, 0.02],
                    "mean_f1_gain": 0.005,
                    "min_required_mean_gain": 0.02,
                    "adopted": False,
                },
            },
            "training_config": {"threshold_policy": "cv-robust", "target_precision": 0.98, "min_recall": 0.0},
        },
    )

    diagnostic = _threshold_diagnostic(bundle, 0.4)

    assert diagnostic["status"] == "validation_candidate_drift"


def test_threshold_diagnostic_handles_malformed_optional_metadata() -> None:
    bundle = _bundle(
        threshold=0.5,
        metadata={
            "threshold_selection": {
                "threshold": "broken",
                "target_precision": 0.98,
                "min_recall": 0.0,
                "decision": {"policy": "cv-robust", "candidate_threshold": "broken", "threshold": None},
            },
            "training_config": {"threshold_policy": "cv-robust", "target_precision": 0.98, "min_recall": 0.0},
        },
    )

    diagnostic = _threshold_diagnostic(bundle, 0.4)

    assert diagnostic["status"] == "policy_metadata_malformed"


def test_threshold_diagnostic_does_not_assume_retained_default_without_matching_candidate() -> None:
    bundle = _bundle(
        threshold=0.5,
        metadata={
            "threshold_selection": {
                "threshold": 0.4,
                "decision": {"policy": "cv-robust", "candidate_threshold": 0.4, "threshold": 0.5, "adopted": False},
            },
            "training_config": {"threshold_policy": "validation"},
        },
    )

    assert _threshold_diagnostic(bundle, 0.4)["status"] == "validation_policy_mismatch"


def test_threshold_diagnostic_checks_configured_policy_matches_decision() -> None:
    bundle = _bundle(
        threshold=0.5,
        metadata={
            "threshold_selection": {
                "threshold": 0.4,
                "decision": {"policy": "cv-robust", "candidate_threshold": 0.4, "threshold": 0.5, "adopted": False},
            },
            "training_config": {"threshold_policy": "validation"},
        },
    )

    assert _threshold_diagnostic(bundle, 0.4)["status"] == "validation_policy_mismatch"


def test_validation_threshold_requires_candidate_and_adoption_metadata() -> None:
    metadata = {
        "threshold_selection": {
            "threshold": 0.4,
            "target_precision": 0.98,
            "min_recall": 0.0,
            "decision": {"policy": "validation", "candidate_threshold": 0.4, "threshold": 0.4, "adopted": True},
        },
        "training_config": {"threshold_policy": "validation", "target_precision": 0.98, "min_recall": 0.0},
    }
    assert _threshold_diagnostic(_bundle(threshold=0.4, metadata=metadata), 0.4)["status"] == "matches_validation"

    malformed = {
        **metadata,
        "threshold_selection": {
            **metadata["threshold_selection"],
            "decision": {**metadata["threshold_selection"]["decision"], "adopted": False},
        },
    }
    assert (
        _threshold_diagnostic(_bundle(threshold=0.4, metadata=malformed), 0.4)["status"]
        == "adoption_metadata_inconsistent"
    )


def test_threshold_diagnostic_checks_validation_settings_match_training_config() -> None:
    metadata = {
        "threshold_selection": {
            "threshold": 0.4,
            "target_precision": 0.95,
            "min_recall": 0.0,
            "decision": {"policy": "validation", "candidate_threshold": 0.4, "threshold": 0.4, "adopted": True},
        },
        "training_config": {"threshold_policy": "validation", "target_precision": 0.98, "min_recall": 0.0},
    }

    assert (
        _threshold_diagnostic(_bundle(threshold=0.4, metadata=metadata), 0.4)["status"]
        == "policy_metadata_inconsistent"
    )


def test_threshold_diagnostic_checks_error_cost_policy_strategy() -> None:
    metadata = {
        "threshold_selection": {
            "threshold": 0.4,
            "target_precision": 0.98,
            "min_recall": 0.0,
            "strategy": "max_f0.5_subject_to_precision_recall",
            "decision": {"policy": "validation", "candidate_threshold": 0.4, "threshold": 0.4, "adopted": True},
        },
        "training_config": {
            "threshold_policy": "validation",
            "target_precision": 0.98,
            "min_recall": 0.0,
            "false_positive_cost": 2.0,
            "false_negative_cost": 1.0,
        },
    }

    assert (
        _threshold_diagnostic(_bundle(threshold=0.4, metadata=metadata), 0.4)["status"]
        == "policy_metadata_inconsistent"
    )


def test_threshold_diagnostic_distinguishes_absent_metadata() -> None:
    bundle = _bundle(threshold=0.5, metadata={})

    assert _threshold_diagnostic(bundle, 0.4)["status"] == "policy_metadata_absent"


def test_threshold_diagnostic_handles_unhashable_policy_metadata() -> None:
    bundle = _bundle(
        threshold=0.5,
        metadata={
            "threshold_selection": {"decision": {"policy": ["validation"]}},
            "training_config": {"threshold_policy": ["validation"]},
        },
    )

    assert _threshold_diagnostic(bundle, 0.4)["status"] == "policy_metadata_malformed"


def test_evaluation_score_description_uses_artifact_calibration_metadata() -> None:
    uncalibrated = _bundle(metadata={"probability_calibrated": False})
    calibrated = _bundle(metadata={"probability_calibrated": True})

    assert "uncalibrated" in _score_interpretation(uncalibrated)
    assert "fraud probability" in _score_interpretation(calibrated)
    malformed = _bundle(metadata={"probability_calibrated": "true"})
    assert "uncalibrated" in _score_interpretation(malformed)
