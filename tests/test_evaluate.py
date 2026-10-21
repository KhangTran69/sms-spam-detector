"""Privacy and provenance regressions for evaluation reports."""

from types import SimpleNamespace

import pandas as pd

from src.data import Dataset, FileRecord
from src.evaluate import (
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
                "decision": {"policy": "cv-robust", "candidate_threshold": 0.4, "threshold": 0.5, "adopted": False}
            }
        },
    )

    diagnostic = _threshold_diagnostic(bundle, 0.4)

    assert diagnostic["status"] == "default_intentionally_retained"
    assert diagnostic["policy"] == "cv-robust"


def test_threshold_diagnostic_does_not_blame_data_for_policy_mismatch() -> None:
    bundle = _bundle(threshold=0.5, metadata={"threshold_selection": {"decision": {"policy": "validation"}}})

    diagnostic = _threshold_diagnostic(bundle, 0.4)

    assert diagnostic["status"] == "validation_policy_mismatch"


def test_evaluation_score_description_uses_artifact_calibration_metadata() -> None:
    uncalibrated = _bundle(metadata={"probability_calibrated": False})
    calibrated = _bundle(metadata={"probability_calibrated": True})

    assert "uncalibrated" in _score_interpretation(uncalibrated)
    assert "calibrated spam probability estimate" in _score_interpretation(calibrated)
