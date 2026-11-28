"""Turn a completed labeling worksheet into a validator-ready consented intake CSV.

Reads the coordinator's master labeling worksheet (the exact
``docs/templates/labeling-worksheet.md`` column set, plus an optional ``group``
column) together with JSON sidecars supplied by the coordinator, applies the
HUMAN_REVIEW adjudication rules in code, and writes a training-purpose intake
CSV that passes the strict ``src/consented_data.py`` gate. The validator is
never weakened: rows that cannot be made validator-clean are excluded from the
CSV and reported by worksheet row number and reason code -- nothing is ever
silently dropped, and no message text or ``label_hint`` value is ever echoed
into errors or the summary report. The ``label_hint`` column is required by the
master worksheet format but is deliberately never read or exported: the donor
hint is not ground truth and must never feed labeling or training.

Adjudication rules enforced here (docs/HUMAN_REVIEW.md, worksheet rules 2-5):

- the two first-pass reviewers are distinct pseudonymous ids (reviewer map);
- agreement rows must be adjudicated to the shared first-pass label;
- disagreement rows need an adjudicator who is neither first-pass reviewer and
  resolve to one of the two first-pass labels;
- reviewer and final confidence values are derived from the worksheet's
  ``labeling_confidence`` (>= 0.8 -> high, >= 0.5 -> medium, otherwise low;
  blank -> medium, never high). Mapped-low rows are excluded
  (``low_confidence_review``) per worksheet rule 5.
- the dated owner-adjudication exception (owner decision D2): the project owner
  may adjudicate a disagreement only while the exception is unexpired and only
  when the owner is one of the two first-pass reviewers (which is exactly when
  the adjudicator matches one of them). ``validate_batch`` has no exception
  hook -- owner-adjudicated disagreement rows cannot pass it -- so such rows
  are EXCLUDED from the intake CSV with reason code
  ``owner_adjudication_pending_independent_reviewer`` until a third independent
  reviewer is onboarded. An owner-adjudicated disagreement after the
  exception's ``expires_on`` date is a hard failure (the exception no longer
  exists) and nothing is written.

Sidecar JSON schemas (minimal, coordinator-supplied):

consent register (--consent-register), keyed by worksheet record_id, carrying
the consent fields of ``REQUIRED_COLUMNS`` per record:

    {"<record_id>": {
        "consent_record_id": "consent_a1b2c3d4e5f6",
        "consent_verified": true,
        "consent_active": true,
        "review_consent": true,
        "model_research_consent": true,
        "authorized_to_share": true,
        "consent_scope": "training_and_evaluation",
        "consent_version": "v1",
        "consent_date": "2026-11-01",
        "retention_until": "2027-11-01"}}

reviewer id map (--reviewer-map); pseudonymous reviewer ids only, never names:

    {"labeler_1": "reviewer_01", "labeler_2": "reviewer_02"}

scam assessments (--scam-assessments): the worksheet template carries no scam
columns, so the coordinator records the agreed scam assessment per record:

    {"default": "not_suspected", "overrides": {"<record_id>": "suspected"}}

One value per record fills all four scam columns (reviewer_a, reviewer_b,
adjudicated, final); reviewers therefore always agree on scam assessment,
which the validator accepts without independent scam adjudication.

owner exception (--owner-exception, optional; decision D2 / HUMAN_REVIEW.md):

    {"owner_reviewer_id": "reviewer_01", "expires_on": "YYYY-MM-DD"}

Output: one new 0600 CSV outside the repository (or under ignored
``data/donations/`` storage), created exclusively -- an existing file is never
overwritten. ``source`` defaults to the fixed pilot code ``pilot_round_1``;
``category`` is the constant ``unknown`` (the worksheet template has no
category column); ``group`` is the worksheet ``group`` column when present,
otherwise ``grp_`` + the first 12 ``record_id`` characters -- never derived
from message content. Exit codes: 0 when the intake CSV was produced and
passes ``validate_csv``; 1 for every tool failure (row-level exclusions are
reported and are not failures). All row numbers in reports refer to worksheet
lines: header = line 1, first data row = 2, matching ``validate_batch``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.consented_data import (
    CONSENT_SCOPES,
    REQUIRED_COLUMNS,
    SAFE_CODE,
    SCAM_ASSESSMENTS,
    _is_safe_id,
    _is_true,
    _norm_label,
    _valid_iso_date,
    normalize_intake_columns,
    validate_csv,
)
from src.dataset_schema import _normalized_message_key
from src.privacy.storage import ensure_private_directory

ROOT = Path(__file__).resolve().parents[1]

WORKSHEET_COLUMNS = (
    "record_id",
    "message",
    "label_hint",
    "language",
    "labeling_confidence",
    "labeler_1_label",
    "labeler_2_label",
    "adjudicated_label",
    "adjudicator",
)
WORKSHEET_GROUP_COLUMN = "group"
CONSENT_FIELDS = (
    "consent_record_id",
    "consent_verified",
    "consent_active",
    "review_consent",
    "model_research_consent",
    "authorized_to_share",
    "consent_scope",
    "consent_version",
    "consent_date",
    "retention_until",
)
CONSENT_FLAG_FIELDS = (
    "consent_verified",
    "consent_active",
    "review_consent",
    "model_research_consent",
    "authorized_to_share",
)
REVIEWER_MAP_KEYS = ("labeler_1", "labeler_2")

SOURCE_DEFAULT = "pilot_round_1"
PURPOSE = "training"
DEFAULT_CATEGORY = "unknown"
DEFAULT_LANGUAGE = "unknown"
CONFIDENCE_HIGH_MIN = 0.8
CONFIDENCE_MEDIUM_MIN = 0.5
DEFAULT_CONFIDENCE = "medium"

# Row-level exclusion reason codes. Codes that also exist in the validator are
# reused verbatim so worksheet exclusions and preflight findings read the same.
RECORD_ID_MISSING = "record_id_missing"
DUPLICATE_RECORD_ID = "duplicate_record_id"
BLANK_MESSAGE = "blank_message"
RECORD_MISSING_FROM_CONSENT_REGISTER = "record_missing_from_consent_register"
CONSENT_REGISTER_ENTRY_INCOMPLETE = "consent_register_entry_incomplete"
CONSENT_NOT_VERIFIED = "consent_not_verified_against_register"
CONSENT_INACTIVE = "consent_inactive_or_revoked"
REVIEW_CONSENT_MISSING = "review_consent_missing"
MODEL_RESEARCH_CONSENT_MISSING = "model_research_consent_missing"
SHARING_AUTHORIZATION_MISSING = "sharing_authorization_missing"
CONSENT_SCOPE_INVALID = "consent_scope_missing_or_invalid"
CONSENT_SCOPE_NOT_COVERING_PURPOSE = "consent_does_not_cover_training"
CONSENT_VERSION_INVALID = "consent_version_missing"
CONSENT_DATE_INVALID = "consent_date_invalid"
RETENTION_EXPIRED = "retention_expired_or_invalid"
TWO_REVIEW_LABELS_AND_ADJUDICATION_REQUIRED = "two_review_labels_and_adjudication_required"
ADJUDICATION_MUST_MATCH_AGREEING_REVIEWERS = "adjudication_must_match_agreeing_reviewers"
UNRESOLVED_LABEL_DISAGREEMENT = "unresolved_label_disagreement"
ADJUDICATOR_MISSING_FOR_DISAGREEMENT = "adjudicator_missing_for_disagreement"
ADJUDICATOR_NOT_INDEPENDENT = "adjudicator_not_independent"
OWNER_ADJUDICATION_PENDING_INDEPENDENT_REVIEWER = "owner_adjudication_pending_independent_reviewer"
OWNER_ADJUDICATION_EXCEPTION_EXPIRED = "owner_adjudication_exception_expired"
LABELING_CONFIDENCE_INVALID = "labeling_confidence_invalid"
LOW_CONFIDENCE_REVIEW = "low_confidence_review"
INVALID_LANGUAGE = "invalid_or_non_categorical_language"
INVALID_GROUP = "invalid_or_non_pseudonymous_group"
INVALID_ADJUDICATOR_ID = "invalid_or_non_pseudonymous_adjudicator_id"
GROUP_AND_CONSENT_RECORD_IDS_MUST_BE_DISTINCT = "group_and_consent_record_ids_must_be_distinct"
DUPLICATE_CONSENT_RECORD_ID = "duplicate_consent_record_id"
DUPLICATE_MESSAGE_BEFORE_SPLIT = "duplicate_message_before_split"

POLICY_NOTES = (
    "The label column equals adjudicated_label; the worksheet label_hint column is "
    "never read and never exported (the donor hint is not ground truth).",
    "labeling_confidence maps to all three reviewer-confidence fields: >=0.8 high, "
    ">=0.5 medium, otherwise low; blank maps to medium; mapped-low rows are excluded.",
    "group is the worksheet group column when present, otherwise grp_ plus the first "
    "12 record_id characters; it is never derived from message content.",
    "category is the constant 'unknown'; the worksheet template has no category column.",
    "One scam assessment per record fills all four scam columns, so reviewers agree on scam assessment.",
    "Owner-adjudicated disagreement rows are excluded "
    "(owner_adjudication_pending_independent_reviewer) until a third independent "
    "reviewer exists; owner adjudication after the exception expiry fails the import.",
)


@dataclass(frozen=True)
class Exclusion:
    """A privacy-safe worksheet exclusion; row number and reason code only."""

    row_number: int
    code: str


@dataclass(frozen=True)
class OwnerException:
    """Decision D2 record: dated owner-adjudication exception."""

    owner_reviewer_id: str
    expires_on: date


@dataclass(frozen=True)
class ScamAssessments:
    """Per-record scam assessment with a coordinator default."""

    default: str
    overrides: dict[str, str] = field(default_factory=dict)

    def for_record(self, record_id: str) -> str:
        return self.overrides.get(record_id, self.default)


class LabelImportError(Exception):
    """Fatal, message-free import failure carrying structured reasons only."""

    def __init__(self, code: str, reasons: list[dict[str, Any]] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.reasons = reasons or []


@dataclass
class IntakeBuild:
    """Everything the import step needs to write and verify the intake CSV."""

    frame: pd.DataFrame
    exclusions: list[Exclusion]
    confidence_counts: dict[str, int]
    worksheet_rows: list[int]


def _validate_output_path(output: str | os.PathLike[str]) -> Path:
    """Mirror export-donations: reject repo-tree paths, allow data/donations/."""
    destination = Path(output).expanduser().resolve()
    repository = ROOT.resolve()
    private_root = (repository / "data" / "donations").resolve()
    if repository in destination.parents and private_root not in destination.parents:
        raise ValueError("Intake CSVs must be outside the repository or under ignored data/donations/ storage.")
    return destination


def _read_json_sidecar(path: Path | None, role: str) -> Any:
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise LabelImportError("sidecar_unreadable", [{"sidecar": role}]) from None


def load_worksheet(path: str | Path) -> pd.DataFrame:
    """Load the master worksheet; the column set must match the template."""
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
        raise LabelImportError("worksheet_unreadable") from None
    try:
        frame = normalize_intake_columns(frame)
    except ValueError:
        raise LabelImportError("worksheet_duplicate_columns") from None
    names = set(frame.columns)
    allowed = set(WORKSHEET_COLUMNS)
    if names != allowed and names != allowed | {WORKSHEET_GROUP_COLUMN}:
        raise LabelImportError("worksheet_columns_do_not_match_template")
    return frame


def load_consent_register(payload: Any) -> dict[str, dict[str, str]]:
    """Validate the register export shape; per-entry completeness is row-level."""
    if not isinstance(payload, dict):
        raise LabelImportError("consent_register_schema_invalid")
    register: dict[str, dict[str, str]] = {}
    for record_id, entry in payload.items():
        if not isinstance(entry, dict):
            raise LabelImportError("consent_register_schema_invalid")
        register[str(record_id)] = {
            key: "" if entry.get(key) is None else str(entry.get(key)) for key in CONSENT_FIELDS
        }
    return register


def load_reviewer_map(payload: Any) -> dict[str, str]:
    """Reviewer ids must be pseudonymous and distinct; never real names."""
    if not isinstance(payload, dict) or any(key not in payload for key in REVIEWER_MAP_KEYS):
        raise LabelImportError("reviewer_map_schema_invalid")
    mapped = {key: str(payload[key]).strip() for key in REVIEWER_MAP_KEYS}
    for reviewer_id in mapped.values():
        if not _is_safe_id(reviewer_id):
            raise LabelImportError("reviewer_id_not_pseudonymous")
    if mapped["labeler_1"].casefold() == mapped["labeler_2"].casefold():
        raise LabelImportError("reviewer_ids_not_distinct")
    return mapped


def load_scam_assessments(payload: Any) -> ScamAssessments:
    """One assessment per record (or the default) from SCAM_ASSESSMENTS."""
    if not isinstance(payload, dict) or "default" not in payload:
        raise LabelImportError("scam_assessments_schema_invalid")
    default = str(payload["default"]).strip()
    overrides_raw = payload.get("overrides", {})
    if default not in SCAM_ASSESSMENTS or not isinstance(overrides_raw, dict):
        raise LabelImportError("scam_assessment_value_invalid")
    overrides = {str(key): str(value).strip() for key, value in overrides_raw.items()}
    if any(value not in SCAM_ASSESSMENTS for value in overrides.values()):
        raise LabelImportError("scam_assessment_value_invalid")
    return ScamAssessments(default=default, overrides=overrides)


def load_owner_exception(payload: Any) -> OwnerException | None:
    """Decision D2 record: the owner reviewer id and the dated expiry."""
    if payload is None:
        return None
    if not isinstance(payload, dict) or "owner_reviewer_id" not in payload or "expires_on" not in payload:
        raise LabelImportError("owner_exception_schema_invalid")
    owner_reviewer_id = str(payload["owner_reviewer_id"]).strip()
    if not _is_safe_id(owner_reviewer_id):
        raise LabelImportError("owner_reviewer_id_not_pseudonymous")
    expires_on = _valid_iso_date(payload["expires_on"])
    if expires_on is None:
        raise LabelImportError("owner_exception_schema_invalid")
    return OwnerException(owner_reviewer_id=owner_reviewer_id, expires_on=expires_on)


def map_confidence(raw: str) -> str | None:
    """Map the worksheet's labeling_confidence to low/medium/high (None: invalid)."""
    text = raw.strip()
    if not text:
        return DEFAULT_CONFIDENCE
    try:
        value = float(text)
    except ValueError:
        return None
    if not 0.0 <= value <= 1.0:
        return None
    if value >= CONFIDENCE_HIGH_MIN:
        return "high"
    if value >= CONFIDENCE_MEDIUM_MIN:
        return "medium"
    return "low"


