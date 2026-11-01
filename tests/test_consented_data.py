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
        "scam_assessment": "not_suspected",
        "data_kind": "consented",
        "source": "consented_batch_01",
        "category": "school_work",
        "language": "en",
        "group": "campaign_001",
        "consent_record_id": "consent_001",
        "consent_verified": "true",
        "consent_active": "true",
        "review_consent": "true",
        "model_research_consent": "true",
        "authorized_to_share": "true",
        "consent_scope": "training_and_evaluation",
        "consent_version": "v1",
        "consent_date": "2026-01-15",
        "retention_until": "2027-01-15",
        "reviewer_a_id": "reviewer_a",
        "reviewer_a_label": "ham",
        "reviewer_a_scam_assessment": "not_suspected",
        "reviewer_a_label_confidence": "high",
        "reviewer_b_id": "reviewer_b",
        "reviewer_b_label": "ham",
        "reviewer_b_scam_assessment": "not_suspected",
        "reviewer_b_label_confidence": "high",
        "adjudicator_id": "",
        "adjudicated_label": "ham",
        "adjudicated_scam_assessment": "not_suspected",
        "adjudicated_label_confidence": "high",
        "review_status": "adjudicated",
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


def test_near_duplicate_template_families_cannot_cross_campaign_groups() -> None:
    first = valid_batch_row(
        message="Your account service notification is ready for review today.",
        group="campaign_001",
    )
    second = valid_batch_row(
        message="Your account service notification is ready for review now!",
        group="campaign_002",
        consent_record_id="consent_002",
    )

    report = validate_batch(pd.DataFrame([first, second]), today=date(2026, 10, 21))

    assert {item.rule for item in report.findings} == {"near_duplicate_template_spans_campaign_groups"}


def test_unknown_or_unverified_consent_scope_is_rejected() -> None:
    row = valid_batch_row(consent_verified="false", consent_scope="product_marketing")
    report = validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21))
    rules = {finding.rule for finding in report.findings}

    assert "consent_not_verified_against_register" in rules
    assert "consent_scope_missing_or_invalid" in rules


def test_consent_scope_must_cover_the_requested_use() -> None:
    row = valid_batch_row(consent_scope="training", received_at="2026-01-14T12:00:00Z")
    report = validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21), purpose="evaluation")
    assert "consent_does_not_cover_evaluation" in {item.rule for item in report.findings}


def test_each_research_use_requires_share_review_and_model_research_consent() -> None:
    for field, expected_rule in (
        ("review_consent", "review_consent_missing"),
        ("authorized_to_share", "sharing_authorization_missing"),
        ("model_research_consent", "model_research_consent_missing"),
    ):
        report = validate_batch(
            pd.DataFrame([valid_batch_row(**{field: "false", "received_at": "2026-01-14T12:00:00Z"})]),
            today=date(2026, 10, 21),
            purpose="evaluation",
        )
        assert expected_rule in {item.rule for item in report.findings}


def test_intake_template_schema_is_explicit() -> None:
    template = pd.read_csv("data/templates/consented_ph_sms_template.csv", nrows=0)
    assert tuple(template.columns[:-1]) == REQUIRED_COLUMNS
    assert template.columns[-1] == "received_at"


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


def test_reviewer_input_rejects_model_outputs() -> None:
    frame = pd.DataFrame([valid_batch_row()]).assign(model_score="0.99")

    with pytest.raises(ValueError, match="unsupported columns"):
        validate_batch(frame, today=date(2026, 11, 1))


def test_spam_label_is_independent_from_scam_assessment_and_has_review_confidence():
    row = valid_batch_row(
        label="spam",
        reviewer_a_label="spam",
        reviewer_b_label="spam",
        adjudicated_label="spam",
        scam_assessment="not_suspected",
    )

    report = validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21))

    assert report.valid
    assert report.labels == {"spam": 1}


def test_scam_assessment_disagreement_needs_independent_adjudication():
    row = valid_batch_row(
        scam_assessment="unclear",
        reviewer_a_scam_assessment="suspected",
        reviewer_b_scam_assessment="not_suspected",
        adjudicated_scam_assessment="unclear",
        adjudicator_id="reviewer_c",
    )

    assert validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21)).valid

    row["adjudicator_id"] = "reviewer_a"
    report = validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21))
    assert "independent_scam_adjudicator_required" in {item.rule for item in report.findings}


def test_unresolved_or_low_confidence_reviews_are_not_model_ready():
    row = valid_batch_row(adjudicated_label_confidence="low", review_status="unresolved")

    report = validate_batch(pd.DataFrame([row]), today=date(2026, 10, 21))

    assert not report.valid
    assert {item.rule for item in report.findings} >= {"review_not_adjudicated", "low_confidence_review"}


def test_normalized_duplicate_messages_are_rejected_before_splitting():
    first = valid_batch_row()
    second = valid_batch_row(message="  class STARTS at nine tomorrow; see you there. ")

    report = validate_batch(pd.DataFrame([first, second]), today=date(2026, 10, 21))

    assert "duplicate_message_before_split" in {item.rule for item in report.findings}


def test_evaluation_intake_requires_real_dates_for_temporal_holdout():
    with pytest.raises(ValueError, match="received_at"):
        validate_batch(pd.DataFrame([valid_batch_row()]), today=date(2026, 10, 21), purpose="evaluation")
