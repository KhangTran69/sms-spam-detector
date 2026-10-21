"""Privacy-safe preflight tests for the local consented-data workflow."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.consented_data import REQUIRED_COLUMNS, validate_batch, validate_csv


def valid_batch_row(**overrides: str) -> dict[str, str]:
    row = {
        "label": "ham",
        "message": "Class starts at nine tomorrow; see you there.",
        "data_kind": "consented",
        "source": "consented_batch_01",
        "category": "school_work",
        "language": "en",
        "group": "donor_001_campaign_a",
        "consent_record_id": "consent_001",
        "consent_verified": "true",
        "consent_active": "true",
        "consent_scope": "training_and_evaluation",
        "consent_version": "v1",
        "consent_date": "2026-01-15",
        "retention_until": "2027-01-15",
        "reviewer_a_id": "reviewer_a",
        "reviewer_a_label": "ham",
        "reviewer_b_id": "reviewer_b",
        "reviewer_b_label": "ham",
        "adjudicator_id": "",
        "adjudicated_label": "ham",
    }
    row.update(overrides)
    return row


def test_valid_intake_reports_aggregate_metadata_only() -> None:
    report = validate_batch(pd.DataFrame([valid_batch_row()]), today=date(2026, 10, 21))

    assert report.valid
    assert report.rows == 1
    assert report.labels == {"ham": 1}
    assert report.languages == {"en": 1}
    assert report.categories == {"school_work": 1}
    assert report.groups == 1
    assert "message" not in str(report.as_dict())


def test_residual_personal_values_are_flagged_without_echoing_message(tmp_path) -> None:
    private_message = "Call +639171234567; visit secure.example.com and use code 987654."
    path = tmp_path / "private.csv"
    pd.DataFrame([valid_batch_row(message=private_message)]).to_csv(path, index=False)

    report = validate_csv(path, today=date(2026, 10, 21))
    serialized = str(report.as_dict())

    assert not report.valid
    assert {finding.rule for finding in report.findings} >= {
        "possible_phone_number",
        "unmasked_url",
        "possible_live_code_or_numeric_identifier",
    }
    assert private_message not in serialized
    assert "+639171234567" not in serialized
    assert "secure.example.com" not in serialized
    assert "987654" not in serialized


def test_short_numeric_otp_is_also_flagged_for_masking() -> None:
    report = validate_batch(
        pd.DataFrame([valid_batch_row(message="Your verification code is 1234")]),
        today=date(2026, 10, 21),
    )
    assert "possible_live_code_or_numeric_identifier" in {item.rule for item in report.findings}


def test_expired_consent_and_revocation_block_intake() -> None:
    frame = pd.DataFrame(
        [
            valid_batch_row(consent_active="false", retention_until="2026-10-20"),
        ]
    )

    report = validate_batch(frame, today=date(2026, 10, 21))
    rules = {finding.rule for finding in report.findings}

    assert "consent_inactive_or_revoked" in rules
    assert "retention_expired_or_invalid" in rules


def test_reviewer_disagreement_requires_independent_adjudicator() -> None:
    row = valid_batch_row(reviewer_a_label="ham", reviewer_b_label="spam", adjudicated_label="ham")
    report = validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21))
    assert "independent_adjudicator_required_for_disagreement" in {item.rule for item in report.findings}

    row["adjudicator_id"] = "reviewer_c"
    assert validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21)).valid


def test_split_group_key_is_separate_from_consent_record_key() -> None:
    row = valid_batch_row(group="consent_001")
    report = validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21))
    assert "group_and_consent_record_ids_must_be_distinct" in {item.rule for item in report.findings}


def test_unknown_or_unverified_consent_scope_is_rejected() -> None:
    row = valid_batch_row(consent_verified="false", consent_scope="product_marketing")
    report = validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21))
    rules = {finding.rule for finding in report.findings}

    assert "consent_not_verified_against_register" in rules
    assert "consent_scope_missing_or_invalid" in rules


def test_consent_scope_must_cover_the_requested_use() -> None:
    row = valid_batch_row(consent_scope="training")
    report = validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21), purpose="evaluation")
    assert "consent_does_not_cover_evaluation" in {item.rule for item in report.findings}


def test_intake_template_schema_is_explicit() -> None:
    template = pd.read_csv("data/templates/consented_ph_sms_template.csv", nrows=0)
    assert tuple(template.columns) == REQUIRED_COLUMNS


def test_free_text_category_metadata_is_not_echoed_in_aggregate_report() -> None:
    report = validate_batch(
        pd.DataFrame([valid_batch_row(category="Khang Tran")]),
        today=date(2026, 10, 21),
    )
    serialized = str(report.as_dict())

    assert "invalid_or_non_categorical_category" in serialized
    assert "Khang Tran" not in serialized
    assert report.categories == {"unknown": 1}


def test_numeric_contact_value_cannot_be_used_as_an_identifier() -> None:
    report = validate_batch(
        pd.DataFrame([valid_batch_row(consent_record_id="09171234567")]),
        today=date(2026, 10, 21),
    )

    assert "invalid_or_non_pseudonymous_consent_record_id" in {item.rule for item in report.findings}


def test_unreviewed_extra_metadata_columns_are_rejected() -> None:
    frame = pd.DataFrame([valid_batch_row()])
    frame["unreviewed_private_notes"] = "participant name must not appear in reports"

    with pytest.raises(ValueError, match="unsupported columns") as raised:
        validate_batch(frame, today=date(2026, 10, 21))
    assert "participant name" not in str(raised.value)