def derive_group(record_id: str) -> str:
    """Deterministic per-record group from the record_id prefix, not content."""
    return f"grp_{record_id[:12].strip().lower()}"


def _consent_findings(entry: dict[str, str], today: date) -> list[str]:
    """Consent-register checks mirrored from validate_batch (training purpose)."""
    codes: list[str] = []
    flag_values = {field_name: _is_true(entry[field_name]) for field_name in CONSENT_FLAG_FIELDS}
    if not flag_values["consent_verified"]:
        codes.append(CONSENT_NOT_VERIFIED)
    if not flag_values["consent_active"]:
        codes.append(CONSENT_INACTIVE)
    if not flag_values["review_consent"]:
        codes.append(REVIEW_CONSENT_MISSING)
    if not flag_values["model_research_consent"]:
        codes.append(MODEL_RESEARCH_CONSENT_MISSING)
    if not flag_values["authorized_to_share"]:
        codes.append(SHARING_AUTHORIZATION_MISSING)
    scope = entry["consent_scope"].strip().lower()
    if scope not in CONSENT_SCOPES:
        codes.append(CONSENT_SCOPE_INVALID)
    elif scope not in {"training", "training_and_evaluation", "model_research"}:
        codes.append(CONSENT_SCOPE_NOT_COVERING_PURPOSE)
    if not SAFE_CODE.fullmatch(entry["consent_version"].strip()):
        codes.append(CONSENT_VERSION_INVALID)
    consent_date = _valid_iso_date(entry["consent_date"])
    if consent_date is None or consent_date > today:
        codes.append(CONSENT_DATE_INVALID)
    retention_until = _valid_iso_date(entry["retention_until"])
    if retention_until is None or retention_until < today:
        codes.append(RETENTION_EXPIRED)
    return codes


