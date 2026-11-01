"""Run a disposable, synthetic rehearsal of the consented-study workflow.

This command uses only generated fictional messages. Its temporary donation
database, reviewer sheets, split files, model, plan, and reports are deleted
before it prints a content-free summary. It is an engineering rehearsal, not
consented participant data or Philippine performance evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from api.donations import create_donation, export_donations
from src.consented_data import REQUIRED_COLUMNS, validate_batch
from src.consented_split import split_consented_dataset
from src.privacy.scrub import detect_pii
from src.public_evaluation import evaluate_public_dataset
from src.train import train

SYNTHETIC_CAMPAIGNS = 64
MESSAGES_PER_CAMPAIGN = 4
NOTICE_VERSION = "rehearsal-v1"
LANGUAGES = ("en", "fil", "tl-en")
VARIANTS = ("one", "two", "three", "four")
_ASSESSMENT_COLUMNS = (
    "record_id",
    "message",
    "label",
    "scam_assessment",
    "category",
    "language",
    "label_confidence",
)


class RehearsalError(RuntimeError):
    """A content-free failure that identifies only the failed workflow stage."""

    def __init__(self, stage: str):
        self.stage = stage
        super().__init__(f"Synthetic consented-study rehearsal failed at {stage}.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _campaign_code(index: int) -> str:
    value = index
    letters: list[str] = []
    while True:
        letters.append(chr(ord("a") + value % 26))
        value //= 26
        if value == 0:
            break
        value -= 1
    return "camp" + "".join(reversed(letters))


def _message(campaign_index: int, variant_index: int, label: str) -> str:
    campaign = _campaign_code(campaign_index)
    variant = VARIANTS[variant_index]
    if label == "spam":
        body = f"Synthetic offer {campaign} unsolicited promotion claim variant {variant} has no trusted sender."
    else:
        body = f"Synthetic bulletin {campaign} routine bank alert variant {variant} is ready for review."
    if campaign_index == 0 and variant_index == 0:
        body += " reviewer-two-disagreement"
    return body


def _classify_synthetic_message(message: str) -> str:
    return "spam" if "unsolicited promotion claim" in message else "ham"


def _category_for_message(message: str) -> str:
    return "promotion" if "unsolicited promotion claim" in message else "bank_alert"


def _write_private_csv(path: Path, rows: list[dict[str, str]], fieldnames: tuple[str, ...]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())


def _create_synthetic_donations(
    database: Path,
    *,
    today: date,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Create generated donations and an in-memory synthetic consent register."""
    rejected_message = "Synthetic test only: inspect https://sms-link.example before sharing."
    if not any(span.category == "url" for span in detect_pii(rejected_message, strict=True)):
        raise RehearsalError("pii_screen")
    try:
        create_donation(
            database,
            message=rejected_message,
            label_hint=None,
            language="en",
            notice_version=NOTICE_VERSION,
            review_consent=True,
            authorized_to_share=True,
            model_research_consent=True,
        )
    except ValueError:
        pass
    else:
        raise RehearsalError("pii_screen")
    if database.exists():
        raise RehearsalError("pii_screen")

    created: dict[str, dict[str, Any]] = {}
    consent_register: dict[str, dict[str, Any]] = {}
    accepted_at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=5)
    for campaign_index in range(SYNTHETIC_CAMPAIGNS):
        expected = "ham" if campaign_index % 2 == 0 else "spam"
        for variant_index in range(MESSAGES_PER_CAMPAIGN):
            message = _message(campaign_index, variant_index, expected)
            language = LANGUAGES[(campaign_index + variant_index) % len(LANGUAGES)]
            record_id = create_donation(
                database,
                message=message,
                label_hint="spam" if expected == "ham" else "ham",
                language=language,
                notice_version=NOTICE_VERSION,
                review_consent=True,
                authorized_to_share=True,
                model_research_consent=True,
                consented_at=accepted_at,
            )
            expiry = (accepted_at + timedelta(days=90)).date()
            created[record_id] = {
                "campaign_index": campaign_index,
                "expected_label": expected,
                "received_at": (today - timedelta(days=SYNTHETIC_CAMPAIGNS - campaign_index)).isoformat()
                + "T12:00:00Z",
            }
            consent_register[record_id] = {
                "notice_version": NOTICE_VERSION,
                "consent_date": accepted_at.date().isoformat(),
                "retention_until": expiry.isoformat(),
                "review_consent": True,
                "model_research_consent": True,
                "authorized_to_share": True,
                "consent_scope": "model_research",
                "active": True,
            }
    return created, consent_register


