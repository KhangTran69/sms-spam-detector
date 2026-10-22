"""Evaluate a trained artifact on the internal test split and a separate holdout.

Important: the checked-in Philippine holdout is synthetic. Its scores are a
pipeline/benchmark sanity check, **not** evidence of real-world performance.
Every report is labelled accordingly, and per-source / per-category breakdowns
are reported when that metadata exists.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import ConfusionMatrixDisplay, confusion_matrix
from sklearn.naive_bayes import MultinomialNB

from src.data import (
    DEFAULT_DATA,
    DEFAULT_HOLDOUT,
    DEFAULT_SEED,
    DEFAULT_SUPPLEMENTS,
    DEFAULT_TEST_SIZE,
    DEFAULT_VAL_SIZE,
    Dataset,
    DatasetError,
    group_leakage_report,
    grouped_splits,
    load_holdout,
    load_training_dataset,
    split_dataset,
)
from src.features import make_model, messages_to_frame
from src.metrics import (
    binary_metrics,
    calibration_metrics,
    campaign_bootstrap_intervals,
    false_positive_categories,
    jsonable,
    per_group_metrics,
    select_threshold,
    threshold_sweep,
)
from src.predict import ModelBundle, load_model, spam_probabilities

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "spam_detector_v1.pkl"
DEFAULT_PLOT = ROOT / "data" / "processed" / "evaluation.png"
KEY_THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
SYNTHETIC_BANNER = "SYNTHETIC BENCHMARK — NOT REAL-WORLD PERFORMANCE"
LEGIT_CATEGORIES = ("otp", "bank_alert", "delivery", "bill", "personal_taglish", "promo")


def _benchmark_run_info(model_sha256: str | None) -> dict[str, Any]:
    """Return report identifiers without including local filesystem paths."""
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        source_tree_clean = not subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
        source_tree_clean = None
    versions = {}
    for package in (
        "numpy",
        "pandas",
        "scikit-learn",
        "scipy",
        "threadpoolctl",
        "joblib",
        "fastapi",
        "starlette",
        "uvicorn",
        "pydantic",
        "pydantic-core",
        "matplotlib",
    ):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unknown"
    return {
        "model_sha256": model_sha256,
        "source_revision": revision,
        "source_tree_clean": source_tree_clean,
        "python_version": platform.python_version(),
        "libraries": versions,
    }


def _provenance_banner(dataset: Dataset) -> str:
    kinds = set(dataset.frame["data_kind"].astype(str))
    if kinds == {"synthetic"}:
        return SYNTHETIC_BANNER
    if "unknown" in kinds or not kinds:
        return "UNVERIFIED OR MIXED-PROVENANCE BENCHMARK — NOT REAL-WORLD PERFORMANCE"
    if "synthetic" in kinds:
        return "MIXED-PROVENANCE BENCHMARK — NOT REAL-WORLD PERFORMANCE"
    if kinds == {"public"}:
        return "PUBLIC-CORPUS BENCHMARK — NOT PHILIPPINE REAL-WORLD PERFORMANCE"
    if "public" in kinds and kinds <= {"public", "consented", "real"}:
        return "MIXED PUBLIC AND CONSENTED-DATA BENCHMARK — REPRESENTATIVENESS NOT ESTABLISHED"
    return "CONSENTED-DATA BENCHMARK — REPRESENTATIVENESS NOT ESTABLISHED"


def _coverage_counts(frame: Any, column: str) -> dict[str, int]:
    if column not in frame:
        return {"unknown": len(frame)}
    counts = frame[column].fillna("unknown").astype(str).value_counts()
    return {str(key): int(value) for key, value in sorted(counts.items())}


def _score_interpretation(bundle: ModelBundle) -> str:
    """Describe scores using the loaded artifact's declared calibration state."""
    if bundle.metadata.get("probability_calibrated") is True:
        return "calibrated spam-versus-ham score; calibration does not make it a fraud probability or establish Philippine representativeness"
    return "uncalibrated spam-versus-ham model score; not a probability"


def _baseline_report(train_set: Dataset, test_set: Dataset, *, text_features: str, seed: int) -> dict[str, Any]:
    """Fit the fixed MultinomialNB baseline on train groups and report the same held-out groups."""
    baseline = make_model(MultinomialNB(), text_features=text_features)
    baseline.fit(messages_to_frame(train_set.messages), train_set.labels)
    bundle = ModelBundle(pipeline=baseline, threshold=0.5, metadata={"model_version": "multinomial-nb-baseline"})
    probabilities = spam_probabilities(bundle, test_set.messages)
    metrics = binary_metrics(test_set.labels, probabilities, 0.5)
    metrics["campaign_bootstrap_95"] = campaign_bootstrap_intervals(test_set.frame, probabilities, 0.5, seed=seed)
    return {
        "name": "MultinomialNB",
        "text_features": text_features,
        "threshold": 0.5,
        "fit_split": "train",
        "at_threshold": metrics,
        "by_data_kind": per_group_metrics(test_set.frame, probabilities, 0.5, group_columns=("data_kind",)),
        "comparison_note": "Baseline and evaluated artifact use the same training and test groups; compare with test.at_default_0.5 for a like-for-like threshold. The candidate's selected threshold is reported separately.",
    }