def _adjudication_findings(
    row_number: int,
    reviewer_labels: tuple[str | None, str | None],
    adjudicated: str | None,
    adjudicator: str,
    reviewer_ids: tuple[str, str],
    exception: OwnerException | None,
    today: date,
) -> list[str]:
    """Worksheet rule 2-4 checks plus the dated D2 owner exception.

    Fatal for an owner adjudication after expiry (the exception no longer
    exists); row-level exclusions otherwise, including owner-adjudicated
    disagreement rows, which the strict validator cannot accept.
    """
    reviewer_a, reviewer_b = reviewer_labels
    if reviewer_a is None or reviewer_b is None or adjudicated is None:
        return [TWO_REVIEW_LABELS_AND_ADJUDICATION_REQUIRED]
    codes: list[str] = []
    if reviewer_a == reviewer_b:
        if adjudicated != reviewer_a:
            codes.append(ADJUDICATION_MUST_MATCH_AGREEING_REVIEWERS)
        return codes
    # Disagreement: the final label must resolve to one of the first-pass
    # labels, and the adjudicator must be independent of both reviewers.
    if adjudicated not in (reviewer_a, reviewer_b):
        codes.append(UNRESOLVED_LABEL_DISAGREEMENT)
    if not adjudicator:
        codes.append(ADJUDICATOR_MISSING_FOR_DISAGREEMENT)
        return codes
    if adjudicator.casefold() in {reviewer_ids[0].casefold(), reviewer_ids[1].casefold()}:
        if exception is not None and adjudicator.casefold() == exception.owner_reviewer_id.casefold():
            if today > exception.expires_on:
                raise LabelImportError(
                    OWNER_ADJUDICATION_EXCEPTION_EXPIRED,
                    [{"row_number": row_number, "code": OWNER_ADJUDICATION_EXCEPTION_EXPIRED}],
                )
            codes.append(OWNER_ADJUDICATION_PENDING_INDEPENDENT_REVIEWER)
        else:
            codes.append(ADJUDICATOR_NOT_INDEPENDENT)
    return codes