def _run_reviewer(
    review_rows: list[dict[str, str]],
    reviewer_id: str,
    output_path: Path,
) -> None:
    """Label one isolated sheet without access to other reviews or model output."""
    labels: list[dict[str, str]] = []
    for row in review_rows:
        message = row["message"]
        label = _classify_synthetic_message(message)
        if reviewer_id == "reviewer_b" and "reviewer-two-disagreement" in message:
            label = "spam" if label == "ham" else "ham"
        labels.append(
            {
                "record_id": row["record_id"],
                "message": message,
                "label": label,
                "scam_assessment": "not_suspected",
                "category": _category_for_message(message),
                "language": row["language"],
                "label_confidence": "high",
            }
        )
    _write_private_csv(output_path, labels, _ASSESSMENT_COLUMNS)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _combine_reviews(
    export_rows: list[dict[str, str]],
    reviewer_a: list[dict[str, str]],
    reviewer_b: list[dict[str, str]],
    created: dict[str, dict[str, Any]],
    consent_register: dict[str, dict[str, Any]],
    *,
    today: date,
) -> tuple[pd.DataFrame, int]:
    first = {row["record_id"]: row for row in reviewer_a}
    second = {row["record_id"]: row for row in reviewer_b}
    if len(first) != len(reviewer_a) or len(second) != len(reviewer_b):
        raise RehearsalError("independent_review")
    if set(first) != set(second) or set(first) != {row["record_id"] for row in export_rows}:
        raise RehearsalError("independent_review")

    reviewed_rows: list[dict[str, str]] = []
    adjudications = 0
    for staged in export_rows:
        record_id = staged["record_id"]
        review_a = first[record_id]
        review_b = second[record_id]
        expected = created[record_id]
        consent = consent_register.get(record_id)
        if consent is None or not consent["active"]:
            raise RehearsalError("consent_preflight")
        if not all(
            consent[field] is True for field in ("review_consent", "model_research_consent", "authorized_to_share")
        ):
            raise RehearsalError("consent_preflight")
        if consent["consent_scope"] != "model_research" or consent["retention_until"] < today.isoformat():
            raise RehearsalError("consent_preflight")
        if any(
            set(row) & {"label_hint", "model_score", "spam_probability", "prediction"} for row in (review_a, review_b)
        ):
            raise RehearsalError("independent_review")

        disagrees = review_a["label"] != review_b["label"]
        if disagrees:
            adjudications += 1
            final_label = _classify_synthetic_message(staged["message"])
            adjudicator_id = "reviewer_c"
        else:
            final_label = review_a["label"]
            adjudicator_id = ""
        if final_label != expected["expected_label"]:
            raise RehearsalError("independent_review")

        output = {column: "" for column in REQUIRED_COLUMNS}
        output.update(
            {
                "label": final_label,
                "scam_assessment": "not_suspected",
                "message": staged["message"],
                "data_kind": "consented",
                "source": "synthetic_rehearsal",
                "category": review_a["category"],
                "language": staged["language"],
                "group": f"campaign_{expected['campaign_index']:03d}",
                "consent_record_id": record_id,
                "consent_verified": "true",
                "consent_active": "true",
                "review_consent": "true",
                "model_research_consent": "true",
                "authorized_to_share": "true",
                "consent_scope": consent["consent_scope"],
                "consent_version": consent["notice_version"],
                "consent_date": consent["consent_date"],
                "retention_until": consent["retention_until"],
                "reviewer_a_id": "reviewer_a",
                "reviewer_a_label": review_a["label"],
                "reviewer_a_scam_assessment": review_a["scam_assessment"],
                "reviewer_a_label_confidence": review_a["label_confidence"],
                "reviewer_b_id": "reviewer_b",
                "reviewer_b_label": review_b["label"],
                "reviewer_b_scam_assessment": review_b["scam_assessment"],
                "reviewer_b_label_confidence": review_b["label_confidence"],
                "adjudicator_id": adjudicator_id,
                "adjudicated_label": final_label,
                "adjudicated_scam_assessment": "not_suspected",
                "adjudicated_label_confidence": "high",
                "review_status": "adjudicated",
                "received_at": expected["received_at"],
            }
        )
        reviewed_rows.append(output)
    return pd.DataFrame(reviewed_rows), adjudications


