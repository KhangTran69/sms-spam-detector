"""Labeling-worksheet import tests with synthetic fixtures only.

The worksheet importer (scripts/label_import.py) must turn completed labeling
worksheets into intake CSVs that pass the strict consented validator, enforce
the HUMAN_REVIEW adjudication rules and the dated owner-adjudication exception
in code, exclude anything that cannot be made validator-clean with a reason
code, and never export the label_hint column or echo message text.

Every message below is a tracked synthetic fixture (no digits, no domains, no
senders, nothing real), and every reviewer/adjudicator id is pseudonymous.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts.label_import import (
    OWNER_ADJUDICATION_EXCEPTION_EXPIRED,
    OWNER_ADJUDICATION_PENDING_INDEPENDENT_REVIEWER,
    _validate_output_path,
    main,
)
from src.consented_data import REQUIRED_COLUMNS, validate_csv

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 28)

RECORD_A = "a1b2c3d4e5f6a7b8a9b0c1d2e3f4a5b6"
RECORD_B = "b2c3d4e5f6a7b8a9b0c1d2e3f4a5b6a1"
RECORD_C = "c3d4e5f6a7b8a9b0c1d2e3f4a5b6a1b2"
RECORD_D = "d4e5f6a7b8a9b0c1d2e3f4a5b6a1b2c3"
RECORD_E = "e5f6a7b8a9b0c1d2e3f4a5b6a1b2c3d4"
RECORD_F = "f6a7b8a9b0c1d2e3f4a5b6a1b2c3d4e5"
RECORD_G = "0aaabbbb000100000000000000000001"
RECORD_H = "0aaabbbb000200000000000000000002"
RECORD_I = "0aaabbbb000300000000000000000003"

# Synthetic fixtures only: no digits, no domains, no senders, nothing real.
MSG_A = "Synthetic pilot fixture one: routine bank alert template for reviewer training only."
MSG_B = "Synthetic pilot fixture two: unsolicited promotion claim template for reviewer training only."
MSG_C = "Synthetic pilot fixture three: unsolicited promotion claim variant for reviewer training only."
MSG_D = "Synthetic pilot fixture four: routine delivery update template for reviewer training only."
MSG_E = "Synthetic pilot fixture five: routine utility notice template for reviewer training only."
MSG_F = "Synthetic pilot fixture six: unsolicited prize claim template for reviewer training only."
MSG_URL = "Synthetic test only: inspect https://sms-link.example before sharing."
HINT_MARKER = "HINT-MARKER-NOT-A-LABEL"
FORBIDDEN_TEXTS = (MSG_A, MSG_B, MSG_C, MSG_D, MSG_E, MSG_F, MSG_URL, HINT_MARKER)

REVIEWERS = {"labeler_1": "reviewer_01", "labeler_2": "reviewer_02"}
OWNER_EXCEPTION = {"owner_reviewer_id": "reviewer_01", "expires_on": "2026-12-15"}


def _assert_message_free(text: str) -> None:
    for forbidden in FORBIDDEN_TEXTS:
        assert forbidden not in text


def _entry(record_id: str = RECORD_A, **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "consent_record_id": f"consent_{record_id[:12]}",
        "consent_verified": True,
        "consent_active": True,
        "review_consent": True,
        "model_research_consent": True,
        "authorized_to_share": True,
        "consent_scope": "training_and_evaluation",
        "consent_version": "v1",
        "consent_date": "2026-11-01",
        "retention_until": "2027-11-01",
    }
    entry.update(overrides)
    return entry


def _row(
    record_id: str,
    message: str,
    *,
    labeler_1: str = "ham",
    labeler_2: str = "ham",
    adjudicated: str = "ham",
    adjudicator: str = "",
    hint: str = "ham",
    language: str = "en",
    confidence: str = "0.9",
    group: str | None = None,
) -> dict[str, str]:
    row = {
        "record_id": record_id,
        "message": message,
        "label_hint": hint,
        "language": language,
        "labeling_confidence": confidence,
        "labeler_1_label": labeler_1,
        "labeler_2_label": labeler_2,
        "adjudicated_label": adjudicated,
        "adjudicator": adjudicator,
    }
    if group is not None:
        row["group"] = group
    return row


def _register(rows: list[dict[str, str]]) -> dict[str, dict[str, object]]:
    return {row["record_id"]: _entry(row["record_id"]) for row in rows if row["record_id"].strip()}


def _write_sidecars(
    tmp_path: Path,
    rows: list[dict[str, str]],
    register: dict[str, dict[str, object]] | None = None,
    *,
    reviewers: dict[str, str] | None = REVIEWERS,
    scam: dict[str, object] | None = None,
    exception: dict[str, str] | None = None,
    worksheet: pd.DataFrame | None = None,
) -> list[str]:
    frame = worksheet if worksheet is not None else pd.DataFrame(rows)
    worksheet_path = tmp_path / "worksheet.csv"
    frame.to_csv(worksheet_path, index=False)
    consent_path = tmp_path / "consent.json"
    consent_path.write_text(json.dumps(register if register is not None else _register(rows)), encoding="utf-8")
    reviewer_path = tmp_path / "reviewers.json"
    reviewer_path.write_text(json.dumps(reviewers), encoding="utf-8")
    scam_path = tmp_path / "scam.json"
    scam_path.write_text(json.dumps(scam or {"default": "not_suspected"}), encoding="utf-8")
    argv = [
        "--worksheet",
        str(worksheet_path),
        "--consent-register",
        str(consent_path),
        "--reviewer-map",
        str(reviewer_path),
        "--scam-assessments",
        str(scam_path),
        "--output",
        str(tmp_path / "intake.csv"),
        "--today",
        TODAY.isoformat(),
    ]
    if exception is not None:
        exception_path = tmp_path / "owner-exception.json"
        exception_path.write_text(json.dumps(exception), encoding="utf-8")
        argv += ["--owner-exception", str(exception_path)]
    return argv


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_agreement_rows_produce_a_validator_passing_intake_csv(tmp_path, capsys) -> None:
    rows = [
        _row(RECORD_A, MSG_A),
        _row(RECORD_B, MSG_B, labeler_1="spam", labeler_2="spam", adjudicated="spam"),
    ]
    argv = _write_sidecars(tmp_path, rows, scam={"default": "not_suspected", "overrides": {RECORD_B: "suspected"}})

    assert main(argv) == 0
    output = tmp_path / "intake.csv"
    frame = _read_csv(output)
    assert list(frame.columns) == list(REQUIRED_COLUMNS) + ["labeling_confidence"]
    assert len(frame) == 2
    first, second = frame.iloc[0], frame.iloc[1]
    assert first["label"] == first["adjudicated_label"] == "ham"
    assert first["data_kind"] == "consented" and first["review_status"] == "adjudicated"
    assert first["source"] == "pilot_round_1" and first["category"] == "unknown"
    assert first["group"] == "grp_a1b2c3d4e5f6"
    assert first["reviewer_a_id"] == "reviewer_01" and first["reviewer_b_id"] == "reviewer_02"
    assert first["adjudicator_id"] == ""
    assert first["scam_assessment"] == "not_suspected" and first["adjudicated_scam_assessment"] == "not_suspected"
    for field in ("reviewer_a_label_confidence", "reviewer_b_label_confidence", "adjudicated_label_confidence"):
        assert first[field] == "high"
    assert second["label"] == "spam"
    for field in (
        "scam_assessment",
        "reviewer_a_scam_assessment",
        "reviewer_b_scam_assessment",
        "adjudicated_scam_assessment",
    ):
        assert second[field] == "suspected"
    assert validate_csv(output, today=TODAY, purpose="training").valid
    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    assert summary["included_rows"] == 2 and summary["excluded_rows"] == []
    _assert_message_free(stdout)


def test_disagreement_with_independent_adjudicator_is_imported(tmp_path, capsys) -> None:
    rows = [
        _row(RECORD_A, MSG_A),
        _row(RECORD_C, MSG_C, labeler_1="spam", labeler_2="ham", adjudicated="spam", adjudicator="reviewer_03"),
    ]

    assert main(_write_sidecars(tmp_path, rows)) == 0
    frame = _read_csv(tmp_path / "intake.csv")
    assert len(frame) == 2
    disagreement = frame.iloc[1]
    assert disagreement["adjudicator_id"] == "reviewer_03"
    assert disagreement["label"] == disagreement["adjudicated_label"] == "spam"
    assert disagreement["reviewer_a_label"] == "spam" and disagreement["reviewer_b_label"] == "ham"
    assert validate_csv(tmp_path / "intake.csv", today=TODAY, purpose="training").valid
    assert json.loads(capsys.readouterr().out)["excluded_rows"] == []


def test_owner_adjudicated_disagreement_inside_expiry_is_excluded_with_reason(tmp_path, capsys) -> None:
    rows = [
        _row(RECORD_A, MSG_A),
        _row(RECORD_B, MSG_B, labeler_1="spam", labeler_2="ham", adjudicated="spam", adjudicator="reviewer_01"),
        _row(RECORD_C, MSG_C, labeler_1="spam", labeler_2="spam", adjudicated="spam"),
    ]
    # Boundary: the expiry day itself is still inside the dated exception.
    for expires_on in ("2026-12-15", TODAY.isoformat()):
        argv = _write_sidecars(tmp_path, rows, exception={**OWNER_EXCEPTION, "expires_on": expires_on})
        output = tmp_path / f"intake-{expires_on}.csv"
        argv[argv.index("--output") + 1] = str(output)

        assert main(argv) == 0
        summary = json.loads(capsys.readouterr().out)
        assert summary["excluded_rows"] == [{"row_number": 3, "code": OWNER_ADJUDICATION_PENDING_INDEPENDENT_REVIEWER}]
        frame = _read_csv(output)
        assert len(frame) == 2
        assert list(frame["message"]) == [MSG_A, MSG_C]
        assert validate_csv(output, today=TODAY, purpose="training").valid
        _assert_message_free(json.dumps(summary))


def test_owner_adjudication_after_expiry_fails_without_writing_output(tmp_path, capsys) -> None:
    rows = [_row(RECORD_B, MSG_B, labeler_1="spam", labeler_2="ham", adjudicated="spam", adjudicator="reviewer_01")]
    output = tmp_path / "intake.csv"
    argv = _write_sidecars(tmp_path, rows, exception={**OWNER_EXCEPTION, "expires_on": "2026-11-27"})
    argv[argv.index("--output") + 1] = str(output)

    assert main(argv) == 1
    captured = capsys.readouterr()
    assert not output.exists()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["status"] == "import_failed"
    assert payload["code"] == OWNER_ADJUDICATION_EXCEPTION_EXPIRED
    assert payload["reasons"] == [{"row_number": 2, "code": OWNER_ADJUDICATION_EXCEPTION_EXPIRED}]
    _assert_message_free(captured.err)


def test_owner_adjudication_expiry_is_enforced_through_today_override(tmp_path, capsys) -> None:
    rows = [_row(RECORD_B, MSG_B, labeler_1="spam", labeler_2="ham", adjudicated="spam", adjudicator="reviewer_01")]
    argv = _write_sidecars(tmp_path, rows, exception=OWNER_EXCEPTION)
    argv[argv.index("--today") + 1] = "2026-12-16"

    assert main(argv) == 1
    captured = capsys.readouterr()
    assert not (tmp_path / "intake.csv").exists()
    assert json.loads(captured.err)["code"] == OWNER_ADJUDICATION_EXCEPTION_EXPIRED
    _assert_message_free(captured.err)


def test_owner_adjudication_with_owner_outside_the_reviewer_pair_is_independent(tmp_path, capsys) -> None:
    # The D2 exception applies only while the owner is one of the two
    # first-pass reviewers; an owner adjudicating from outside the pair is the
    # ordinary independent-adjudicator rule and imports without exclusions.
    rows = [_row(RECORD_A, MSG_A, labeler_1="spam", labeler_2="ham", adjudicated="spam", adjudicator="reviewer_09")]
    argv = _write_sidecars(tmp_path, rows, exception={"owner_reviewer_id": "reviewer_09", "expires_on": "2020-01-01"})

    assert main(argv) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["excluded_rows"] == []
    frame = _read_csv(tmp_path / "intake.csv")
    assert frame.iloc[0]["adjudicator_id"] == "reviewer_09"
    assert validate_csv(tmp_path / "intake.csv", today=TODAY, purpose="training").valid


def test_label_hint_is_never_exported_and_never_becomes_the_label(tmp_path, capsys) -> None:
    rows = [
        _row(RECORD_A, MSG_A, hint=HINT_MARKER),
        _row(RECORD_B, MSG_B, hint="spam"),
        _row(RECORD_C, MSG_C, hint="ham", labeler_1="spam", labeler_2="spam", adjudicated="spam"),
    ]

    assert main(_write_sidecars(tmp_path, rows)) == 0
    stdout = capsys.readouterr().out
    output = tmp_path / "intake.csv"
    text = output.read_text(encoding="utf-8")
    assert "label_hint" not in text
    assert HINT_MARKER not in text and HINT_MARKER not in stdout
    assert list(_read_csv(output)["label"]) == ["ham", "ham", "spam"]


def test_intake_csv_is_created_exclusively_with_private_permissions(tmp_path, capsys) -> None:
    argv = _write_sidecars(tmp_path, [_row(RECORD_A, MSG_A)])
    output = tmp_path / "intake.csv"

    assert main(argv) == 0
    capsys.readouterr()
    assert validate_csv(output, today=TODAY, purpose="training").valid
    if os.name == "posix":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
        assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    first_bytes = output.read_bytes()

    assert main(argv) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.err)["code"] == "output_file_already_exists"
    assert output.read_bytes() == first_bytes
    assert validate_csv(output, today=TODAY, purpose="training").valid


def test_rows_failing_validation_are_a_failure_with_row_numbers_and_no_message_text(tmp_path, capsys) -> None:
    rows = [_row(RECORD_A, MSG_A), _row(RECORD_B, MSG_URL)]
    output = tmp_path / "intake.csv"
    argv = _write_sidecars(tmp_path, rows)
    argv[argv.index("--output") + 1] = str(output)

    assert main(argv) == 1
    captured = capsys.readouterr()
    assert not output.exists()
    payload = json.loads(captured.err)
    assert payload["code"] == "validation_failed"
    assert payload["reasons"] == [{"row_number": 3, "code": "unmasked_url"}]
    _assert_message_free(captured.err)


def test_output_path_protection_rejects_repository_paths(tmp_path, capsys) -> None:
    with pytest.raises(ValueError):
        _validate_output_path(ROOT / "intake.csv")
    with pytest.raises(ValueError):
        _validate_output_path(ROOT / "data" / "processed" / "intake.csv")
    assert _validate_output_path(tmp_path / "intake.csv") == (tmp_path / "intake.csv").resolve()
    assert (
        _validate_output_path(ROOT / "data" / "donations" / "intake.csv")
        == (ROOT / "data" / "donations" / "intake.csv").resolve()
    )
    assert _validate_output_path(ROOT / "data" / "donations" / "rounds" / "intake.csv").name == "intake.csv"

    output = ROOT / "intake-should-never-exist.csv"
    argv = _write_sidecars(tmp_path, [_row(RECORD_A, MSG_A)])
    argv[argv.index("--output") + 1] = str(output)

    assert main(argv) == 1
    captured = capsys.readouterr()
    assert not output.exists()
    assert json.loads(captured.err)["code"] == "invalid_output_path"
    _assert_message_free(captured.err)


def test_worksheet_field_defects_are_excluded_with_reason_codes(tmp_path, capsys) -> None:
    rows = [
        _row("", MSG_A),
        _row(RECORD_B, ""),
        _row(RECORD_C, MSG_C, adjudicated="maybe"),
        _row(RECORD_D, MSG_D, labeler_1="spam", labeler_2="ham", adjudicated="spam", adjudicator=""),
        _row(RECORD_E, MSG_E, labeler_1="spam", labeler_2="ham", adjudicated="spam", adjudicator="reviewer_02"),
        _row(RECORD_F, MSG_F, adjudicated="spam"),
        _row(RECORD_A, MSG_A),
    ]
    assert main(_write_sidecars(tmp_path, rows)) == 0
    summary = json.loads(capsys.readouterr().out)

    codes = {(item["row_number"], item["code"]) for item in summary["excluded_rows"]}
    assert (2, "record_id_missing") in codes
    assert (3, "blank_message") in codes
    assert (4, "two_review_labels_and_adjudication_required") in codes
    assert (5, "adjudicator_missing_for_disagreement") in codes
    assert (6, "adjudicator_not_independent") in codes
    assert (7, "adjudication_must_match_agreeing_reviewers") in codes
    assert summary["included_rows"] == 1
    frame = _read_csv(tmp_path / "intake.csv")
    assert list(frame["message"]) == [MSG_A]
    assert validate_csv(tmp_path / "intake.csv", today=TODAY, purpose="training").valid


def test_consent_register_gaps_are_excluded_with_validator_codes(tmp_path, capsys) -> None:
    rows = [
        _row(RECORD_A, MSG_A),
        _row(RECORD_B, MSG_B),
        _row(RECORD_C, MSG_C),
        _row(RECORD_D, MSG_D),
        _row(RECORD_E, MSG_E),
        _row(RECORD_F, MSG_F),
        _row(RECORD_G, MSG_A),
        _row(RECORD_H, MSG_D),
        _row(RECORD_I, MSG_C),
    ]
    register = {
        RECORD_B: _entry(RECORD_B, consent_active=False),
        RECORD_C: _entry(RECORD_C, consent_scope="evaluation"),
        RECORD_D: _entry(RECORD_D, retention_until="2026-01-01"),
        RECORD_E: _entry(RECORD_E, model_research_consent=False),
        RECORD_F: _entry(RECORD_F, consent_verified=False),
        RECORD_G: _entry(RECORD_G, consent_date="2026-12-25"),
        RECORD_H: _entry(RECORD_H, consent_version="not a safe code!!"),
        RECORD_I: _entry(RECORD_I),
    }
    assert main(_write_sidecars(tmp_path, rows, register=register)) == 0
    summary = json.loads(capsys.readouterr().out)

    codes = {(item["row_number"], item["code"]) for item in summary["excluded_rows"]}
    assert (2, "record_missing_from_consent_register") in codes
    assert (3, "consent_inactive_or_revoked") in codes
    assert (4, "consent_does_not_cover_training") in codes
    assert (5, "retention_expired_or_invalid") in codes
    assert (6, "model_research_consent_missing") in codes
    assert (7, "consent_not_verified_against_register") in codes
    assert (8, "consent_date_invalid") in codes
    assert (9, "consent_version_missing") in codes
    assert summary["included_rows"] == 1
    assert validate_csv(tmp_path / "intake.csv", today=TODAY, purpose="training").valid


def test_duplicate_records_messages_and_consent_ids_are_excluded(tmp_path, capsys) -> None:
    rows = [_row(RECORD_A, MSG_A), _row(RECORD_B, MSG_A), _row(RECORD_C, MSG_B)]
    register = _register(rows)
    register[RECORD_C] = {**_entry(RECORD_A), "consent_record_id": "consent_a1b2c3d4e5f6"}

    assert main(_write_sidecars(tmp_path, rows, register=register)) == 0
    summary = json.loads(capsys.readouterr().out)

    codes = {(item["row_number"], item["code"]) for item in summary["excluded_rows"]}
    assert (3, "duplicate_message_before_split") in codes
    assert (4, "duplicate_consent_record_id") in codes
    assert summary["included_rows"] == 1
    assert validate_csv(tmp_path / "intake.csv", today=TODAY, purpose="training").valid


def test_confidence_mapping_and_low_confidence_exclusion(tmp_path, capsys) -> None:
    rows = [
        _row(RECORD_A, MSG_A, confidence="0.9"),
        _row(RECORD_B, MSG_B, confidence="0.55"),
        _row(RECORD_C, MSG_C, confidence="0.3"),
        _row(RECORD_D, MSG_D, confidence=""),
        _row(RECORD_E, MSG_E, confidence="abc"),
        _row(RECORD_F, MSG_F, confidence="1.5"),
    ]
    assert main(_write_sidecars(tmp_path, rows)) == 0
    summary = json.loads(capsys.readouterr().out)
    frame = _read_csv(tmp_path / "intake.csv")

    codes = {(item["row_number"], item["code"]) for item in summary["excluded_rows"]}
    assert (4, "low_confidence_review") in codes
    assert (6, "labeling_confidence_invalid") in codes
    assert (7, "labeling_confidence_invalid") in codes
    assert summary["included_rows"] == 3
    assert summary["confidence_map"] == {"high": 1, "medium": 2}
    assert list(frame["labeling_confidence"]) == ["0.9", "0.55", ""]
    assert list(frame["reviewer_a_label_confidence"]) == ["high", "medium", "medium"]
    assert list(frame["adjudicated_label_confidence"]) == ["high", "medium", "medium"]
    assert validate_csv(tmp_path / "intake.csv", today=TODAY, purpose="training").valid


def test_group_uses_worksheet_column_or_record_id_prefix(tmp_path, capsys) -> None:
    rows = [_row(RECORD_A, MSG_A), _row(RECORD_B, MSG_B, group="camp_alpha_01"), _row(RECORD_C, MSG_C, group="x")]

    assert main(_write_sidecars(tmp_path, rows)) == 0
    summary = json.loads(capsys.readouterr().out)
    frame = _read_csv(tmp_path / "intake.csv")

    assert (4, "invalid_or_non_pseudonymous_group") in {(i["row_number"], i["code"]) for i in summary["excluded_rows"]}
    assert list(frame["group"]) == ["grp_a1b2c3d4e5f6", "camp_alpha_01"]
    assert all(group != consent for group, consent in zip(frame["group"], frame["consent_record_id"], strict=False))
    assert validate_csv(tmp_path / "intake.csv", today=TODAY, purpose="training").valid


def test_unparseable_reviewer_labels_are_excluded(tmp_path, capsys) -> None:
    rows = [_row(RECORD_A, MSG_A, labeler_2="unsure"), _row(RECORD_B, MSG_B)]

    assert main(_write_sidecars(tmp_path, rows)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["excluded_rows"] == [{"row_number": 2, "code": "two_review_labels_and_adjudication_required"}]
    assert summary["included_rows"] == 1
    assert validate_csv(tmp_path / "intake.csv", today=TODAY, purpose="training").valid


def test_sidecar_and_worksheet_schema_failures(tmp_path, capsys) -> None:
    rows = [_row(RECORD_A, MSG_A)]
    cases = [
        ({"reviewers": {"labeler_1": "reviewer_01", "labeler_2": "reviewer_01"}}, "reviewer_ids_not_distinct"),
        ({"reviewers": {"labeler_1": "reviewer 1!", "labeler_2": "reviewer_02"}}, "reviewer_id_not_pseudonymous"),
        ({"scam": {"default": "maybe"}}, "scam_assessment_value_invalid"),
        ({"scam": {"default": "not_suspected", "overrides": {RECORD_A: "perhaps"}}}, "scam_assessment_value_invalid"),
        (
            {"exception": {"owner_reviewer_id": "reviewer_01", "expires_on": "15/12/2026"}},
            "owner_exception_schema_invalid",
        ),
        (
            {"exception": {"owner_reviewer_id": "the owner!", "expires_on": "2026-12-15"}},
            "owner_reviewer_id_not_pseudonymous",
        ),
        ({"register": [RECORD_A]}, "consent_register_schema_invalid"),
    ]
    for overrides, expected_code in cases:
        sidecars: dict[str, object] = {"register": _register(rows), **overrides}
        argv = _write_sidecars(tmp_path, rows, **sidecars)
        capsys.readouterr()
        assert main(argv) == 1, expected_code
        captured = capsys.readouterr()
        assert not (tmp_path / "intake.csv").exists()
        assert json.loads(captured.err)["code"] == expected_code
        _assert_message_free(captured.err)

    capsys.readouterr()
    extra_column = pd.DataFrame([{**_row(RECORD_A, MSG_A), "sender": "nope"}])
    assert main(_write_sidecars(tmp_path, rows, register=_register(rows), worksheet=extra_column)) == 1
    assert json.loads(capsys.readouterr().err)["code"] == "worksheet_columns_do_not_match_template"

    missing_hint = pd.DataFrame([{key: value for key, value in _row(RECORD_A, MSG_A).items() if key != "label_hint"}])
    assert main(_write_sidecars(tmp_path, rows, register=_register(rows), worksheet=missing_hint)) == 1
    assert json.loads(capsys.readouterr().err)["code"] == "worksheet_columns_do_not_match_template"

    argv = _write_sidecars(tmp_path, rows)
    argv[argv.index("--reviewer-map") + 1] = str(tmp_path / "missing.json")
    assert main(argv) == 1
    assert json.loads(capsys.readouterr().err)["code"] == "sidecar_unreadable"

    argv = _write_sidecars(tmp_path, rows)
    argv += ["--source", "pilot round!"]
    assert main(argv) == 1
    assert json.loads(capsys.readouterr().err)["code"] == "invalid_source_code"


def test_no_importable_rows_is_a_failure_listing_the_exclusions(tmp_path, capsys) -> None:
    rows = [
        _row(RECORD_A, MSG_A),
        _row(RECORD_B, MSG_B, labeler_1="spam", labeler_2="ham", adjudicated="spam", adjudicator="reviewer_01"),
    ]
    output = tmp_path / "intake.csv"
    argv = _write_sidecars(tmp_path, rows, register={RECORD_B: _entry(RECORD_B)}, exception=OWNER_EXCEPTION)
    argv[argv.index("--output") + 1] = str(output)

    assert main(argv) == 1
    captured = capsys.readouterr()
    assert not output.exists()
    payload = json.loads(captured.err)
    assert payload["code"] == "no_importable_rows"
    assert payload["reasons"] == [
        {"row_number": 2, "code": "record_missing_from_consent_register"},
        {"row_number": 3, "code": OWNER_ADJUDICATION_PENDING_INDEPENDENT_REVIEWER},
    ]
    _assert_message_free(captured.err)
