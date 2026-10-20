"""Privacy and provenance regressions for evaluation reports."""

import pandas as pd

from src.data import Dataset
from src.evaluate import _errors, _length_strata, _provenance_banner


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
