"""Local preflight checks for consented SMS batches.

This module reads private data only from the operator's local workspace. It
prints aggregate counts and row-number/rule findings, never message values.
Passing preflight is not proof of consent or complete de-identification; the
operator must still verify the separate consent register and human review.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.dataset_schema import LABEL_ALIASES, _normalized_message_key, make_group_key
from src.preprocess import MONEY_RE, PHONE_RE, URL_RE

REQUIRED_COLUMNS = (
    "label",
    "scam_assessment",
    "message",
    "data_kind",
    "source",
    "category",
    "language",
    "group",
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
    "reviewer_a_id",
    "reviewer_a_label",
    "reviewer_a_scam_assessment",
    "reviewer_a_label_confidence",
    "reviewer_b_id",
    "reviewer_b_label",
    "reviewer_b_scam_assessment",
    "reviewer_b_label_confidence",
    "adjudicator_id",
    "adjudicated_label",
    "adjudicated_scam_assessment",
    "adjudicated_label_confidence",
    "review_status",
)
CONSENT_SCOPES = {"training", "evaluation", "training_and_evaluation", "model_research"}
OPTIONAL_COLUMNS = {"received_at", "labeling_confidence"}
SCAM_ASSESSMENTS = {"suspected", "not_suspected", "unclear"}
REVIEW_CONFIDENCE = {"low", "medium", "high"}
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$", re.IGNORECASE)
SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$", re.IGNORECASE)
EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LONG_DIGITS_RE = re.compile(r"\d[\d\s-]{2,}\d")


@dataclass(frozen=True)
class Finding:
    """A privacy-safe validation finding; it deliberately has no raw value."""

    row: int
    rule: str


@dataclass(frozen=True)
class BatchReport:
    rows: int
    labels: dict[str, int]
    languages: dict[str, int]
    categories: dict[str, int]
    groups: int
    findings: tuple[Finding, ...]

    @property
    def valid(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "rows": self.rows,
            "labels": self.labels,
            "languages": self.languages,
            "categories": self.categories,
            "groups": self.groups,
            "findings": [asdict(item) for item in self.findings],
            "notice": (
                "Preflight checks do not prove consent or complete de-identification. "
                "Verify the separate consent register and reviewer records."
            ),
        }


def _norm_label(value: Any) -> str | None:
    return LABEL_ALIASES.get(str(value).strip().lower())


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _is_safe_id(value: str) -> bool:
    return bool(SAFE_ID.fullmatch(value) and re.search(r"[a-z]", value, re.IGNORECASE))


def _valid_iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        try:
            return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).date()
        except ValueError:
            return None


def normalize_intake_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with intake headers canonicalized to the schema names.

    Preflight and import must interpret column headers identically. Reject
    collisions (for example, ``Label`` alongside `` label ``) instead of
    silently choosing one of the values.
    """
    names = [str(column).strip().lower().replace(" ", "_") for column in frame.columns]
    if len(set(names)) != len(names):
        raise ValueError("The intake CSV has duplicate columns after normalization.")
    normalized = frame.copy()
    normalized.columns = names
    return normalized


def _content_findings(message: str, row_number: int) -> list[Finding]:
    findings: list[Finding] = []
    if PHONE_RE.search(message):
        findings.append(Finding(row_number, "possible_phone_number"))
    if EMAIL_RE.search(message):
        findings.append(Finding(row_number, "possible_email_address"))
    if URL_RE.search(message):
        findings.append(Finding(row_number, "unmasked_url"))

    # Long numeric identifiers and OTPs are flagged, while ordinary money
    # amounts may remain when they do not identify a person or transaction.
    money_spans = [match.span() for match in MONEY_RE.finditer(message)]
    digit_text = list(message)
    for start, end in money_spans:
        digit_text[start:end] = " " * (end - start)
    if LONG_DIGITS_RE.search("".join(digit_text)):
        findings.append(Finding(row_number, "possible_live_code_or_numeric_identifier"))
    return findings