def build_intake_frame(
    worksheet: pd.DataFrame,
    *,
    register: dict[str, dict[str, str]],
    reviewer_map: dict[str, str],
    scam: ScamAssessments,
    exception: OwnerException | None,
    source: str,
    today: date,
) -> IntakeBuild:
    """Apply the worksheet rules per row; return includable rows plus exclusions."""
    reviewer_a_id = reviewer_map["labeler_1"]
    reviewer_b_id = reviewer_map["labeler_2"]
    has_group_column = WORKSHEET_GROUP_COLUMN in worksheet.columns
    has_confidence_column = "labeling_confidence" in worksheet.columns
    exclusions: list[Exclusion] = []
    frame_rows: list[dict[str, str]] = []
    worksheet_rows: list[int] = []
    confidence_counts: dict[str, int] = {}
    used_record_ids: set[str] = set()
    used_message_keys: set[str] = set()
    used_consent_ids: set[str] = set()

    for offset, raw in enumerate(worksheet.iterrows()):
        row_number = offset + 2
        _, values = raw
        record_id = str(values["record_id"]).strip()
        if not record_id:
            exclusions.append(Exclusion(row_number, RECORD_ID_MISSING))
            continue
        codes: list[str] = []
        message = str(values["message"])
        if not message.strip():
            codes.append(BLANK_MESSAGE)

        group = str(values[WORKSHEET_GROUP_COLUMN]).strip() if has_group_column else ""
        group = group or derive_group(record_id)
        if not _is_safe_id(group):
            codes.append(INVALID_GROUP)

        entry = register.get(record_id)
        if entry is None:
            codes.append(RECORD_MISSING_FROM_CONSENT_REGISTER)
        elif any(not entry[field_name].strip() for field_name in CONSENT_FIELDS):
            codes.append(CONSENT_REGISTER_ENTRY_INCOMPLETE)
        else:
            codes.extend(_consent_findings(entry, today))
            if entry["consent_record_id"].strip().casefold() == group.casefold():
                codes.append(GROUP_AND_CONSENT_RECORD_IDS_MUST_BE_DISTINCT)

        reviewer_labels = (_norm_label(values["labeler_1_label"]), _norm_label(values["labeler_2_label"]))
        adjudicated = _norm_label(values["adjudicated_label"])
        adjudicator = str(values["adjudicator"]).strip()
        codes.extend(
            _adjudication_findings(
                row_number, reviewer_labels, adjudicated, adjudicator, (reviewer_a_id, reviewer_b_id), exception, today
            )
        )
        if adjudicator and not _is_safe_id(adjudicator):
            codes.append(INVALID_ADJUDICATOR_ID)

        confidence = (
            map_confidence(str(values.get("labeling_confidence", ""))) if has_confidence_column else DEFAULT_CONFIDENCE
        )
        if confidence is None:
            codes.append(LABELING_CONFIDENCE_INVALID)
        elif confidence == "low":
            codes.append(LOW_CONFIDENCE_REVIEW)

        language = str(values["language"]).strip() or DEFAULT_LANGUAGE
        if not SAFE_CODE.fullmatch(language):
            codes.append(INVALID_LANGUAGE)

        if codes:
            exclusions.extend(Exclusion(row_number, code) for code in codes)
            continue

        consent_record_id = entry["consent_record_id"].strip()
        message_key = _normalized_message_key(message)
        if record_id in used_record_ids:
            exclusions.append(Exclusion(row_number, DUPLICATE_RECORD_ID))
        elif message_key in used_message_keys:
            exclusions.append(Exclusion(row_number, DUPLICATE_MESSAGE_BEFORE_SPLIT))
        elif consent_record_id.casefold() in used_consent_ids:
            exclusions.append(Exclusion(row_number, DUPLICATE_CONSENT_RECORD_ID))
        else:
            scam_value = scam.for_record(record_id)
            row = {
                "label": str(adjudicated),
                "scam_assessment": scam_value,
                "message": message,
                "data_kind": "consented",
                "source": source,
                "category": DEFAULT_CATEGORY,
                "language": language,
                "group": group,
                "consent_record_id": consent_record_id,
                "consent_verified": "true" if _is_true(entry["consent_verified"]) else "false",
                "consent_active": "true" if _is_true(entry["consent_active"]) else "false",
                "review_consent": "true" if _is_true(entry["review_consent"]) else "false",
                "model_research_consent": "true" if _is_true(entry["model_research_consent"]) else "false",
                "authorized_to_share": "true" if _is_true(entry["authorized_to_share"]) else "false",
                "consent_scope": entry["consent_scope"].strip(),
                "consent_version": entry["consent_version"].strip(),
                "consent_date": entry["consent_date"].strip(),
                "retention_until": entry["retention_until"].strip(),
                "reviewer_a_id": reviewer_a_id,
                "reviewer_a_label": str(reviewer_labels[0]),
                "reviewer_a_scam_assessment": scam_value,
                "reviewer_a_label_confidence": confidence,
                "reviewer_b_id": reviewer_b_id,
                "reviewer_b_label": str(reviewer_labels[1]),
                "reviewer_b_scam_assessment": scam_value,
                "reviewer_b_label_confidence": confidence,
                "adjudicator_id": adjudicator,
                "adjudicated_label": str(adjudicated),
                "adjudicated_scam_assessment": scam_value,
                "adjudicated_label_confidence": confidence,
                "review_status": "adjudicated",
            }
            if has_confidence_column:
                row["labeling_confidence"] = str(values["labeling_confidence"])
            frame_rows.append(row)
            worksheet_rows.append(row_number)
            used_record_ids.add(record_id)
            used_message_keys.add(message_key)
            used_consent_ids.add(consent_record_id.casefold())
            if confidence is not None:
                confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1

    columns = list(REQUIRED_COLUMNS) + (["labeling_confidence"] if has_confidence_column else [])
    frame = pd.DataFrame(frame_rows, columns=columns)
    return IntakeBuild(
        frame=frame,
        exclusions=exclusions,
        confidence_counts=confidence_counts,
        worksheet_rows=worksheet_rows,
    )