def _threshold_diagnostic(bundle: ModelBundle, recomputed_threshold: float) -> dict[str, Any]:
    """Validate saved selection and adoption metadata against current validation."""
    selection = bundle.metadata.get("threshold_selection")
    decision = selection.get("decision") if isinstance(selection, dict) else None
    config = bundle.metadata.get("training_config")
    policy = decision.get("policy") if isinstance(decision, dict) else None
    configured_policy = config.get("threshold_policy") if isinstance(config, dict) else None
    configured_precision = _metadata_number(config.get("target_precision")) if isinstance(config, dict) else None
    configured_recall = _metadata_number(config.get("min_recall")) if isinstance(config, dict) else None
    configured_fp_cost = _metadata_number(config.get("false_positive_cost")) if isinstance(config, dict) else None
    configured_fn_cost = _metadata_number(config.get("false_negative_cost")) if isinstance(config, dict) else None
    selection_strategy = selection.get("strategy") if isinstance(selection, dict) else None
    selected_precision = _metadata_number(selection.get("target_precision")) if isinstance(selection, dict) else None
    selected_recall = _metadata_number(selection.get("min_recall")) if isinstance(selection, dict) else None
    candidate = _metadata_threshold(decision.get("candidate_threshold")) if isinstance(decision, dict) else None
    selected_candidate = _metadata_threshold(selection.get("threshold")) if isinstance(selection, dict) else None
    decided_threshold = _metadata_threshold(decision.get("threshold")) if isinstance(decision, dict) else None
    status = "matches_validation"

    if selection is None:
        status = "policy_metadata_absent"
    elif not isinstance(selection, dict):
        status = "policy_metadata_malformed"
    elif "decision" not in selection:
        status = "policy_metadata_absent"
    elif not isinstance(decision, dict):
        status = "policy_metadata_malformed"
    elif not isinstance(config, dict):
        status = "policy_metadata_malformed" if config is not None else "policy_metadata_absent"
    elif "threshold_policy" not in config:
        status = "policy_metadata_absent"
    elif (
        not isinstance(configured_policy, str)
        or not isinstance(policy, str)
        or configured_policy not in {"validation", "cv-robust"}
        or policy not in {"validation", "cv-robust"}
    ):
        status = "policy_metadata_malformed"
    elif configured_policy != policy:
        status = "validation_policy_mismatch"
    elif (
        candidate is None
        or selected_candidate is None
        or decided_threshold is None
        or not isinstance(decision.get("adopted"), bool)
    ):
        status = "policy_metadata_malformed"
    elif abs(selected_candidate - candidate) > 1e-9:
        status = "policy_metadata_inconsistent"
    elif abs(candidate - recomputed_threshold) > 1e-9:
        status = "validation_candidate_drift"
    elif (
        configured_precision is None
        or configured_recall is None
        or selected_precision is None
        or selected_recall is None
    ):
        status = "policy_metadata_absent"
    elif not (0 <= configured_precision <= 1 and 0 <= configured_recall <= 1):
        status = "policy_metadata_malformed"
    elif abs(configured_precision - selected_precision) > 1e-9 or abs(configured_recall - selected_recall) > 1e-9:
        status = "policy_metadata_inconsistent"
    elif (
        (("false_positive_cost" in config) != ("false_negative_cost" in config))
        or (config.get("false_positive_cost") is not None and configured_fp_cost is None)
        or (config.get("false_negative_cost") is not None and configured_fn_cost is None)
        or (
            configured_fp_cost is not None
            and (configured_fp_cost <= 0 or configured_fn_cost is None or configured_fn_cost <= 0)
        )
        or (configured_fn_cost is not None and configured_fp_cost is None)
    ):
        status = "policy_metadata_malformed"
    elif (
        configured_fp_cost is not None
        and selection_strategy != "minimum_validation_weighted_error_cost"
        or configured_fp_cost is None
        and selection_strategy == "minimum_validation_weighted_error_cost"
    ):
        status = "policy_metadata_inconsistent"
    elif policy == "validation":
        if decision["adopted"] is not True or abs(decided_threshold - candidate) > 1e-9:
            status = "adoption_metadata_inconsistent"
        elif abs(float(bundle.threshold) - decided_threshold) > 1e-9:
            status = "artifact_threshold_mismatch"
    else:
        status = _cv_robust_threshold_status(bundle.threshold, candidate, decided_threshold, decision)

    return {
        "artifact_threshold": float(bundle.threshold),
        "recomputed_validation_candidate": float(recomputed_threshold),
        "selected_validation_candidate": selected_candidate,
        "recorded_candidate_threshold": candidate,
        "policy": str(policy) if policy is not None else None,
        "settings_consistent": status
        not in {"policy_metadata_absent", "policy_metadata_malformed", "policy_metadata_inconsistent"},
        "status": status,
    }