def _consent_controls_pass(frame: pd.DataFrame, *, today: date) -> dict[str, bool]:
    sample = frame.iloc[[0]].copy()
    try:
        validate_batch(sample.drop(columns=["consent_active"]), today=today, purpose="training")
    except ValueError:
        missing_blocks = True
    else:
        missing_blocks = False

    withdrawn = sample.copy()
    withdrawn["consent_active"] = "false"
    withdrawn_rules = {item.rule for item in validate_batch(withdrawn, today=today, purpose="training").findings}

    expired = sample.copy()
    expired["retention_until"] = (today - timedelta(days=1)).isoformat()
    expired_rules = {item.rule for item in validate_batch(expired, today=today, purpose="training").findings}

    insufficient = sample.copy()
    insufficient["consent_scope"] = "training"
    scope_rules = {item.rule for item in validate_batch(insufficient, today=today, purpose="evaluation").findings}
    return {
        "missing_blocks": missing_blocks,
        "withdrawn_blocks": "consent_inactive_or_revoked" in withdrawn_rules,
        "expired_blocks": "retention_expired_or_invalid" in expired_rules,
        "insufficient_scope_blocks": "consent_does_not_cover_evaluation" in scope_rules,
    }


def _evaluation_plan(
    *,
    development: dict[str, Any],
    sealed_test: dict[str, Any],
    model_hash: str,
    model_version: str,
    threshold: float,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "registered_at": datetime.now(UTC).isoformat(),
        "intended_use": "Synthetic workflow rehearsal only; no participant or performance claim.",
        "dataset_sha256": sealed_test["sha256"],
        "training_dataset_sha256": development["sha256"],
        "training_membership_sha256": development["membership_sha256"],
        "test_membership_sha256": sealed_test["membership_sha256"],
        "model_sha256": model_hash,
        "model_version": model_version,
        "decision_threshold": threshold,
        "split_method": "chronological_campaign_holdout",
        "campaign_overlap_checked": True,
        "test_split_sealed": True,
        "minimum_campaign_groups": 10,
        "coverage_rationale": (
            "Synthetic fixture contract only: exercise one record in each generated language and category. "
            "This is not a human-study coverage target."
        ),
        "uncertainty_rationale": (
            "Synthetic fixture contract only: permit wide intervals while testing the evaluator path. "
            "This is not an acceptable uncertainty policy for a real study."
        ),
        "minimum_coverage": {
            "language": {"en": 1, "fil": 1, "tl-en": 1},
            "category": {"bank_alert": 1, "promotion": 1},
        },
        "maximum_cluster_interval_width": {
            "precision": 0.99,
            "recall": 0.99,
            "f1": 0.99,
            "false_positive_rate": 0.99,
            "false_negative_rate": 0.99,
        },
    }


