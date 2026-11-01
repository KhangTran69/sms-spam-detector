"""Evaluate one normalized dataset without mixing provenance classes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from src.dataset_loading import Dataset, group_leakage_report, load_dataset
from src.dataset_schema import make_group_key
from src.metrics import binary_metrics, calibration_metrics, campaign_bootstrap_intervals, jsonable, per_group_metrics
from src.predict import ModelArtifactError, load_model, spam_probabilities
from src.privacy.storage import ensure_private_directory

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_NAMES = (
    "numpy",
    "pandas",
    "scikit-learn",
    "scipy",
    "joblib",
    "fastapi",
    "uvicorn",
    "pydantic",
)
BOOTSTRAP_SEED = 42
CALIBRATION_BINS = 10


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_metadata() -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        revision = None
        dirty = None
    versions: dict[str, str] = {}
    for name in DEPENDENCY_NAMES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "unknown"
    return {
        "source_revision": revision,
        "source_tree_dirty": dirty,
        "python_version": platform.python_version(),
        "libraries": versions,
    }


def _safe_slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")[:80]
    return slug or fallback


def _dataset_kind(dataset: Dataset) -> str:
    kinds = set(dataset.frame["data_kind"].fillna("unknown").astype(str).str.lower())
    if len(kinds) != 1:
        raise ValueError(
            "Evaluation input must contain one provenance kind only (public, synthetic, consented, or unknown); "
            "split mixed provenance into separate datasets before evaluation."
        )
    return next(iter(kinds))


def _breakdowns(dataset: Dataset, probabilities: list[float], threshold: float) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for column in ("source", "language", "category"):
        result[column] = per_group_metrics(
            dataset.frame,
            probabilities,
            threshold,
            group_columns=(column,),
            min_count=1,
        )
    return jsonable(result)


def _operating_threshold(labels: list[str], probabilities: list[float], max_fpr: float) -> dict[str, Any]:
    ham_count = labels.count("ham")
    if ham_count == 0:
        return {
            "status": "unavailable_no_ham_examples",
            "threshold": None,
            "max_false_positive_rate": max_fpr,
            "metrics": None,
        }
    candidates = np.asarray(sorted({0.0, 1.0, *(float(value) for value in probabilities)}))
    scores = np.asarray(probabilities, dtype=float)
    is_spam = np.asarray([label == "spam" for label in labels], dtype=bool)
    ham_scores = np.sort(scores[~is_spam])
    spam_scores = np.sort(scores[is_spam])
    false_positives = ham_count - np.searchsorted(ham_scores, candidates, side="left")
    true_positives = len(spam_scores) - np.searchsorted(spam_scores, candidates, side="left")
    false_positive_rates = false_positives / ham_count
    recall_rates = true_positives / max(int(is_spam.sum()), 1)
    eligible = np.flatnonzero(false_positive_rates <= max_fpr)
    if not len(eligible):
        return {
            "status": "unavailable_no_threshold_meets_observed_bound",
            "threshold": None,
            "max_false_positive_rate": max_fpr,
            "metrics": None,
        }
    best_index = max(
        eligible.tolist(),
        key=lambda index: (recall_rates[index], -false_positive_rates[index], candidates[index]),
    )
    chosen = binary_metrics(labels, probabilities, float(candidates[best_index]))
    return {
        "status": "available_empirical_only",
        "threshold": chosen["threshold"],
        "max_false_positive_rate": max_fpr,
        "metrics": chosen,
        "interpretation": (
            "Descriptive threshold analysis on this dataset only; it is not a production recommendation and "
            "does not guarantee the same false-positive rate on future messages."
        ),
    }


def _membership_fingerprint(dataset_sha256: str, row_count: int) -> str:
    # Hash positional membership identifiers, not message content or record IDs.
    members = "\n".join(f"{dataset_sha256}:{index}" for index in range(row_count))
    return hashlib.sha256(members.encode("ascii")).hexdigest()


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    dataset = report["dataset"]
    model = report["model"]

    def format_metric(value: float | None) -> str:
        return "unavailable" if value is None else f"{value:.4f}"

    def coverage_items(name: str) -> str:
        return (
            ", ".join(f"{item.get(name) or 'unknown'} ({item['support']})" for item in report["breakdowns"][name])
            or "none"
        )

    lines = [
        f"# Evaluation: {dataset['name']}",
        "",
        f"> **{dataset['kind'].upper()} DATASET** — this result describes only this dataset and does not establish representative real-world Philippine performance.",
        "",
        f"- Model: `{model['version']}` (SHA-256 `{model['sha256']}`)",
        f"- Dataset SHA-256: `{dataset['sha256']}`",
        f"- Source revision: `{report['run']['source_revision'] or 'unavailable'}` (working tree dirty: `{report['run']['source_tree_dirty']}`)",
        f"- Evaluated rows: {metrics['support']} ({metrics['support_ham']} ham, {metrics['support_spam']} spam)",
        "",
        "Scores are model outputs, not calibrated fraud probabilities or guarantees that a message is safe.",
        "",
        "## Metrics at the model's stored decision threshold",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Decision threshold | {metrics['threshold']:.4f} |",
        f"| Precision | {metrics['precision']:.4f} |",
        f"| Recall | {metrics['recall']:.4f} |",
        f"| F1 | {metrics['f1']:.4f} |",
        f"| ROC-AUC | {format_metric(metrics['roc_auc'])} |",
        f"| PR-AUC | {format_metric(metrics['pr_auc'])} |",
        f"| False-negative rate | {format_metric(metrics['false_negative_rate'])} |",
        f"| Confusion counts (TP / FP / TN / FN) | {metrics['confusion_matrix']['tp']} / {metrics['confusion_matrix']['fp']} / {metrics['confusion_matrix']['tn']} / {metrics['confusion_matrix']['fn']} |",
        "",
        "Wilson intervals are row-level marginal intervals. Campaign bootstrap intervals resample whole campaign groups; either interval may be unavailable or too wide for a decision. Calibration diagnostics do not establish calibration on future or representative Philippine messages.",
        "",
        "## Operating-threshold diagnostic",
        "",
        (
            "No threshold sweep was run. The stored threshold was frozen before this sealed consented evaluation."
            if report["operating_threshold"]["status"] == "not_run_sealed_consent_evaluation"
            else f"Configured empirical false-positive-rate bound: {report['operating_threshold']['max_false_positive_rate']:.1%}."
        ),
        (
            f"Status: `{report['operating_threshold']['status']}`; selected threshold: {report['operating_threshold']['threshold'] if report['operating_threshold']['threshold'] is not None else 'unavailable'}."
            if report["operating_threshold"]["status"] != "not_run_sealed_consent_evaluation"
            else ""
        ),
        "Threshold diagnostics on public/synthetic datasets are descriptive and are not production recommendations.",
        "",
        "## Coverage",
        "",
        f"- Sources: {coverage_items('source')}",
        f"- Languages: {coverage_items('language')}",
        f"- Categories: {coverage_items('category')}",
        "",
        "Verify suspicious requests through trusted official channels. Do not use a low spam score as proof that a message is safe.",
        "",
    ]
    return "\n".join(lines)


def _readiness_markdown(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    model = report["model"]
    blockers = "\n".join(f"- `{reason}`" for reason in report["readiness"]["blockers"])
    return "\n".join(
        [
            f"# Evaluation readiness: {dataset['name']}",
            "",
            f"> **BLOCKED** — no performance metrics were generated for this {dataset['kind']} dataset.",
            "",
            f"- Dataset SHA-256: `{dataset['sha256']}`",
            f"- Rows checked: {dataset['rows']} ({dataset['label_counts']})",
            f"- Campaign groups: {dataset['campaign_groups']}",
            f"- Model status: `{model['status']}`",
            "",
            "## Blockers",
            "",
            blockers,
            "",
            "A passing dataset preflight is not an evaluation result. Resolve every blocker, verify consent scope and withdrawal status, independently adjudicated labels, campaign/date separation, artifact provenance, and pre-registered uncertainty and coverage criteria. Do not report representativeness from a one-person inbox or synthetic fixtures.",
            "",
        ]
    )


def _write_reports(report: dict[str, Any], output_dir: str | Path) -> None:
    private = report["dataset"]["kind"] in {"consented", "synthetic_rehearsal"}
    destination = Path(output_dir).expanduser().resolve()
    private_root = (ROOT / "data" / "donations").resolve()
    inside_repository = destination == ROOT.resolve() or ROOT.resolve() in destination.parents
    if private and inside_repository and destination != private_root and private_root not in destination.parents:
        raise ValueError(
            "Consented evaluation reports must be written outside the repository or under ignored data/donations/."
        )
    if private:
        destination = ensure_private_directory(destination)
    else:
        destination.mkdir(parents=True, exist_ok=True, mode=0o755)

    dataset_name = report["dataset"]["name"]
    if report["status"] == "blocked":
        json_path = destination / f"{dataset_name}_readiness.json"
        markdown_path = destination / f"{dataset_name}_readiness.md"
        markdown = _readiness_markdown(report)
    else:
        json_path = destination / f"{dataset_name}_{report['model']['version']}.json"
        markdown_path = destination / f"{dataset_name}.md"
        markdown = _markdown(report)
    outputs = (
        (json_path, json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"),
        (markdown_path, markdown),
    )
    if private and report["status"] == "evaluated" and any(target.exists() for target, _ in outputs):
        raise FileExistsError(
            "A consented evaluation report already exists; keep the sealed evaluation result immutable."
        )
    for target, content in outputs:
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o666)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise


def _claim_sealed_evaluation_attempt(
    output_dir: str | Path,
    dataset_path: str | Path,
    *,
    dataset_name: str,
    dataset_sha256: str,
    training_sha256: str,
    model_sha256: str,
    model_version: str,
    threshold: float,
    evaluation_plan_sha256: str,
) -> str | None:
    """Atomically reserve a private report directory for one sealed-test score."""
    destination = Path(output_dir).expanduser().resolve()
    repository = ROOT.resolve()
    private_root = (repository / "data" / "donations").resolve()
    if (destination == repository or repository in destination.parents) and private_root not in destination.parents:
        return "sealed_evaluation_output_not_private"
    try:
        destination = ensure_private_directory(destination)
    except (OSError, ValueError):
        return "sealed_evaluation_output_not_private"

    try:
        dataset_directory = ensure_private_directory(Path(dataset_path).expanduser().resolve().parent)
    except (OSError, ValueError):
        return "sealed_evaluation_attempt_registry_not_private"
    marker_path = dataset_directory / f".{dataset_sha256}.sealed-evaluation-attempt.json"
    if marker_path.exists():
        return "sealed_evaluation_already_attempted"
    model_slug = _safe_slug(model_version, fallback="unknown-model")
    report_paths = (
        destination / f"{dataset_name}_{model_slug}.json",
        destination / f"{dataset_name}.md",
    )
    if any(path.exists() for path in report_paths):
        return "sealed_evaluation_already_reported"

    marker = {
        "schema_version": 1,
        "claimed_at_utc": datetime.now(UTC).isoformat(),
        "dataset_sha256": dataset_sha256,
        "training_dataset_sha256": training_sha256,
        "model_sha256": model_sha256,
        "model_version": model_slug,
        "decision_threshold": float(threshold),
        "evaluation_plan_sha256": evaluation_plan_sha256,
    }
    try:
        descriptor = os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return "sealed_evaluation_already_attempted"
    except OSError:
        return "sealed_evaluation_attempt_could_not_be_recorded"
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(marker, indent=2, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        return "sealed_evaluation_attempt_could_not_be_recorded"
    return None


def _evaluation_readiness_report(
    dataset: Dataset,
    dataset_file: Path,
    model_file: Path,
    *,
    blockers: list[str],
    operating_fpr: float,
    diagnostics: dict[str, Any] | None = None,
    model_status: str | None = None,
    evaluation_plan_sha256: str | None = None,
    dataset_sha256: str | None = None,
    dataset_kind: str | None = None,
) -> dict[str, Any]:
    dataset_hash = dataset_sha256 or _sha256(dataset_file)
    labels = dataset.labels
    kind = dataset_kind or _dataset_kind(dataset)
    resolved_model_status = model_status or ("missing" if "model_artifact_missing" in blockers else "unavailable")
    model_hash = _sha256(model_file) if model_file.is_file() else None
    return jsonable(
        {
            "schema_version": 1,
            "status": "blocked",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "readiness": {
                "status": "blocked",
                "blockers": blockers,
                "metrics_generated": False,
                "interpretation": "No performance report was released because one or more model, dataset, coverage, or uncertainty readiness checks failed.",
                "diagnostics": diagnostics or {},
            },
            "dataset": {
                "name": "consented-evaluation"
                if kind == "consented"
                else "synthetic-rehearsal"
                if kind == "synthetic_rehearsal"
                else _safe_slug(dataset_file.stem, fallback="dataset"),
                "kind": kind,
                "sha256": dataset_hash,
                "rows": len(dataset),
                "label_counts": {"ham": labels.count("ham"), "spam": labels.count("spam")},
                "campaign_groups": len(set(dataset.groups)),
                "evaluation_membership_sha256": _membership_fingerprint(dataset_hash, len(dataset)),
            },
            "model": {"status": resolved_model_status, "sha256": model_hash, "version": None},
            "evaluation_plan": {"sha256": evaluation_plan_sha256} if evaluation_plan_sha256 else None,
            "run": {
                **_run_metadata(),
                "configuration": {"operating_false_positive_rate_bound": operating_fpr},
            },
            "metrics": None,
            "breakdowns": None,
            "limitations": [
                "A passing dataset preflight is not an evaluation result.",
                "Before reporting performance, verify consent scope and withdrawal status, independent adjudication, campaign/date separation, artifact provenance, and pre-registered uncertainty and coverage criteria.",
                "This report does not establish representative Philippine performance, calibrated fraud probabilities, or safety guarantees.",
            ],
        }
    )


def _validate_consent_evaluation_plan(
    plan_path: str | Path | None,
    *,
    dataset_sha256: str,
    training_sha256: str,
    training_membership_sha256: str,
    test_membership_sha256: str,
    model_sha256: str,
    model_version: str,
    threshold: float,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate an operator-authored plan without echoing its free-text fields."""
    if plan_path is None:
        return None, ["evaluation_plan_missing"]
    path = Path(plan_path).expanduser()
    if not path.is_file():
        return None, ["evaluation_plan_unavailable"]
    try:
        plan_bytes = path.read_bytes()
        plan = json.loads(plan_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, ["evaluation_plan_unavailable"]
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        return None, ["evaluation_plan_invalid"]

    blockers: list[str] = []
    if not isinstance(plan.get("intended_use"), str) or not plan["intended_use"].strip():
        blockers.append("evaluation_plan_intended_use_missing")
    for field in ("coverage_rationale", "uncertainty_rationale"):
        value = plan.get(field)
        if not isinstance(value, str) or len(value.strip()) < 20:
            blockers.append("evaluation_plan_acceptance_rationale_missing")
    registered_at: datetime | None = None
    try:
        registered_at = datetime.fromisoformat(str(plan.get("registered_at", "")).replace("Z", "+00:00"))
        if registered_at.tzinfo is None or registered_at > datetime.now(UTC):
            blockers.append("evaluation_plan_registration_time_invalid")
    except (TypeError, ValueError):
        blockers.append("evaluation_plan_registration_time_invalid")
    if plan.get("dataset_sha256") != dataset_sha256:
        blockers.append("evaluation_plan_dataset_hash_mismatch")
    if plan.get("training_dataset_sha256") != training_sha256:
        blockers.append("evaluation_plan_training_hash_mismatch")
    if plan.get("training_membership_sha256") != training_membership_sha256:
        blockers.append("evaluation_plan_training_membership_mismatch")
    if plan.get("test_membership_sha256") != test_membership_sha256:
        blockers.append("evaluation_plan_test_membership_mismatch")
    if plan.get("model_sha256") != model_sha256:
        blockers.append("evaluation_plan_model_hash_mismatch")
    if plan.get("model_version") != model_version or not isinstance(plan.get("model_version"), str):
        blockers.append("evaluation_plan_model_version_mismatch")
    try:
        planned_threshold_value = plan.get("decision_threshold")
        if isinstance(planned_threshold_value, bool) or not isinstance(planned_threshold_value, (int, float)):
            raise ValueError
        planned_threshold = float(planned_threshold_value)
        if not 0.0 <= planned_threshold <= 1.0 or abs(planned_threshold - threshold) > 1e-9:
            blockers.append("evaluation_plan_threshold_mismatch")
    except (TypeError, ValueError):
        blockers.append("evaluation_plan_threshold_mismatch")
    if plan.get("split_method") != "chronological_campaign_holdout":
        blockers.append("evaluation_plan_campaign_time_split_required")
    if plan.get("campaign_overlap_checked") is not True:
        blockers.append("evaluation_plan_campaign_overlap_not_verified")
    if plan.get("test_split_sealed") is not True:
        blockers.append("evaluation_plan_test_set_not_sealed")

    minimum_groups = plan.get("minimum_campaign_groups")
    if isinstance(minimum_groups, bool) or not isinstance(minimum_groups, int) or minimum_groups < 2:
        blockers.append("evaluation_plan_campaign_group_minimum_invalid")
    coverage = plan.get("minimum_coverage")
    safe_code = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    if not isinstance(coverage, dict):
        blockers.append("evaluation_plan_coverage_requirements_invalid")
    else:
        for dimension in ("language", "category"):
            values = coverage.get(dimension)
            if not isinstance(values, dict) or not values:
                blockers.append("evaluation_plan_coverage_requirements_invalid")
                continue
            if any(
                not isinstance(code, str)
                or not safe_code.fullmatch(code)
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 1
                for code, count in values.items()
            ):
                blockers.append("evaluation_plan_coverage_requirements_invalid")
    widths = plan.get("maximum_cluster_interval_width")
    required_metrics = {"precision", "recall", "f1", "false_positive_rate", "false_negative_rate"}
    if (
        not isinstance(widths, dict)
        or not required_metrics <= set(widths)
        or any(
            isinstance(widths[name], bool)
            or not isinstance(widths[name], (int, float))
            or not 0.0 < float(widths[name]) < 1.0
            for name in required_metrics
        )
    ):
        blockers.append("evaluation_plan_uncertainty_requirements_invalid")
    if blockers:
        return None, sorted(set(blockers))
    if registered_at is None:  # Defensive for type checkers and malformed plans.
        return None, ["evaluation_plan_registration_time_invalid"]
    if not isinstance(widths, dict):  # Defensive: the blocker above should already cover this.
        return None, ["evaluation_plan_uncertainty_requirements_invalid"]

    safe_plan = {
        "sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "registered_at": registered_at.astimezone(UTC).isoformat(),
        "training_dataset_sha256": training_sha256,
        "training_membership_sha256": training_membership_sha256,
        "test_dataset_sha256": dataset_sha256,
        "test_membership_sha256": test_membership_sha256,
        "minimum_campaign_groups": minimum_groups,
        "minimum_coverage": coverage,
        "maximum_cluster_interval_width": {name: float(widths[name]) for name in sorted(required_metrics)},
        "split_method": "chronological_campaign_holdout",
        "campaign_overlap_checked": True,
        "test_split_sealed": True,
    }
    return safe_plan, []


def _consented_development_diagnostics(
    development: Dataset,
    evaluation: Dataset,
    *,
    development_sha256: str,
    evaluation_sha256: str,
) -> tuple[dict[str, Any], list[str]]:
    """Check the consented development pool against a sealed later test batch."""
    blockers: list[str] = []
    try:
        development_kind = _dataset_kind(development)
    except ValueError:
        development_kind = "mixed"
    if development_kind != "consented":
        blockers.append("development_dataset_must_be_consented")
    if set(development.labels) != {"ham", "spam"}:
        blockers.append("development_split_requires_both_labels")
    if set(evaluation.labels) != {"ham", "spam"}:
        blockers.append("evaluation_split_requires_both_labels")

    dev_groups = set(development.groups)
    eval_groups = set(evaluation.groups)
    group_overlap = len(dev_groups & eval_groups)
    if group_overlap:
        blockers.append("campaign_group_overlap_across_splits")

    try:
        leakage = group_leakage_report(development, evaluation)
    except ValueError:
        leakage = {"exact_or_normalized_message_overlap": True}
        blockers.append("duplicate_message_across_splits")

    development_templates = {
        make_group_key(message, category=str(category))
        for message, category in zip(development.messages, development.frame["category"], strict=True)
    }
    evaluation_templates = {
        make_group_key(message, category=str(category))
        for message, category in zip(evaluation.messages, evaluation.frame["category"], strict=True)
    }
    template_overlap = len(development_templates & evaluation_templates)
    if template_overlap:
        blockers.append("template_family_overlap_across_splits")

    date_ranges: dict[str, str | None] = {}
    parsed_dates: dict[str, pd.Series] = {}
    for name, dataset in (("development", development), ("evaluation", evaluation)):
        dates = pd.to_datetime(dataset.frame["received_at"], errors="coerce", utc=True)
        parsed_dates[name] = dates
        if dates.isna().any():
            blockers.append(f"{name}_dates_missing_or_invalid")
            date_ranges[name] = None
        else:
            date_ranges[name] = f"{dates.min().date().isoformat()}..{dates.max().date().isoformat()}"
    if (
        not parsed_dates["development"].isna().any()
        and not parsed_dates["evaluation"].isna().any()
        and parsed_dates["development"].max() >= parsed_dates["evaluation"].min()
    ):
        blockers.append("campaign_dates_not_chronologically_separated")

    development_membership = _membership_fingerprint(development_sha256, len(development))
    evaluation_membership = _membership_fingerprint(evaluation_sha256, len(evaluation))
    return (
        {
            "development": {
                "dataset_sha256": development_sha256,
                "membership_sha256": development_membership,
                "rows": len(development),
                "label_counts": {"ham": development.labels.count("ham"), "spam": development.labels.count("spam")},
                "campaign_groups": len(dev_groups),
                "date_range_utc": date_ranges["development"],
            },
            "evaluation": {
                "dataset_sha256": evaluation_sha256,
                "membership_sha256": evaluation_membership,
                "rows": len(evaluation),
                "label_counts": {"ham": evaluation.labels.count("ham"), "spam": evaluation.labels.count("spam")},
                "campaign_groups": len(eval_groups),
                "date_range_utc": date_ranges["evaluation"],
            },
            "campaign_group_overlap": group_overlap,
            "template_family_overlap": template_overlap,
            "exact_or_normalized_message_overlap": (
                leakage.get("exact_message_overlap", 0)
                if leakage.get("exact_or_normalized_message_overlap") is not True
                else None
            ),
        },
        sorted(set(blockers)),
    )


def _model_provenance_blockers(bundle: Any, development_sha256: str) -> list[str]:
    metadata = getattr(bundle, "metadata", {})
    if not isinstance(metadata, dict):
        return ["model_training_provenance_missing"]
    training_config = metadata.get("training_config")
    selection = metadata.get("threshold_selection")
    decision = selection.get("decision") if isinstance(selection, dict) else None
    split = metadata.get("split")
    data_sources = metadata.get("data_sources")
    blockers: list[str] = []
    threshold = getattr(bundle, "threshold", None)
    if (
        not isinstance(training_config, dict)
        or training_config.get("split_by") != "time"
        or training_config.get("threshold_policy") not in {"validation", "cv-robust"}
        or not isinstance(split, dict)
        or split.get("method") != "chronological_group_holdout"
        or split.get("group_leakage") != 0
    ):
        blockers.append("model_campaign_time_split_provenance_missing")
    if (
        not isinstance(decision, dict)
        or decision.get("policy") not in {"validation", "cv-robust"}
        or not isinstance(training_config, dict)
        or decision.get("policy") != training_config.get("threshold_policy")
        or isinstance(decision.get("threshold"), bool)
        or not isinstance(decision.get("threshold"), (int, float))
        or threshold is None
        or abs(float(decision.get("threshold", -1)) - float(threshold)) > 1e-9
    ):
        blockers.append("model_validation_threshold_provenance_missing")
    source_hashes = (
        {
            source.get("sha256")
            for source in data_sources
            if isinstance(source, dict) and isinstance(source.get("sha256"), str)
        }
        if isinstance(data_sources, list)
        else set()
    )
    if development_sha256 not in source_hashes:
        blockers.append("model_development_dataset_hash_mismatch")
    return sorted(set(blockers))


def _consented_coverage_diagnostics(dataset: Dataset, plan: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    coverage_counts: dict[str, dict[str, int]] = {}
    blockers: list[str] = []
    for dimension in ("language", "category"):
        counts = dataset.frame[dimension].fillna("unknown").astype(str).value_counts().to_dict()
        coverage_counts[dimension] = {str(key): int(value) for key, value in counts.items()}
        minimums = plan["minimum_coverage"][dimension]
        for code, minimum in minimums.items():
            if coverage_counts[dimension].get(code, 0) < minimum:
                blockers.append(f"{dimension}_coverage_below_plan")
    group_count = len(set(dataset.groups))
    if group_count < plan["minimum_campaign_groups"]:
        blockers.append("campaign_group_count_below_plan")
    return {
        "campaign_group_count": group_count,
        "required_campaign_group_count": plan["minimum_campaign_groups"],
        "coverage_counts": coverage_counts,
    }, sorted(set(blockers))


def _wilson_interval(successes: int, total: int) -> list[float] | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = z * ((proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)) ** 0.5) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def evaluate_public_dataset(
    dataset_path: str | Path,
    model_path: str | Path,
    output_dir: str | Path,
    *,
    operating_fpr: float = 0.05,
    evaluation_plan_path: str | Path | None = None,
    training_data_path: str | Path | None = None,
    synthetic_rehearsal: bool = False,
) -> dict[str, Any]:
    """Evaluate the given model on one dataset and write content-free reports."""
    if not 0.0 <= operating_fpr <= 1.0:
        raise ValueError("operating_fpr must be between 0 and 1")
    dataset_file = Path(dataset_path).expanduser().resolve()
    model_file = Path(model_path)
    dataset = load_dataset(dataset_file, role="holdout", require_both_classes=False, min_class_count=0)
    dataset_hash = dataset.records[0].sha256 if dataset.records else _sha256(dataset_file)
    source_kind = _dataset_kind(dataset)
    if synthetic_rehearsal and source_kind != "consented":
        raise ValueError("Synthetic rehearsal labeling is only available for a consent-gated synthetic fixture.")
    kind = "synthetic_rehearsal" if synthetic_rehearsal else source_kind
    requires_consent_gate = source_kind == "consented"

    # identify_artifact hashes and deserializes the same immutable byte sequence.
    blockers: list[str] = []
    split_diagnostics: dict[str, Any] = {}
    development: Dataset | None = None
    development_sha256: str | None = None
    if requires_consent_gate:
        if evaluation_plan_path is None:
            blockers.append("evaluation_plan_missing")
        if training_data_path is None:
            blockers.append("development_dataset_missing")
        else:
            development_file = Path(training_data_path).expanduser()
            if not development_file.is_file():
                blockers.append("development_dataset_unavailable")
            else:
                try:
                    development = load_dataset(
                        development_file,
                        role="training",
                        require_both_classes=False,
                        min_class_count=0,
                    )
                    development_sha256 = (
                        development.records[0].sha256 if development.records else _sha256(development_file)
                    )
                    split_diagnostics, split_blockers = _consented_development_diagnostics(
                        development,
                        dataset,
                        development_sha256=development_sha256,
                        evaluation_sha256=dataset_hash,
                    )
                    blockers.extend(split_blockers)
                except (OSError, ValueError):
                    blockers.append("development_dataset_invalid")
    if not model_file.is_file():
        blockers.append("model_artifact_missing")
    if blockers:
        readiness = _evaluation_readiness_report(
            dataset,
            dataset_file,
            model_file,
            blockers=sorted(set(blockers)),
            operating_fpr=operating_fpr,
            diagnostics=split_diagnostics,
            model_status="missing" if "model_artifact_missing" in blockers else "unverified",
            dataset_sha256=dataset_hash,
            dataset_kind=kind,
        )
        _write_reports(readiness, output_dir)
        return readiness
    try:
        bundle = load_model(model_file, identify_artifact=True)
    except (FileNotFoundError, ModelArtifactError, OSError):
        readiness = _evaluation_readiness_report(
            dataset,
            dataset_file,
            model_file,
            blockers=["model_artifact_unavailable"],
            operating_fpr=operating_fpr,
            model_status="unavailable",
            dataset_sha256=dataset_hash,
            dataset_kind=kind,
        )
        _write_reports(readiness, output_dir)
        return readiness
    model_hash = getattr(bundle, "artifact_sha256", None) or _sha256(model_file)
    evaluation_plan: dict[str, Any] | None = None
    if requires_consent_gate:
        assert development is not None and development_sha256 is not None
        training_membership_sha256 = _membership_fingerprint(development_sha256, len(development))
        test_membership_sha256 = _membership_fingerprint(dataset_hash, len(dataset))
        model_blockers = _model_provenance_blockers(bundle, development_sha256)
        if model_blockers:
            readiness = _evaluation_readiness_report(
                dataset,
                dataset_file,
                model_file,
                blockers=model_blockers,
                operating_fpr=operating_fpr,
                diagnostics=split_diagnostics,
                model_status="verified",
                dataset_sha256=dataset_hash,
                dataset_kind=kind,
            )
            _write_reports(readiness, output_dir)
            return readiness
        evaluation_plan, plan_blockers = _validate_consent_evaluation_plan(
            evaluation_plan_path,
            dataset_sha256=dataset_hash,
            training_sha256=development_sha256,
            training_membership_sha256=training_membership_sha256,
            test_membership_sha256=test_membership_sha256,
            model_sha256=model_hash,
            model_version=str(bundle.version),
            threshold=float(bundle.threshold),
        )
        if plan_blockers or evaluation_plan is None:
            readiness = _evaluation_readiness_report(
                dataset,
                dataset_file,
                model_file,
                blockers=plan_blockers or ["evaluation_plan_invalid"],
                operating_fpr=operating_fpr,
                model_status="verified",
                diagnostics=split_diagnostics,
                evaluation_plan_sha256=(
                    _sha256(Path(evaluation_plan_path))
                    if evaluation_plan_path and Path(evaluation_plan_path).is_file()
                    else None
                ),
                dataset_sha256=dataset_hash,
                dataset_kind=kind,
            )
            _write_reports(readiness, output_dir)
            return readiness
        coverage_diagnostics, coverage_blockers = _consented_coverage_diagnostics(dataset, evaluation_plan)
        if coverage_blockers:
            readiness = _evaluation_readiness_report(
                dataset,
                dataset_file,
                model_file,
                blockers=coverage_blockers,
                operating_fpr=operating_fpr,
                diagnostics={**split_diagnostics, "coverage": coverage_diagnostics},
                model_status="verified",
                evaluation_plan_sha256=evaluation_plan["sha256"],
                dataset_sha256=dataset_hash,
                dataset_kind=kind,
            )
            _write_reports(readiness, output_dir)
            return readiness
        attempt_blocker = _claim_sealed_evaluation_attempt(
            output_dir,
            dataset_file,
            dataset_name="synthetic-rehearsal" if synthetic_rehearsal else "consented-evaluation",
            dataset_sha256=dataset_hash,
            training_sha256=development_sha256,
            model_sha256=model_hash,
            model_version=str(bundle.version),
            threshold=float(bundle.threshold),
            evaluation_plan_sha256=evaluation_plan["sha256"],
        )
        if attempt_blocker:
            readiness = _evaluation_readiness_report(
                dataset,
                dataset_file,
                model_file,
                blockers=[attempt_blocker],
                operating_fpr=operating_fpr,
                diagnostics=split_diagnostics,
                model_status="verified",
                evaluation_plan_sha256=evaluation_plan["sha256"],
                dataset_sha256=dataset_hash,
                dataset_kind=kind,
            )
            _write_reports(readiness, output_dir)
            return readiness
    probabilities = spam_probabilities(bundle, dataset.messages)
    labels = dataset.labels
    metrics = binary_metrics(labels, probabilities, bundle.threshold)
    classes = set(labels)
    if classes == {"ham", "spam"}:
        metrics["roc_auc"] = float(roc_auc_score([int(label == "spam") for label in labels], probabilities))
        metrics["pr_auc"] = float(average_precision_score([int(label == "spam") for label in labels], probabilities))
        metrics["false_negative_rate"] = metrics["fn"] / metrics["support_spam"]
        metrics["false_negative_rate_status"] = "available"
    else:
        metrics["roc_auc"] = None
        metrics["pr_auc"] = None
        metrics["false_negative_rate"] = (
            None if metrics["support_spam"] == 0 else metrics["fn"] / metrics["support_spam"]
        )
        metrics["false_negative_rate_status"] = (
            "unavailable_no_positive_examples" if metrics["support_spam"] == 0 else "available"
        )
    metrics["confidence_intervals_95"]["false_negative_rate"] = _wilson_interval(
        int(metrics["fn"]), int(metrics["support_spam"])
    )
    campaign_intervals = campaign_bootstrap_intervals(
        dataset.frame,
        probabilities,
        float(bundle.threshold),
        replicates=1000,
        seed=BOOTSTRAP_SEED,
        minimum_groups=evaluation_plan["minimum_campaign_groups"] if evaluation_plan else 10,
    )
    if requires_consent_gate and evaluation_plan is not None:
        uncertainty_blockers: list[str] = []
        interval_widths: dict[str, float | None] = {}
        planned_widths = evaluation_plan["maximum_cluster_interval_width"]
        intervals = campaign_intervals.get("intervals", {})
        for metric_name, maximum_width in planned_widths.items():
            interval = intervals.get(metric_name) if campaign_intervals.get("available") else None
            if not isinstance(interval, list) or len(interval) != 2:
                interval_widths[metric_name] = None
                uncertainty_blockers.append("campaign_uncertainty_unavailable")
                continue
            width = float(interval[1]) - float(interval[0])
            interval_widths[metric_name] = width
            if width > float(maximum_width):
                uncertainty_blockers.append("campaign_uncertainty_precision_below_plan")
        if uncertainty_blockers:
            readiness = _evaluation_readiness_report(
                dataset,
                dataset_file,
                model_file,
                blockers=sorted(set(uncertainty_blockers)),
                operating_fpr=operating_fpr,
                diagnostics={
                    **split_diagnostics,
                    "campaign_bootstrap_95": campaign_intervals,
                    "campaign_interval_widths": interval_widths,
                },
                model_status="verified",
                evaluation_plan_sha256=evaluation_plan["sha256"],
                dataset_sha256=dataset_hash,
                dataset_kind=kind,
            )
            _write_reports(readiness, output_dir)
            return readiness
    calibration = calibration_metrics(labels, probabilities, n_bins=CALIBRATION_BINS)
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "evaluated",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset": {
            "name": "consented-evaluation"
            if kind == "consented"
            else "synthetic-rehearsal"
            if kind == "synthetic_rehearsal"
            else _safe_slug(dataset_file.stem, fallback="dataset"),
            "kind": kind,
            "sha256": dataset_hash,
            "rows": len(dataset),
            "evaluation_membership_sha256": _membership_fingerprint(dataset_hash, len(dataset)),
            "provenance": (
                {"source": "synthetic_rehearsal_fixture"}
                if synthetic_rehearsal
                else {"source": "consented_private"}
                if kind == "consented"
                else dataset.records[0].provenance
                if dataset.records
                else {}
            ),
        },
        "model": {
            "version": _safe_slug(str(bundle.version), fallback="unknown-model"),
            "sha256": model_hash,
            "probability_calibrated": getattr(bundle, "metadata", {}).get("probability_calibrated") is True,
        },
        "run": {
            **_run_metadata(),
            "configuration": {
                "decision_threshold": float(bundle.threshold),
                "operating_false_positive_rate_bound": operating_fpr if not requires_consent_gate else None,
                "calibration_bins": CALIBRATION_BINS,
                "uncertainty_method": (
                    "Wilson score 95% marginal intervals plus 95% campaign-cluster bootstrap"
                    if requires_consent_gate
                    else "Wilson score 95% marginal intervals plus campaign-cluster bootstrap when supported"
                ),
                "operating_threshold_method": (
                    "disabled on sealed consented evaluation"
                    if requires_consent_gate
                    else "maximize observed recall subject to the configured empirical false-positive-rate bound"
                ),
            },
        },
        "metrics": {
            "threshold": metrics["threshold"],
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "f1": metrics["f1"],
            "accuracy": metrics["accuracy"],
            "roc_auc": metrics["roc_auc"],
            "pr_auc": metrics["pr_auc"],
            "false_positive_rate": metrics["false_positive_rate"],
            "false_negative_rate": metrics["false_negative_rate"],
            "false_negative_rate_status": metrics["false_negative_rate_status"],
            "confusion_matrix": {key: metrics[key] for key in ("tp", "fp", "tn", "fn")},
            "support": metrics["support"],
            "support_ham": metrics["support_ham"],
            "support_spam": metrics["support_spam"],
            "confidence_intervals_95": metrics["confidence_intervals_95"],
            "campaign_bootstrap_95": campaign_intervals,
        },
        "calibration": calibration,
        "operating_threshold": (
            {
                "status": "not_run_sealed_consent_evaluation",
                "threshold": None,
                "max_false_positive_rate": None,
                "metrics": None,
                "interpretation": "No threshold search is run on the sealed consented evaluation set.",
            }
            if requires_consent_gate
            else _operating_threshold(labels, probabilities, operating_fpr)
        ),
        "evaluation_plan": evaluation_plan,
        "split_inputs": split_diagnostics if requires_consent_gate else None,
        "breakdowns": _breakdowns(dataset, probabilities, bundle.threshold),
        "limitations": [
            "This report describes only the supplied dataset and is not evidence of representative Philippine real-world accuracy.",
            "Scores are spam-versus-ham model outputs, not fraud probabilities or safety guarantees.",
            "Threshold diagnostics are descriptive and not a production recommendation.",
        ],
    }
    if synthetic_rehearsal:
        report["limitations"].append(
            "This report uses synthetic rehearsal fixtures only; it is not consented participant data, "
            "Philippine field evidence, or a real-world accuracy estimate."
        )
    report = jsonable(report)

    _write_reports(report, output_dir)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate one normalized dataset without mixing provenance classes.")
    parser.add_argument(
        "--dataset", required=True, help="Normalized CSV to evaluate (for Kaggle, under data/external/)."
    )
    parser.add_argument("--model", default=None, help="Model artifact path; defaults to the configured detector model.")
    parser.add_argument("--output-dir", default="reports/eval", help="Directory for JSON and Markdown reports.")
    parser.add_argument("--operating-fpr", type=float, default=0.05, help="Empirical false-positive-rate cap (0..1).")
    parser.add_argument(
        "--evaluation-plan",
        default=None,
        help="Pre-registered JSON plan required for consented evaluation data.",
    )
    parser.add_argument(
        "--training-data",
        default=None,
        help="Exact consented development CSV used to train the model; required for consented evaluation.",
    )
    args = parser.parse_args(argv)
    model_path = args.model
    if model_path is None:
        from src.predict import default_model_path

        model_path = default_model_path()
    report = evaluate_public_dataset(
        args.dataset,
        model_path,
        args.output_dir,
        operating_fpr=args.operating_fpr,
        evaluation_plan_path=args.evaluation_plan,
        training_data_path=args.training_data,
    )
    if report["status"] == "blocked":
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "dataset": report["dataset"]["name"],
                    "blockers": report["readiness"]["blockers"],
                    "metrics_generated": False,
                },
                indent=2,
            )
        )
        return 2
    print(
        json.dumps(
            {"status": report["status"], "dataset": report["dataset"]["name"], "metrics": report["metrics"]}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