def _cv_robust_threshold_status(
    artifact_threshold: float,
    candidate: float,
    decided_threshold: float,
    decision: dict[str, Any],
) -> str:
    """Check that saved fold statistics imply the recorded cv-robust decision."""
    gains = decision.get("fold_f1_gains")
    default_threshold = _metadata_threshold(decision.get("default_threshold"))
    min_required_gain = _metadata_number(decision.get("min_required_mean_gain"))
    recorded_mean_gain = _metadata_number(decision.get("mean_f1_gain"))
    if not isinstance(gains, list) or not gains or default_threshold is None or min_required_gain is None:
        return "policy_metadata_absent"
    parsed_gains = [_metadata_number(value) for value in gains]
    if any(value is None or not -1 <= value <= 1 for value in parsed_gains):
        return "policy_metadata_malformed"
    valid_gains = [value for value in parsed_gains if value is not None]
    if not 0 <= min_required_gain <= 1 or recorded_mean_gain is None or not -1 <= recorded_mean_gain <= 1:
        return "policy_metadata_malformed"

    mean_gain = sum(valid_gains) / len(valid_gains)
    if abs(mean_gain - recorded_mean_gain) > 0.001:
        return "policy_metadata_inconsistent"
    expected_adoption = (
        abs(candidate - default_threshold) > 1e-9 and min(valid_gains) > 0 and recorded_mean_gain >= min_required_gain
    )
    adopted = decision["adopted"]
    expected_threshold = candidate if expected_adoption else default_threshold
    if adopted is not expected_adoption or abs(decided_threshold - expected_threshold) > 1e-9:
        return "adoption_metadata_inconsistent"
    if abs(artifact_threshold - decided_threshold) > 1e-9:
        return "artifact_threshold_mismatch"
    return "matches_validation" if adopted else "default_intentionally_retained"


def _metadata_threshold(value: Any) -> float | None:
    """Return only finite probability thresholds; tolerate malformed old metadata."""
    if isinstance(value, bool):
        return None
    try:
        threshold = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return threshold if math.isfinite(threshold) and 0 <= threshold <= 1 else None


def _metadata_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


# Diagnostic examples from the project brief. They are deliberately excluded
# from every data file (tests assert this) so predictions show generalized
# behavior. They are not a benchmark.
PHILIPPINE_EXAMPLES = (
    "Nag-claim ka ng ₱500,000 sa GMA Kapuso Foundation. Call now 09123456789",
    "BDO: Your account is locked. Verify here: http://bit.ly/fakebdo",
    "Congrats! You won ₱1M from PCSO. Text your name and address to 0922xxxxxxx",
)


def _probabilities(bundle: ModelBundle, dataset: Dataset) -> list[float]:
    return spam_probabilities(bundle, dataset.messages)


def _format_metrics(label: str, metrics: dict[str, Any]) -> str:
    return (
        f"{label}: precision={metrics['precision']:.4f} recall={metrics['recall']:.4f} "
        f"f1={metrics['f1']:.4f} accuracy={metrics['accuracy']:.4f} "
        f"FP={metrics['fp']} FN={metrics['fn']} (n={metrics['support']})"
    )


def _split_from_artifact(bundle: ModelBundle, dataset: Dataset, overrides: dict[str, Any]) -> Any:
    config = bundle.metadata.get("training_config")
    config = config if isinstance(config, dict) else {}
    val_size = overrides.get("val_size") or config.get("val_size", DEFAULT_VAL_SIZE)
    test_size = overrides.get("test_size") or config.get("test_size", DEFAULT_TEST_SIZE)
    seed_value = overrides.get("seed") if overrides.get("seed") is not None else config.get("random_state")
    seed = int(seed_value) if seed_value is not None else DEFAULT_SEED
    split_by = overrides.get("split_by") or config.get("split_by", "group")
    return grouped_splits(dataset, val_size=val_size, test_size=test_size, seed=seed, split_by=split_by)


def _data_hash_warnings(bundle: ModelBundle, dataset: Dataset) -> list[str]:
    recorded = list(bundle.metadata.get("data_sources", []))
    warnings: list[str] = []
    if recorded and len(recorded) != len(dataset.records):
        warnings.append("The number of current data sources differs from the training manifest.")
    for index, record in enumerate(dataset.records):
        if index >= len(recorded):
            break
        expected = recorded[index]
        expected_role = expected.get("role")
        expected_hash = expected.get("sha256")
        if expected_role and expected_role != record.role:
            warnings.append(f"Data source {index + 1} has a different role from the training manifest.")
        elif expected_hash and str(expected_hash) != record.sha256:
            warnings.append(
                f"Data source {index + 1} ({record.role}) differs from the training manifest hash. "
                "Metrics may not reproduce the trained model's results; retrain before trusting this report."
            )
    if recorded and len(recorded) == len(dataset.records) and not warnings:
        warnings.append("Data files match the artifact hashes recorded at training time.")
    return warnings


def _length_strata(frame: Any) -> Any:
    enriched = frame.copy()
    lengths = enriched["message"].map(len)
    enriched["message_length_range"] = lengths.map(
        lambda size: "1-70" if size <= 70 else "71-160" if size <= 160 else "161+"
    )
    return enriched