def write_intake_csv(frame: pd.DataFrame, destination: Path) -> None:
    """Create the intake CSV exclusively with private permissions (never overwrites).

    Mirrors ``api.donations.export_donations``: exclusive create, owner-only file
    mode, private parent directory, and a partial-file cleanup that never
    removes a pre-existing file.
    """
    ensure_private_directory(destination.parent)
    payload = frame.to_csv(index=False, lineterminator="\n")
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise
    except OSError:
        raise LabelImportError("could_not_write_output") from None
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        except OSError:
            with contextlib.suppress(OSError):
                destination.unlink()
            raise LabelImportError("could_not_write_output") from None
    os.chmod(destination, 0o600)


def _translate_findings(report: Any, worksheet_rows: list[int]) -> list[dict[str, Any]]:
    """Express validator findings as worksheet row numbers and codes only."""
    translated: list[dict[str, Any]] = []
    for finding in report.findings:
        row_number = finding.row
        if 2 <= row_number < len(worksheet_rows) + 2:
            row_number = worksheet_rows[row_number - 2]
        translated.append({"row_number": row_number, "code": finding.rule})
    return translated


def run_import(args: argparse.Namespace) -> dict[str, Any]:
    """Import the worksheet; return a message-free summary report."""
    today = args.today or datetime.now(UTC).date()
    destination = _validate_output_path(args.output)
    source = args.source
    if not _is_safe_id(source):
        raise LabelImportError("invalid_source_code")

    worksheet = load_worksheet(args.worksheet)
    register = load_consent_register(_read_json_sidecar(args.consent_register, "consent_register"))
    reviewer_map = load_reviewer_map(_read_json_sidecar(args.reviewer_map, "reviewer_map"))
    scam = load_scam_assessments(_read_json_sidecar(args.scam_assessments, "scam_assessments"))
    exception = load_owner_exception(_read_json_sidecar(args.owner_exception, "owner_exception"))

    build = build_intake_frame(
        worksheet,
        register=register,
        reviewer_map=reviewer_map,
        scam=scam,
        exception=exception,
        source=source,
        today=today,
    )
    exclusions = [{"row_number": item.row_number, "code": item.code} for item in build.exclusions]
    if build.frame.empty:
        raise LabelImportError("no_importable_rows", exclusions)

    try:
        write_intake_csv(build.frame, destination)
    except FileExistsError:
        raise LabelImportError("output_file_already_exists") from None
    except OSError as exc:
        raise LabelImportError("could_not_write_output", [{"os_error": type(exc).__name__}]) from None
    try:
        report = validate_csv(destination, today=today, purpose=PURPOSE)
    except ValueError:
        raise LabelImportError("output_validation_unreadable") from None
    if not report.valid:
        with contextlib.suppress(OSError):
            destination.unlink()
        raise LabelImportError("validation_failed", _translate_findings(report, build.worksheet_rows))

    summary = {
        "status": "imported",
        "output": str(destination),
        "purpose": PURPOSE,
        "source": source,
        "worksheet_rows": int(len(worksheet)),
        "included_rows": int(len(build.frame)),
        "excluded_rows": exclusions,
        "reviewer_ids": {"reviewer_a": reviewer_map["labeler_1"], "reviewer_b": reviewer_map["labeler_2"]},
        "confidence_map": dict(sorted(build.confidence_counts.items())),
        "policy_notes": list(POLICY_NOTES),
    }
    _assert_report_message_free(summary, worksheet)
    return summary


