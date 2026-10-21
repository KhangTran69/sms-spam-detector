"""Privacy and provenance regressions for evaluation reports."""

from types import SimpleNamespace

import pandas as pd

from src.data import Dataset, FileRecord
from src.evaluate import _data_hash_warnings, _errors, _length_strata, _provenance_banner


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