def _repeated_group_stability(
    dataset: Dataset,
    development_indices: list[int],
    *,
    seeds: Iterable[int],
    val_size: float,
    target_precision: float,
    min_recall: float,
    text_features: str,
    false_positive_cost: float | None,
    false_negative_cost: float | None,
) -> dict[str, Any]:
    """Repeat train/validation group splits within development data only.

    The caller reserves the artifact's final test indices first and never passes
    them here. Metrics below are threshold-selection diagnostics, not final test
    estimates; each validation fold is used to choose its own threshold.
    """
    dev = Dataset(frame=dataset.frame.iloc[development_indices].reset_index(drop=True), records=dataset.records)
    if len(set(dev.groups)) < 10:
        return {"available": False, "reason": "requires at least 10 development template groups"}
    runs: list[dict[str, Any]] = []
    for seed in seeds:
        try:
            split = grouped_splits(dev, val_size=val_size, test_size=0.1, seed=int(seed), split_by="group")
        except DatasetError as exc:
            runs.append({"seed": int(seed), "available": False, "reason": str(exc)})
            continue
        if not split.grouped:
            runs.append({"seed": int(seed), "available": False, "reason": "group-aware split unavailable"})
            continue
        fit_indices = sorted([*split.train_idx, *split.test_idx])
        fit_frame = dev.frame.iloc[fit_indices]
        val_frame = dev.frame.iloc[split.val_idx]
        model = make_model(
            LogisticRegression(class_weight="balanced", max_iter=2000, solver="liblinear", random_state=int(seed)),
            text_features=text_features,
        )
        model.fit(messages_to_frame(fit_frame["message"].tolist()), fit_frame["label"].tolist())
        val_probabilities = [
            float(row[list(model.classes_).index("spam")])
            for row in model.predict_proba(messages_to_frame(val_frame["message"].tolist()))
        ]
        choice = select_threshold(
            val_frame["label"].tolist(),
            val_probabilities,
            target_precision=target_precision,
            min_recall=min_recall,
            false_positive_cost=false_positive_cost,
            false_negative_cost=false_negative_cost,
        )
        metrics = binary_metrics(val_frame["label"].tolist(), val_probabilities, choice.threshold)
        runs.append(
            {
                "seed": int(seed),
                "group_count": int(dev.frame.iloc[split.val_idx]["group"].nunique()),
                "validation_rows": len(split.val_idx),
                "threshold": choice.threshold,
                "threshold_strategy": choice.strategy,
                "validation_selection_metrics": metrics,
                "warning": "Validation metrics are used for threshold selection and are not independent performance estimates.",
            }
        )
    usable = [run for run in runs if run.get("available", True) and "threshold" in run]
    thresholds = [float(run["threshold"]) for run in usable]
    return {
        "available": bool(usable),
        "method": "repeated stratified group splits within development data; final test groups excluded",
        "seeds": [int(seed) for seed in seeds],
        "runs": runs,
        "threshold_summary": (
            {
                "min": min(thresholds),
                "median": float(np.median(thresholds)),
                "max": max(thresholds),
                "range": max(thresholds) - min(thresholds),
            }
            if thresholds
            else None
        ),
        "limitation": "Synthetic/unknown-provenance data remain diagnostics; repeated splits do not establish real-world performance.",
    }


