"""Importer regression coverage using fictional, masked-only fixtures."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.consented_data import main as preflight_main
from src.data import DatasetError, load_dataset
from src.import_consented import import_consented
from src.import_consented import main as importer_main


def _fixture(tmp_path, rows: list[dict[str, str]]) -> tuple[object, object]:
    source = tmp_path / "private_participant_batch.csv"
    output = tmp_path / "protected"
    pd.DataFrame(rows).to_csv(source, index=False)
    return source, output


def _valid_rows() -> list[dict[str, str]]:
    common = {
        "data_kind": "consented",
        "source": "consented_batch_01",
        "category": "school_work",
        "language": "en",
        "consent_record_id": "consent_001",
        "consent_verified": "true",
        "consent_active": "true",
        "consent_scope": "training_and_evaluation",
        "consent_version": "v1",
        "consent_date": "2026-01-15",
        "retention_until": "2027-01-15",
        "reviewer_a_id": "reviewer_a",
        "reviewer_b_id": "reviewer_b",
        "adjudicator_id": "",
    }
    return [
        {
            **common,
            "label": "ham",
            "message": "Your appointment is confirmed for Monday.",
            "group": "campaign_safe_01",
            "reviewer_a_label": "ham",
            "reviewer_b_label": "ham",
            "adjudicated_label": "ham",
        },
        {
            **common,
            "label": "spam",
            "message": "Claim your reward now at URLTOKEN.",
            "group": "campaign_scam_02",
            "reviewer_a_label": "spam",
            "reviewer_b_label": "spam",
            "adjudicated_label": "spam",
        },
    ]


def test_importer_uses_shared_schema_and_outputs_loader_compatible_file(tmp_path) -> None:
    rows = _valid_rows()
    source, output = _fixture(tmp_path, rows)

    result = import_consented(source, purpose="training", output_dir=output, today=date(2026, 10, 21))
    imported = output / result["output"]
    dataset = load_dataset(imported, require_both_classes=True, min_class_count=0)

    assert result["rows_written"] == 2
    assert dataset.class_counts == {"ham": 1, "spam": 1}
    assert dataset.frame["data_kind"].eq("consented").all()
    assert set(dataset.frame["group"]) == {"campaign_safe_01", "campaign_scam_02"}
    assert "private_participant_batch.csv" not in str(result)
    assert rows[0]["message"] not in str(result)


def test_documented_cli_workflow_accepts_fictional_fixture(tmp_path, capsys) -> None:
    source, output = _fixture(tmp_path, _valid_rows())

    assert preflight_main([str(source), "--purpose", "training"]) == 0
    assert '"valid": true' in capsys.readouterr().out
    assert importer_main(["--input", str(source), "--purpose", "training", "--output-dir", str(output)]) == 0
    imported_report = capsys.readouterr().out
    assert '"rows_written": 2' in imported_report
    assert source.name not in imported_report
    assert (output / next(path.name for path in output.glob("*.csv"))).exists()


@pytest.mark.parametrize(
    ("overrides", "purpose", "expected_rule"),
    [
        ({"consent_active": "false"}, "training", "consent_inactive_or_revoked"),
        ({"retention_until": "2026-10-20"}, "training", "retention_expired_or_invalid"),
        (
            {
                "reviewer_a_label": "ham",
                "reviewer_b_label": "spam",
                "label": "spam",
                "adjudicated_label": "spam",
                "adjudicator_id": "reviewer_a",
            },
            "training",
            "independent_adjudicator_required_for_disagreement",
        ),
        ({"consent_scope": "training"}, "evaluation", "consent_does_not_cover_evaluation"),
        ({"consent_scope": "evaluation"}, "training", "consent_does_not_cover_training"),
    ],
)
def test_importer_rejects_consent_and_review_failures_without_echoing_content(
    tmp_path, overrides, purpose, expected_rule
) -> None:
    rows = _valid_rows()
    rows[0].update(overrides)
    secret = "Fictional message with masked content only."
    rows[0]["message"] = secret
    source, output = _fixture(tmp_path, rows)

    with pytest.raises(ValueError, match=expected_rule) as raised:
        import_consented(source, purpose=purpose, output_dir=output, today=date(2026, 10, 21))

    assert secret not in str(raised.value)
    assert not output.exists()


def test_evaluation_import_requires_both_labels(tmp_path) -> None:
    rows = _valid_rows()
    rows[0]["consent_scope"] = "training_and_evaluation"
    rows[1]["consent_scope"] = "training_and_evaluation"
    rows[1]["label"] = rows[1]["adjudicated_label"] = "ham"
    rows[1]["reviewer_a_label"] = rows[1]["reviewer_b_label"] = "ham"
    source, output = _fixture(tmp_path, rows)

    with pytest.raises(ValueError, match="evaluation_batch_requires_both_labels"):
        import_consented(source, purpose="evaluation", output_dir=output, today=date(2026, 10, 21))


def test_importer_rejects_unmasked_values_using_shared_preflight(tmp_path) -> None:
    rows = _valid_rows()
    rows[0]["message"] = "Fictional SMS with 09171234567 and [CODE]."
    source, output = _fixture(tmp_path, rows)

    with pytest.raises(ValueError, match="possible_phone_number"):
        import_consented(source, purpose="training", output_dir=output, today=date(2026, 10, 21))
    assert not output.exists()


def test_training_loader_rechecks_consent_even_when_import_is_bypassed(tmp_path) -> None:
    rows = _valid_rows()
    rows[0]["consent_active"] = "false"
    source, _ = _fixture(tmp_path, rows)

    with pytest.raises(DatasetError, match="consent_inactive_or_revoked"):
        load_dataset(source, require_both_classes=False, min_class_count=0)


def test_training_loader_rejects_consent_without_review_metadata(tmp_path) -> None:
    path = tmp_path / "unreviewed-consented.csv"
    pd.DataFrame(
        [
            ("ham", "Fictional safe message one", "consented", "batch_a", "school_work", "en", "campaign_a"),
            ("spam", "Fictional scam message two", "consented", "batch_a", "phishing", "en", "campaign_b"),
        ],
        columns=("label", "message", "data_kind", "source", "category", "language", "group"),
    ).to_csv(path, index=False)

    with pytest.raises(DatasetError, match="approved consented intake schema") as raised:
        load_dataset(path, require_both_classes=False, min_class_count=0)

    assert "Fictional safe message" not in str(raised.value)