def validate_batch(
    frame: pd.DataFrame,
    *,
    today: date | None = None,
    purpose: str | None = None,
) -> BatchReport:
    """Validate a de-identified intake batch without returning message values."""
    if purpose not in {None, "training", "evaluation"}:
        raise ValueError("purpose must be training or evaluation")
    today = today or datetime.now(UTC).date()
    canonical_frame = normalize_intake_columns(frame)
    normalized = dict(zip(canonical_frame.columns, frame.columns, strict=True))
    missing = sorted(set(REQUIRED_COLUMNS) - set(normalized))
    if missing:
        # Column names are schema, not message content.
        raise ValueError(f"Missing required intake columns: {', '.join(missing)}")
    if frame.empty:
        raise ValueError("The intake CSV has no data rows.")
    if set(normalized) - set(REQUIRED_COLUMNS) - OPTIONAL_COLUMNS:
        raise ValueError("The intake CSV has unsupported columns; remove fields not listed in the intake template.")
    if purpose == "evaluation" and "received_at" not in normalized:
        raise ValueError("Evaluation intake requires received_at dates for chronological campaign holdout.")

    findings: list[Finding] = []
    label_counts: dict[str, int] = {}
    language_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    group_ids: set[str] = set()
    message_keys: set[str] = set()
    template_groups: dict[str, list[tuple[int, str]]] = {}

    for row_offset, (_, row) in enumerate(frame.iterrows()):
        row_number = row_offset + 2
        values = {key: str(row[column]).strip() for key, column in normalized.items()}
        label = _norm_label(values["label"])
        if label is None:
            findings.append(Finding(row_number, "invalid_label"))
        else:
            label_counts[label] = label_counts.get(label, 0) + 1
        if values["data_kind"].lower() != "consented":
            findings.append(Finding(row_number, "data_kind_must_be_consented"))
        if not values["message"]:
            findings.append(Finding(row_number, "blank_message"))
        else:
            findings.extend(_content_findings(values["message"], row_number))
            message_key = _normalized_message_key(values["message"])
            if message_key in message_keys:
                findings.append(Finding(row_number, "duplicate_message_before_split"))
            message_keys.add(message_key)
            template_key = make_group_key(values["message"], category=values["category"])
            template_groups.setdefault(template_key, []).append((row_number, values["group"].casefold()))

        for field in ("source", "group", "consent_record_id", "reviewer_a_id", "reviewer_b_id"):
            if not _is_safe_id(values[field]):
                findings.append(Finding(row_number, f"invalid_or_non_pseudonymous_{field}"))
        if values["adjudicator_id"] and not _is_safe_id(values["adjudicator_id"]):
            findings.append(Finding(row_number, "invalid_or_non_pseudonymous_adjudicator_id"))
        group_ids.add(values["group"])
        if values["reviewer_a_id"].casefold() == values["reviewer_b_id"].casefold():
            findings.append(Finding(row_number, "reviewers_must_be_distinct"))
        if values["group"].casefold() == values["consent_record_id"].casefold():
            findings.append(Finding(row_number, "group_and_consent_record_ids_must_be_distinct"))

        if not _is_true(values["consent_verified"]):
            findings.append(Finding(row_number, "consent_not_verified_against_register"))
        if not _is_true(values["consent_active"]):
            findings.append(Finding(row_number, "consent_inactive_or_revoked"))
        if not _is_true(values["review_consent"]):
            findings.append(Finding(row_number, "review_consent_missing"))
        if not _is_true(values["authorized_to_share"]):
            findings.append(Finding(row_number, "sharing_authorization_missing"))
        if purpose is not None and not _is_true(values["model_research_consent"]):
            findings.append(Finding(row_number, "model_research_consent_missing"))
        if values["consent_scope"].lower() not in CONSENT_SCOPES:
            findings.append(Finding(row_number, "consent_scope_missing_or_invalid"))
        elif purpose == "training" and values["consent_scope"].lower() not in {
            "training",
            "training_and_evaluation",
            "model_research",
        }:
            findings.append(Finding(row_number, "consent_does_not_cover_training"))
        elif purpose == "evaluation" and values["consent_scope"].lower() not in {
            "evaluation",
            "training_and_evaluation",
            "model_research",
        }:
            findings.append(Finding(row_number, "consent_does_not_cover_evaluation"))
        if not SAFE_CODE.fullmatch(values["consent_version"]):
            findings.append(Finding(row_number, "consent_version_missing"))
        consent_date = _valid_iso_date(values["consent_date"])
        if consent_date is None or consent_date > today:
            findings.append(Finding(row_number, "consent_date_invalid"))
        retention_until = _valid_iso_date(values["retention_until"])
        if retention_until is None or retention_until < today:
            findings.append(Finding(row_number, "retention_expired_or_invalid"))
        if purpose == "evaluation" and not values.get("received_at", ""):
            findings.append(Finding(row_number, "received_at_required_for_evaluation"))
        elif (
            "received_at" in values
            and values["received_at"]
            and pd.isna(pd.to_datetime(values["received_at"], errors="coerce", utc=True))
        ):
            findings.append(Finding(row_number, "received_at_invalid"))
        if "labeling_confidence" in values and values["labeling_confidence"]:
            try:
                confidence = float(values["labeling_confidence"])
            except ValueError:
                confidence = -1.0
            if not 0.0 <= confidence <= 1.0:
                findings.append(Finding(row_number, "labeling_confidence_invalid"))

        reviewer_confidence = (
            values["reviewer_a_label_confidence"].lower(),
            values["reviewer_b_label_confidence"].lower(),
        )
        if any(confidence not in REVIEW_CONFIDENCE for confidence in reviewer_confidence):
            findings.append(Finding(row_number, "reviewer_confidence_invalid"))
        final_confidence = values["adjudicated_label_confidence"].lower()
        if final_confidence not in REVIEW_CONFIDENCE:
            findings.append(Finding(row_number, "label_confidence_invalid"))
        elif final_confidence == "low":
            findings.append(Finding(row_number, "low_confidence_review"))
        if values["review_status"].lower() != "adjudicated":
            findings.append(Finding(row_number, "review_not_adjudicated"))

        reviewer_a = _norm_label(values["reviewer_a_label"])
        reviewer_b = _norm_label(values["reviewer_b_label"])
        adjudicated = _norm_label(values["adjudicated_label"])
        if None in (reviewer_a, reviewer_b, adjudicated):
            findings.append(Finding(row_number, "two_review_labels_and_adjudication_required"))
        elif label is not None and adjudicated != label:
            findings.append(Finding(row_number, "label_must_match_adjudicated_label"))
        elif reviewer_a == reviewer_b and adjudicated != reviewer_a:
            findings.append(Finding(row_number, "adjudication_must_match_agreeing_reviewers"))
        elif reviewer_a != reviewer_b and (
            not values["adjudicator_id"]
            or values["adjudicator_id"].casefold()
            in {values["reviewer_a_id"].casefold(), values["reviewer_b_id"].casefold()}
        ):
            findings.append(Finding(row_number, "independent_adjudicator_required_for_disagreement"))
        elif reviewer_a != reviewer_b and adjudicated not in {reviewer_a, reviewer_b}:
            findings.append(Finding(row_number, "unresolved_label_disagreement"))

        scam_a = values["reviewer_a_scam_assessment"].lower()
        scam_b = values["reviewer_b_scam_assessment"].lower()
        scam_final = values["adjudicated_scam_assessment"].lower()
        scam_row = values["scam_assessment"].lower()
        for assessment in (scam_a, scam_b, scam_final, scam_row):
            if assessment not in SCAM_ASSESSMENTS:
                findings.append(Finding(row_number, "invalid_scam_assessment"))
                break
        if all(assessment in SCAM_ASSESSMENTS for assessment in (scam_a, scam_b, scam_final, scam_row)):
            if scam_row != scam_final:
                findings.append(Finding(row_number, "scam_assessment_must_match_adjudication"))
            if scam_a == scam_b and scam_final != scam_a:
                findings.append(Finding(row_number, "scam_adjudication_must_match_agreeing_reviewers"))
            elif scam_a != scam_b and (
                not values["adjudicator_id"]
                or values["adjudicator_id"].casefold()
                in {values["reviewer_a_id"].casefold(), values["reviewer_b_id"].casefold()}
            ):
                findings.append(Finding(row_number, "independent_scam_adjudicator_required"))

        for field in ("language", "category"):
            value = values[field] or "unknown"
            target = language_counts if field == "language" else category_counts
            if not SAFE_CODE.fullmatch(value):
                findings.append(Finding(row_number, f"invalid_or_non_categorical_{field}"))
                value = "unknown"
            target[value] = target.get(value, 0) + 1

    # Campaign IDs are operator-supplied and can accidentally split a single
    # message-template family. Keep the diagnostic content-free while blocking
    # these near-duplicates from crossing campaign/time partitions.
    for template_rows in template_groups.values():
        if len({group for _, group in template_rows}) > 1:
            findings.extend(
                Finding(row_number, "near_duplicate_template_spans_campaign_groups") for row_number, _ in template_rows
            )

    # Deduplicate identical row/rule reports without including offending values.
    unique_findings = tuple(sorted(set(findings), key=lambda item: (item.row, item.rule)))
    if purpose == "evaluation" and set(label_counts) != {"ham", "spam"}:
        unique_findings = (*unique_findings, Finding(0, "evaluation_batch_requires_both_labels"))
        unique_findings = tuple(sorted(set(unique_findings), key=lambda item: (item.row, item.rule)))
    return BatchReport(
        rows=len(frame),
        labels=label_counts,
        languages=language_counts,
        categories=category_counts,
        groups=len(group_ids - {""}),
        findings=unique_findings,
    )


def validate_csv(
    path: str | Path,
    *,
    today: date | None = None,
    purpose: str | None = None,
) -> BatchReport:
    """Read and validate a local CSV; pandas parse errors are sanitized."""
    try:
        _, frame = _read_intake_csv(path)
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"Could not read intake CSV ({type(exc).__name__}).") from None
    return validate_batch(frame, today=today, purpose=purpose)


def _read_intake_csv(path: str | Path) -> tuple[bytes, pd.DataFrame]:
    """Read one stable byte snapshot for validation, hashing, and import."""
    try:
        content = Path(path).read_bytes()
        frame = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False, encoding="utf-8-sig")
        return content, frame
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"Could not read intake CSV ({type(exc).__name__}).") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Privacy-safe local preflight for a consented SMS CSV.")
    parser.add_argument("csv", type=Path, help="Private, de-identified intake CSV (never commit it).")
    parser.add_argument("--purpose", required=True, choices=("training", "evaluation"))
    args = parser.parse_args(argv)
    try:
        report = validate_csv(args.csv, purpose=args.purpose)
    except ValueError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.valid else 1


if __name__ == "__main__":
    sys.exit(main())