def evaluate(
    data_path: str | Path = DEFAULT_DATA,
    supplement_path: str | Path | Iterable[str | Path] | None = DEFAULT_SUPPLEMENTS,
    model_path: str | Path = DEFAULT_MODEL,
    holdout_path: str | Path | None = DEFAULT_HOLDOUT,
    plot_path: str | Path | None = DEFAULT_PLOT,
    *,
    json_output: str | Path | None = None,
    strict_supplement_paths: bool = False,
    strict_data: bool = True,
    val_size: float | None = None,
    test_size: float | None = None,
    seed: int | None = None,
    split_by: str | None = None,
    stability_seeds: Iterable[int] | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Evaluate the artifact; returns a JSON-safe metrics dictionary."""
    bundle = load_model(model_path, identify_artifact=True)
    threshold = bundle.threshold
    dataset = load_training_dataset(
        data_path,
        supplement_path,
        strict_data=strict_data,
        strict_supplement_paths=strict_supplement_paths,
    )
    split = _split_from_artifact(
        bundle, dataset, {"val_size": val_size, "test_size": test_size, "seed": seed, "split_by": split_by}
    )
    train_set, val_set, test_set = split_dataset(dataset, split)

    warnings = [*dataset.warnings, *split.warnings, *_data_hash_warnings(bundle, dataset)]
    for split_name, split_data in (("validation", val_set), ("test", test_set)):
        small = {
            label: split_data.labels.count(label) for label in ("ham", "spam") if split_data.labels.count(label) < 30
        }
        if small:
            warnings.append(
                f"Small class support in {split_name} split: {small}; precision/recall estimates may be unstable."
            )
    artifact_split = bundle.metadata.get("split")
    artifact_split = artifact_split if isinstance(artifact_split, dict) else {}
    if artifact_split.get("group_fingerprint"):
        current_fingerprint = (
            split.group_fingerprint(dataset.groups)
            if artifact_split.get("group_fingerprint_version") == "row-membership-v1"
            else split.legacy_group_fingerprint(dataset.groups)
        )
        if current_fingerprint != artifact_split["group_fingerprint"]:
            warnings.append(
                "The reproduced split fingerprint differs from the artifact's training split; "
                "the data or split configuration changed since training."
            )

    val_probabilities = _probabilities(bundle, val_set)
    test_probabilities = _probabilities(bundle, test_set)
    config = bundle.metadata.get("training_config")
    config = config if isinstance(config, dict) else {}
    target_precision = _metadata_number(config.get("target_precision"))
    min_recall = _metadata_number(config.get("min_recall"))
    false_positive_cost = _metadata_number(config.get("false_positive_cost"))
    false_negative_cost = _metadata_number(config.get("false_negative_cost"))
    settings_malformed = (
        ("target_precision" in config and (target_precision is None or not 0 <= target_precision <= 1))
        or ("min_recall" in config and (min_recall is None or not 0 <= min_recall <= 1))
        or (("false_positive_cost" in config) != ("false_negative_cost" in config))
        or (config.get("false_positive_cost") is not None and false_positive_cost is None)
        or (config.get("false_negative_cost") is not None and false_negative_cost is None)
        or (
            false_positive_cost is not None
            and (false_positive_cost <= 0 or false_negative_cost is None or false_negative_cost <= 0)
        )
        or (false_negative_cost is not None and false_positive_cost is None)
    )
    target_precision = target_precision if target_precision is not None and 0 <= target_precision <= 1 else 0.98
    min_recall = min_recall if min_recall is not None and 0 <= min_recall <= 1 else 0.0
    if settings_malformed:
        false_positive_cost = false_negative_cost = None
    recomputed = select_threshold(
        val_set.labels,
        val_probabilities,
        target_precision=target_precision,
        min_recall=min_recall,
        false_positive_cost=false_positive_cost,
        false_negative_cost=false_negative_cost,
    )
    if settings_malformed:
        warnings.append(
            "Recorded threshold-selection settings are malformed; safe defaults were used for this diagnostic."
        )
    threshold_diagnostic = _threshold_diagnostic(bundle, recomputed.threshold)
    if threshold_diagnostic["status"] in {
        "validation_policy_mismatch",
        "policy_metadata_inconsistent",
        "adoption_metadata_inconsistent",
        "artifact_threshold_mismatch",
        "policy_metadata_malformed",
    }:
        warnings.append(
            "Recorded threshold policy metadata is incomplete or inconsistent; inspect it separately from dataset hashes and split fingerprints."
        )
    elif threshold_diagnostic["status"] == "validation_candidate_drift":
        warnings.append(
            "The saved validation candidate differs from the candidate recomputed on this validation split; see dataset hashes and split fingerprints for evidence of changed inputs."
        )
    elif threshold_diagnostic["status"] == "policy_metadata_absent" and abs(recomputed.threshold - threshold) > 1e-9:
        warnings.append(
            "Artifact threshold differs from the candidate recomputed on the current validation split, "
            "but threshold-policy metadata is absent; see split and data hash diagnostics separately."
        )

    test_metrics = binary_metrics(test_set.labels, test_probabilities, threshold)
    test_frame_with_length = _length_strata(test_set.frame)
    test_metrics["campaign_bootstrap_95"] = campaign_bootstrap_intervals(
        test_set.frame, test_probabilities, threshold, seed=split.seed
    )
    test_at_default = binary_metrics(test_set.labels, test_probabilities, 0.5)
    test_calibration = calibration_metrics(test_set.labels, test_probabilities)
    baseline_mode = bundle.metadata.get("text_feature_mode")
    baseline_mode = baseline_mode if baseline_mode in {"word", "char", "combined"} else "word"
    baseline_result = _baseline_report(train_set, test_set, text_features=baseline_mode, seed=split.seed)
    thresholds = sorted({*KEY_THRESHOLDS, round(threshold, 4)})
    validation_sweep = threshold_sweep(val_set.labels, val_probabilities, thresholds=thresholds)

    results: dict[str, Any] = {
        "report_schema_version": 2,
        "run": _benchmark_run_info(bundle.artifact_sha256),
        "banner": _provenance_banner(test_set),
        "model": bundle.model_info(),
        "training_config": bundle.metadata.get("training_config", {}),
        "threshold": threshold,
        "threshold_diagnostic": threshold_diagnostic,
        "score_interpretation": _score_interpretation(bundle),
        "dataset": dataset.summary(),
        "split": split.as_dict(dataset.groups),
        "split_summary": {
            name: {
                "rows": len(indices),
                "class_counts": {
                    label: int((dataset.frame.iloc[indices]["label"] == label).sum()) for label in ("ham", "spam")
                },
                "groups": int(dataset.frame.iloc[indices]["group"].nunique()),
                "provenance": _coverage_counts(dataset.frame.iloc[indices], "data_kind"),
                "language": _coverage_counts(dataset.frame.iloc[indices], "language"),
                "category": _coverage_counts(dataset.frame.iloc[indices], "category"),
            }
            for name, indices in split.splits.items()
        },
        "validation": {
            "threshold_selection": recomputed.as_dict(),
            "sweep": validation_sweep,
        },
        "test": {
            "at_threshold": test_metrics,
            "at_default_0.5": test_at_default,
            "calibration": test_calibration,
            "by_data_kind": per_group_metrics(
                test_set.frame, test_probabilities, threshold, group_columns=("data_kind",)
            ),
            "by_source_category_language": per_group_metrics(
                test_set.frame, test_probabilities, threshold, group_columns=("source_file", "category", "language")
            ),
            "by_language": per_group_metrics(
                test_set.frame, test_probabilities, threshold, group_columns=("language",)
            ),
            "by_category": per_group_metrics(
                test_set.frame, test_probabilities, threshold, group_columns=("category",)
            ),
            "by_message_length_range": per_group_metrics(
                test_frame_with_length, test_probabilities, threshold, group_columns=("message_length_range",)
            ),
        },
        "baseline": baseline_result,
        "warnings": warnings,
    }
    if stability_seeds is not None:
        seeds = tuple(int(seed_value) for seed_value in stability_seeds)
        if not seeds:
            raise ValueError("stability_seeds must include at least one seed")
        dev_indices = sorted([*split.train_idx, *split.val_idx])
        results["development_stability"] = _repeated_group_stability(
            dataset,
            dev_indices,
            seeds=seeds,
            val_size=min(
                0.4,
                float(config.get("val_size", DEFAULT_VAL_SIZE))
                / max(0.01, 1.0 - float(config.get("test_size", DEFAULT_TEST_SIZE))),
            ),
            target_precision=float(config.get("target_precision", 0.98)),
            min_recall=float(config.get("min_recall", 0.0)),
            text_features=(
                str(bundle.metadata.get("text_feature_mode"))
                if str(bundle.metadata.get("text_feature_mode")) in {"word", "char", "combined"}
                else "word"
            ),
            false_positive_cost=config.get("false_positive_cost"),
            false_negative_cost=config.get("false_negative_cost"),
        )

    holdout: Dataset | None = None
    holdout_probabilities: list[float] = []
    if holdout_path is not None:
        holdout = load_holdout(holdout_path, strict=True)
    if holdout is not None:
        leakage = group_leakage_report(dataset, holdout)
        if leakage["template_family_overlap"]:
            warnings.append(
                f"Holdout template-family overlap: {leakage['template_family_overlap']}/"
                f"{leakage['holdout_template_family_count']} groups; holdout metrics are optimistic."
            )
        holdout_probabilities = _probabilities(bundle, holdout)
        holdout_metrics = binary_metrics(holdout.labels, holdout_probabilities, threshold)
        holdout_at_default = binary_metrics(holdout.labels, holdout_probabilities, 0.5)
        holdout_calibration = calibration_metrics(holdout.labels, holdout_probabilities)
        holdout_groups = per_group_metrics(
            holdout.frame, holdout_probabilities, threshold, group_columns=("source_file", "category", "language")
        )
        fp_categories = false_positive_categories(holdout.frame, holdout_probabilities, threshold)
        flagged_legit = sum(fp_categories.values())
        by_category = {
            name: {
                "rows": int((holdout.frame["category"] == name).sum()),
                "ham_rows": int(((holdout.frame["category"] == name) & (holdout.frame["label"] == "ham")).sum()),
                "false_positives": fp_categories.get(name, 0),
            }
            for name in sorted(set(holdout.frame["category"].astype(str)))
        }
        small_categories = {
            name: entry["ham_rows"]
            for name, entry in by_category.items()
            if entry["ham_rows"] and entry["ham_rows"] < 10
        }
        if small_categories:
            warnings.append(
                "Small legitimate holdout category support "
                f"({small_categories}); category false-positive counts are descriptive only."
            )
        results["holdout"] = {
            "banner": _provenance_banner(holdout),
            "data_note": bundle.data_note,
            "at_threshold": holdout_metrics,
            "campaign_bootstrap_95": campaign_bootstrap_intervals(
                holdout.frame, holdout_probabilities, threshold, seed=split.seed
            ),
            "at_default_0.5": holdout_at_default,
            "calibration": holdout_calibration,
            "by_source_category_language": holdout_groups,
            "false_positive_categories": fp_categories,
            "legitimate_flagged_total": flagged_legit,
            "by_category": by_category,
            "leakage": leakage,
            "errors": _errors(
                holdout,
                holdout_probabilities,
                threshold,
                probability_calibrated=bundle.metadata.get("probability_calibrated") is True,
            ),
        }

    results = jsonable(results)
    diagnostic_probabilities = spam_probabilities(bundle, list(PHILIPPINE_EXAMPLES))
    results["diagnostic_examples"] = [
        {
            "example_id": index + 1,
            "prediction": "spam" if probability >= threshold else "ham",
            "spam_score": round(float(probability), 4),
        }
        for index, probability in enumerate(diagnostic_probabilities)
    ]
    if plot_path:
        _plot(
            results, test_set, test_probabilities, val_set, val_probabilities, holdout, holdout_probabilities, plot_path
        )
    if json_output:
        output = Path(json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        if verbose:
            print(f"Evaluation metrics written to {output}")
    if verbose:
        _print_report(results, threshold, holdout)
    return results


def _errors(
    dataset: Dataset,
    probabilities: list[float],
    threshold: float,
    *,
    probability_calibrated: bool = False,
) -> list[dict[str, Any]]:
    predictions = ["spam" if probability >= threshold else "ham" for probability in probabilities]
    errors: list[dict[str, Any]] = []
    for index, (label, prediction) in enumerate(zip(dataset.labels, predictions)):
        if label == prediction:
            continue
        errors.append(
            {
                "index": index,
                "label": label,
                "prediction": prediction,
                "spam_score": round(float(probabilities[index]), 4),
                "probability_calibrated": probability_calibrated,
                "category": str(dataset.frame.iloc[index].get("category", "unknown")),
                "language": str(dataset.frame.iloc[index].get("language", "unknown")),
            }
        )
    return errors


def _plot(
    results: dict[str, Any],
    test_set: Dataset,
    test_probabilities: list[float],
    val_set: Dataset,
    val_probabilities: list[float],
    holdout: Dataset | None,
    holdout_probabilities: list[float],
    plot_path: str | Path,
) -> None:
    threshold = float(results["threshold"])
    figure, axes = plt.subplots(2, 2, figsize=(13, 10))

    predictions = ["spam" if probability >= threshold else "ham" for probability in test_probabilities]
    matrix = confusion_matrix(test_set.labels, predictions, labels=["ham", "spam"])
    ConfusionMatrixDisplay(matrix, display_labels=["ham", "spam"]).plot(
        ax=axes[0, 0], cmap="Blues", values_format="d", colorbar=False
    )
    axes[0, 0].set_title(f"Test split @ threshold {threshold:.2f}")

    sweep = threshold_sweep(val_set.labels, val_probabilities)
    thresholds = [row["threshold"] for row in sweep]
    axes[0, 1].plot(thresholds, [row["precision"] for row in sweep], label="precision (spam)")
    axes[0, 1].plot(thresholds, [row["recall"] for row in sweep], label="recall (spam)")
    axes[0, 1].axvline(threshold, color="black", linestyle="--", label=f"chosen {threshold:.2f}")
    axes[0, 1].set_title("Validation threshold tradeoff")
    axes[0, 1].set_xlabel("threshold")
    axes[0, 1].set_ylim(0, 1.05)
    axes[0, 1].legend(loc="best")

    calibration = results["test"]["calibration"]
    bins = [entry for entry in calibration["bins"] if entry["count"]]
    if bins:
        axes[1, 0].plot([1, 0], [1, 0], linestyle=":", color="gray", label="perfect")
        axes[1, 0].plot(
            [entry["mean_probability"] for entry in bins],
            [entry["observed_rate"] for entry in bins],
            marker="o",
            label="test reliability",
        )
    axes[1, 0].set_title(f"Calibration (test) ECE={calibration['expected_calibration_error']:.3f}")
    axes[1, 0].set_xlabel(
        f"mean {'calibrated estimate' if results['model'].get('probability_calibrated') else 'model score'}"
    )
    axes[1, 0].set_ylabel("observed spam rate")
    axes[1, 0].set_xlim(0, 1)
    axes[1, 0].set_ylim(0, 1)
    axes[1, 0].legend(loc="best")

    if holdout is not None and holdout_probabilities:
        fp = false_positive_categories(holdout.frame, holdout_probabilities, threshold)
        if fp:
            names = list(fp)
            axes[1, 1].bar(names, [fp[name] for name in names], color="#dc2626")
            axes[1, 1].set_title("Legit holdout messages flagged (by category)")
            axes[1, 1].tick_params(axis="x", rotation=30)
        else:
            axes[1, 1].text(0.5, 0.5, "0 legitimate holdout messages flagged", ha="center", va="center")
            axes[1, 1].set_axis_off()
    else:
        axes[1, 1].text(0.5, 0.5, "No holdout configured", ha="center", va="center")
        axes[1, 1].set_axis_off()
    figure.suptitle(f"{results['banner']}\nmodel={results['model']['model_version']}", fontsize=10)
    figure.tight_layout()
    output = Path(plot_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)


def _print_report(results: dict[str, Any], threshold: float, holdout: Dataset | None) -> None:
    print(f"\n=== {results['banner']} ===")
    print(results["model"]["data_note"])
    print(f"model_version={results['model']['model_version']} threshold={threshold:.2f}")
    print(f"Score interpretation: {results['score_interpretation']}")
    print(f"Threshold diagnostic: {results['threshold_diagnostic']}")
    split_summary = results["split_summary"]
    print("\n=== Split ===")
    for name in ("train", "val", "test"):
        print(
            f"{name:>5}: rows={split_summary[name]['rows']:>5} "
            f"groups={split_summary[name]['groups']:>4} classes={split_summary[name]['class_counts']}"
        )

    print("\n=== Validation threshold tuning (used to pick the threshold) ===")
    print(results["validation"]["threshold_selection"]["note"])
    print(f"{'threshold':>9} | {'precision':>9} | {'recall':>7} | {'FP':>5} | {'FN':>5}")
    for row in results["validation"]["sweep"]:
        marker = " <- chosen" if abs(row["threshold"] - threshold) < 1e-9 else ""
        print(
            f"{row['threshold']:>9.2f} | {row['precision']:>9.4f} | {row['recall']:>7.4f} | "
            f"{row['fp']:>5d} | {row['fn']:>5d}{marker}"
        )

    print("\n=== Test split ===")
    print(_format_metrics("at tuned threshold", results["test"]["at_threshold"]))
    print(_format_metrics("at default 0.5", results["test"]["at_default_0.5"]))
    print("Test metrics by provenance:")
    for group in results["test"]["by_data_kind"]:
        print(_format_metrics(group["data_kind"], group))
    calibration = results["test"]["calibration"]
    print(
        f"Calibration: Brier={calibration['brier_score']:.4f} log_loss={calibration['log_loss']:.4f} "
        f"ECE={calibration['expected_calibration_error']:.4f}"
    )

    if "holdout" in results:
        holdout_results = results["holdout"]
        print(f"\n=== {holdout_results['banner']} (separate holdout) ===")
        print(_format_metrics("holdout at tuned threshold", holdout_results["at_threshold"]))
        print(_format_metrics("holdout at 0.5", holdout_results["at_default_0.5"]))
        print(f"Legitimate holdout messages flagged: {holdout_results['legitimate_flagged_total']}")
        if holdout_results["false_positive_categories"]:
            print(f"False positives by category: {holdout_results['false_positive_categories']}")
        print("False-positive coverage by legitimate category:")
        for name in LEGIT_CATEGORIES:
            entry = holdout_results["by_category"].get(name)
            if entry:
                print(f"  {name:>16}: {entry['false_positives']} FP of {entry['ham_rows']} legit rows")
        leakage = holdout_results["leakage"]
        print(
            f"Template-family overlap with training: {leakage['template_family_overlap']}/"
            f"{leakage['holdout_template_family_count']} groups "
            f"({leakage['template_family_overlap_ratio']:.0%})"
        )
        if holdout_results["errors"]:
            print(f"Errors ({len(holdout_results['errors'])}; message content omitted):")
            for error in holdout_results["errors"]:
                print(
                    f"  [{error['label']} -> {error['prediction']} "
                    f"score={error['spam_score']:.3f}] "
                    f"category={error['category']} language={error['language']}"
                )
    else:
        print("\nNo separate holdout configured; internal test split only.")

    print("\n=== Diagnostic examples from the project brief (not a benchmark) ===")
    for entry in results["diagnostic_examples"]:
        print(f"example {entry['example_id']}: {entry['prediction']:>4} (spam score={entry['spam_score']:.3f})")

    for warning in results["warnings"]:
        print(f"warning: {warning}")


def _parse_supplements(args: argparse.Namespace):
    if args.no_supplements and args.supplement:
        raise SystemExit("error: --no-supplements cannot be combined with --supplement")
    if args.no_supplements:
        return None, False
    if args.supplement is None:
        return DEFAULT_SUPPLEMENTS, False
    return args.supplement, True


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a trained SMS detector artifact.")
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument(
        "--supplement",
        action="extend",
        nargs="+",
        default=None,
        metavar="CSV",
        help="Supplement CSV(s); repeatable. Omit for defaults; 'none' or --no-supplements disables.",
    )
    parser.add_argument("--no-supplements", action="store_true")
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT), help="Holdout CSV; pass 'none' to skip.")
    parser.add_argument("--plot", default=str(DEFAULT_PLOT), help="Plot output path; pass 'none' to skip.")
    parser.add_argument("--json-out", default=None, help="Write JSON metrics (no raw messages) to this path.")
    parser.add_argument("--lenient-data", action="store_true")
    parser.add_argument(
        "--stability-seeds",
        type=int,
        nargs="+",
        default=None,
        help="Optional repeated group-aware train/validation seeds within development groups (never uses final test groups).",
    )
    args = parser.parse_args(argv)

    supplements, strict_supplement_paths = _parse_supplements(args)
    holdout = None if args.holdout.strip().lower() == "none" else args.holdout
    plot = None if args.plot.strip().lower() == "none" else args.plot
    try:
        evaluate(
            data_path=args.data,
            supplement_path=supplements,
            model_path=args.model,
            holdout_path=holdout,
            plot_path=plot,
            json_output=args.json_out,
            strict_supplement_paths=strict_supplement_paths,
            strict_data=not args.lenient_data,
            stability_seeds=args.stability_seeds,
        )
    except DatasetError as exc:
        print(f"data error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