def run_synthetic_rehearsal() -> dict[str, Any]:
    """Run intake through one hash-bound evaluation with disposable fixtures."""
    stage = "temporary_workspace"
    temporary_root: Path | None = None
    summary: dict[str, Any]
    try:
        with tempfile.TemporaryDirectory(prefix="smsd-synthetic-rehearsal-") as workspace:
            temporary_root = Path(workspace)
            workspace_path = temporary_root
            database = workspace_path / "donations.sqlite3"
            today = datetime.now(UTC).date()

            stage = "synthetic_donation"
            created, consent_register = _create_synthetic_donations(database, today=today)
            if len(created) != SYNTHETIC_CAMPAIGNS * MESSAGES_PER_CAMPAIGN:
                raise RehearsalError(stage)

            stage = "review_only_export"
            staging_path = workspace_path / "review-staging.csv"
            export_counts = export_donations(database, staging_path)
            export_rows = _read_rows(staging_path)
            staging_fields = set(export_rows[0]) if export_rows else set()
            if (
                not export_rows
                or any(row["label"] or row["eligible_for_modeling"] != "false" for row in export_rows)
                or "label_hint" in staging_fields
            ):
                raise RehearsalError(stage)
            if len(export_rows) != export_counts["exported"]:
                raise RehearsalError(stage)

            stage = "independent_review"
            reviewer_inputs = [
                {"record_id": row["record_id"], "message": row["message"], "language": row["language"]}
                for row in export_rows
            ]
            reviewer_a_dir = workspace_path / "reviewer-a"
            reviewer_b_dir = workspace_path / "reviewer-b"
            reviewer_a_dir.mkdir(mode=0o700)
            reviewer_b_dir.mkdir(mode=0o700)
            reviewer_a_path = reviewer_a_dir / "first-pass.csv"
            reviewer_b_path = reviewer_b_dir / "first-pass.csv"
            _run_reviewer(reviewer_inputs, "reviewer_a", reviewer_a_path)
            _run_reviewer(reviewer_inputs, "reviewer_b", reviewer_b_path)
            reviewer_a_rows = _read_rows(reviewer_a_path)
            reviewer_b_rows = _read_rows(reviewer_b_path)
            output_fields = set(reviewer_a_rows[0]) | set(reviewer_b_rows[0])
            if output_fields & {"label_hint", "model_score", "spam_probability", "prediction"}:
                raise RehearsalError(stage)
            reviewed, adjudications = _combine_reviews(
                export_rows,
                reviewer_a_rows,
                reviewer_b_rows,
                created,
                consent_register,
                today=today,
            )
            reviewed_path = workspace_path / "approved-reviewed-synthetic.csv"
            reviewed.to_csv(reviewed_path, index=False, lineterminator="\n")
            os.chmod(reviewed_path, 0o600)

            stage = "consent_preflight"
            training_preflight = validate_batch(reviewed, today=today, purpose="training")
            evaluation_preflight = validate_batch(reviewed, today=today, purpose="evaluation")
            consent_controls = _consent_controls_pass(reviewed, today=today)
            if not training_preflight.valid or not evaluation_preflight.valid or not all(consent_controls.values()):
                raise RehearsalError(stage)

            stage = "campaign_time_split"
            development_dir = workspace_path / "development"
            sealed_dir = workspace_path / "sealed-test"
            split_result = split_consented_dataset(
                reviewed_path,
                development_output_dir=development_dir,
                evaluation_output_dir=sealed_dir,
                validation_size=0.15,
                test_size=0.15,
                seed=42,
            )
            development_path = development_dir / split_result["development"]["filename"]
            manifest = json.loads((development_dir / split_result["manifest"]).read_text(encoding="utf-8"))
            development_info = manifest["development"]
            sealed_info = manifest["sealed_evaluation"]
            split_details = manifest["split"]
            if (
                split_result["split_method"] != "chronological_group_holdout"
                or split_details["group_leakage"] != 0
                or split_details["cross_split_duplicate_preflight"] != "passed"
                or split_details["temporal_ordering"] != "chronological_campaign_holdout"
            ):
                raise RehearsalError(stage)

            stage = "development_only_training"
            model_path = workspace_path / "candidate-model.pkl"
            artifact = train(
                data_path=development_path,
                model_path=model_path,
                supplement_path=None,
                holdout_path=None,
                val_size=0.15,
                test_size=0.15,
                random_state=42,
                split_by="time",
                strict_data=True,
                model_version="synthetic-rehearsal-v1",
                threshold_policy="validation",
                write_metadata=False,
                verbose=False,
            )
            if (
                not model_path.is_file()
                or artifact["training_config"]["threshold_policy"] != "validation"
                or artifact["training_config"]["split_by"] != "time"
            ):
                raise RehearsalError(stage)
            model_hash = _sha256(model_path)
            plan = _evaluation_plan(
                development=development_info,
                sealed_test=sealed_info,
                model_hash=model_hash,
                model_version=str(artifact["model_version"]),
                threshold=float(artifact["threshold"]),
            )
            plan_path = workspace_path / "registered-synthetic-plan.json"
            plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.chmod(plan_path, 0o600)

            stage = "sealed_test_evaluation"
            evaluation_path = sealed_dir / sealed_info["filename"]
            evaluation = evaluate_public_dataset(
                evaluation_path,
                model_path,
                workspace_path / "reports",
                evaluation_plan_path=plan_path,
                training_data_path=development_path,
                synthetic_rehearsal=True,
            )
            if evaluation["status"] != "evaluated" or evaluation["dataset"]["kind"] != "synthetic_rehearsal":
                raise RehearsalError(stage)

            evaluation_metrics = evaluation["metrics"]
            summary = {
                "status": "completed",
                "evidence_class": "synthetic_rehearsal",
                "intake": {
                    "synthetic_submissions": export_counts["exported"],
                    "explicit_consent": True,
                    "reserved_example_url_rejected": True,
                    "consent_controls": consent_controls,
                },
                "review": {
                    "reviewer_count": 2,
                    "blind": True,
                    "donor_hints_used_as_labels": False,
                    "model_results_exposed_to_reviewers": False,
                    "adjudications": adjudications,
                    "rows_adjudicated": len(reviewed),
                },
                "preflight": {
                    "training_valid": training_preflight.valid,
                    "evaluation_valid": evaluation_preflight.valid,
                },
                "split": {
                    "method": split_result["split_method"],
                    "development_rows": development_info["rows"],
                    "sealed_test_rows": sealed_info["rows"],
                    "development_campaign_groups": development_info["campaign_groups"],
                    "sealed_test_campaign_groups": sealed_info["campaign_groups"],
                    "campaign_group_overlap": split_details["group_leakage"],
                    "cross_split_duplicate_preflight": split_details["cross_split_duplicate_preflight"],
                },
                "training": {
                    "model_version": artifact["model_version"],
                    "model_sha256": model_hash,
                    "threshold_source": "development_validation_only",
                    "decision_threshold": float(artifact["threshold"]),
                    "development_sha256": development_info["sha256"],
                },
                "evaluation": {
                    "status": evaluation["status"],
                    "attempts": 1,
                    "reported_data_kind": evaluation["dataset"]["kind"],
                    "sealed_test_sha256": evaluation["dataset"]["sha256"],
                    "evaluation_plan_sha256": evaluation["evaluation_plan"]["sha256"],
                    "decision_threshold": evaluation_metrics["threshold"],
                    "sample_counts": {
                        "total": evaluation_metrics["support"],
                        "ham": evaluation_metrics["support_ham"],
                        "spam": evaluation_metrics["support_spam"],
                    },
                    "metrics": {
                        key: evaluation_metrics[key]
                        for key in (
                            "precision",
                            "recall",
                            "f1",
                            "false_positive_rate",
                            "false_negative_rate",
                            "confusion_matrix",
                        )
                    },
                    "campaign_interval_available": evaluation_metrics["campaign_bootstrap_95"]["available"],
                },
                "limitations": [
                    "All messages are generated fixtures; this rehearsal is not consented participant data, "
                    "Philippine field evidence, or a real-world accuracy estimate.",
                    "The synthetic consent register exercises technical gates only and is not a real governance record.",
                ],
            }
    except RehearsalError:
        raise
    except Exception:
        raise RehearsalError(stage) from None

    summary["cleanup"] = {"temporary_workspace_removed": temporary_root is not None and not temporary_root.exists()}
    if not summary["cleanup"]["temporary_workspace_removed"]:
        raise RehearsalError("temporary_cleanup")
    return summary


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Run a disposable synthetic consented-study rehearsal.").parse_args(argv)
    try:
        report = run_synthetic_rehearsal()
    except RehearsalError as exc:
        print(json.dumps({"status": "failed", "stage": exc.stage}, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