def _assert_report_message_free(summary: dict[str, Any], worksheet: pd.DataFrame) -> None:
    """Refuse to print a summary that carries message or label_hint values."""
    forbidden = {
        str(value) for column in ("message", "label_hint") if column in worksheet.columns for value in worksheet[column]
    }
    forbidden = {value for value in forbidden if value.strip()}
    serialized = json.dumps(summary, sort_keys=True)
    if any(value in serialized for value in forbidden):
        raise LabelImportError("report_safety_check_failed")


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError("--today must be an ISO date (YYYY-MM-DD)") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--worksheet", type=Path, required=True, help="Completed master labeling worksheet CSV.")
    parser.add_argument(
        "--consent-register", type=Path, required=True, help="Consent register export JSON keyed by record_id."
    )
    parser.add_argument(
        "--reviewer-map",
        type=Path,
        required=True,
        help="JSON mapping labeler_1/labeler_2 to pseudonymous reviewer ids.",
    )
    parser.add_argument(
        "--scam-assessments",
        type=Path,
        required=True,
        help="JSON scam assessments: {'default': ..., 'overrides': {...}}.",
    )
    parser.add_argument(
        "--owner-exception",
        type=Path,
        default=None,
        help="Optional D2 owner-adjudication exception JSON: {'owner_reviewer_id': ..., 'expires_on': 'YYYY-MM-DD'}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New CSV destination outside the repository or under ignored data/donations/ storage.",
    )
    parser.add_argument("--source", default=SOURCE_DEFAULT, help="Fixed pseudonymous source code for the pilot batch.")
    parser.add_argument(
        "--today", type=_iso_date, default=None, help="ISO date used for expiry/retention checks (default: today)."
    )
    args = parser.parse_args(argv)

    try:
        summary = run_import(args)
    except LabelImportError as exc:
        payload = {"status": "import_failed", "code": exc.code, "reasons": exc.reasons, "output_written": False}
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    except ValueError as exc:
        payload = {
            "status": "import_failed",
            "code": "invalid_output_path",
            "detail": str(exc),
            "output_written": False,
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
