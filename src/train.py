"""Train, tune, evaluate, and persist the SMS classifier.

Pipeline:
1. Load base + all supplement CSVs (schema/label/duplicate/class validation).
2. Deduplicate globally, then create deterministic group-aware train/val/test
   splits (no template family crosses a boundary).
3. Fit a MultinomialNB baseline. Choose the primary classifier (class-balanced
   LogisticRegression or LinearSVC over a C grid) by group-aware
   cross-validated spam F1 on the training split, then calibrate it with
   sigmoid CalibratedClassifierCV.
4. Use a 0.5 decision threshold unless the validation-tuned threshold shows a
   robust out-of-fold F1 gain (see ``src.model_selection``); never tune on the
   test split or the holdout.
5. Save one joblib artifact containing the pipeline, threshold, label mapping,
   data-source hashes, training configuration, version, and measured metrics.
"""

from __future__ import annotations

import argparse
import json
import platform
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import sklearn
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
    dataset_manifest,
    group_leakage_report,
    grouped_splits,
    load_holdout,
    load_training_dataset,
    resolve_supplement_paths,
    split_dataset,
)
from src.data import (
    load_dataset as load_dataset_frame,
)
from src.features import FEATURE_VERSION, TEXT_FEATURE_MODES, make_model
from src.metrics import (
    binary_metrics,
    calibration_metrics,
    false_positive_categories,
    jsonable,
    per_group_metrics,
    select_threshold,
    threshold_sweep,
)
from src.model_selection import (
    calibrated_model,
    out_of_fold_probabilities,
    robust_threshold_decision,
    select_classifier,
)
from src.predict import ARTIFACT_SCHEMA_VERSION, DEFAULT_MODEL, ModelBundle, spam_probabilities

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_PRECISION = 0.95
DEFAULT_MIN_RECALL = 0.80
MIN_EVALUATION_CLASS_COUNT = 30
THRESHOLD_POLICIES = ("cv-robust", "validation")
KEY_THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

# Backward-compatible aliases for the notebook and older scripts.
DEFAULT_SUPPLEMENT = DEFAULT_SUPPLEMENTS
TEST_SIZE = DEFAULT_TEST_SIZE
RANDOM_STATE = DEFAULT_SEED


def load_dataset(path: str | Path) -> tuple[list[str], list[str]]:
    """Deprecated tuple-returning wrapper; prefer :func:`src.data.load_dataset`."""
    dataset = load_dataset_frame(path, role="data", require_both_classes=False, strict=False, min_class_count=0)
    return dataset.messages, dataset.labels


def load_training_data(
    data_path: str | Path = DEFAULT_DATA,
    supplement_path: str | Path | Iterable[str | Path] | None = DEFAULT_SUPPLEMENTS,
) -> tuple[list[str], list[str]]:
    """Deprecated tuple-returning wrapper; prefer :func:`src.data.load_training_dataset`."""
    dataset = load_training_dataset(data_path, supplement_path)
    return dataset.messages, dataset.labels


def _now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _class_counts(dataset: Dataset) -> dict[str, int]:
    return dataset.class_counts


def _probabilities(pipeline, messages: list[str]) -> list[float]:
    bundle = ModelBundle(pipeline=pipeline, threshold=0.5, metadata={"model_version": "in-training"})
    return spam_probabilities(bundle, messages)


def _metrics(pipeline, dataset: Dataset, threshold: float) -> tuple[dict[str, Any], list[float]]:
    probabilities = _probabilities(pipeline, dataset.messages)
    return binary_metrics(dataset.labels, probabilities, threshold), probabilities


def _key_sweep(labels: list[str], probabilities: list[float], chosen: float) -> list[dict[str, Any]]:
    thresholds = sorted({*KEY_THRESHOLDS, round(float(chosen), 4)})
    return threshold_sweep(labels, probabilities, thresholds=thresholds)


def _format_metrics(label: str, metrics: dict[str, Any]) -> str:
    return (
        f"{label}: precision={metrics['precision']:.4f} recall={metrics['recall']:.4f} "
        f"f1={metrics['f1']:.4f} accuracy={metrics['accuracy']:.4f} "
        f"FP={metrics['fp']} FN={metrics['fn']} (n={metrics['support']})"
    )


def _split_summary(split, dataset: Dataset) -> dict[str, Any]:
    frame = dataset.frame
    summary: dict[str, Any] = {}
    for name, indices in split.splits.items():
        subset = frame.iloc[indices]
        summary[name] = {
            "rows": int(len(subset)),
            "groups": int(subset["group"].nunique()),
            "class_counts": {label: int((subset["label"] == label).sum()) for label in ("ham", "spam")},
        }
    return summary


def train(
    data_path: str | Path = DEFAULT_DATA,
    model_path: str | Path = DEFAULT_MODEL,
    supplement_path: str | Path | Iterable[str | Path] | None = DEFAULT_SUPPLEMENTS,
    *,
    holdout_path: str | Path | None = DEFAULT_HOLDOUT,
    val_size: float = DEFAULT_VAL_SIZE,
    test_size: float = DEFAULT_TEST_SIZE,
    random_state: int = DEFAULT_SEED,
    target_precision: float = DEFAULT_TARGET_PRECISION,
    min_recall: float = DEFAULT_MIN_RECALL,
    false_positive_cost: float | None = None,
    false_negative_cost: float | None = None,
    split_by: str = "group",
    strict_data: bool = True,
    strict_supplement_paths: bool = False,
    model_version: str | None = None,
    text_features: str = "combined",
    threshold_policy: str = "cv-robust",
    write_metadata: bool = True,
    metadata_output: str | Path | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Train and persist the primary model. Returns the saved artifact mapping."""
    dataset = load_training_dataset(
        data_path,
        supplement_path,
        strict_data=strict_data,
        strict_supplement_paths=strict_supplement_paths,
    )
    split = grouped_splits(dataset, val_size=val_size, test_size=test_size, seed=random_state, split_by=split_by)
    train_set, val_set, test_set = split_dataset(dataset, split)
    for split_name, split_dataset_value in (("train", train_set), ("validation", val_set), ("test", test_set)):
        small_classes = {
            label: count
            for label, count in split_dataset_value.class_counts.items()
            if count < MIN_EVALUATION_CLASS_COUNT
        }
        if small_classes:
            dataset.warnings.append(
                f"{split_name} split has fewer than {MIN_EVALUATION_CLASS_COUNT} examples in one or more classes "
                f"({small_classes}); class metrics may be unstable."
            )
    if verbose:
        print("=== Dataset ===")
        print(
            f"rows={len(dataset)} classes={_class_counts(dataset)} groups={dataset.frame['group'].nunique()} "
            f"files={[record.as_dict()['path'] for record in dataset.records]}"
        )
        for warning in dataset.warnings:
            print(f"warning: {warning}")

    baseline = make_model(MultinomialNB(), text_features=text_features)
    if threshold_policy not in THRESHOLD_POLICIES:
        raise ValueError(f"threshold_policy must be one of {THRESHOLD_POLICIES}, got {threshold_policy!r}")
    train_frame = _frame(train_set.messages)
    selection = select_classifier(
        train_frame, train_set.labels, train_set.groups, text_features=text_features, seed=random_state
    )
    primary = calibrated_model(
        selection.estimator,
        text_features=text_features,
        seed=random_state,
        labels=train_set.labels,
        groups=train_set.groups,
    )
    baseline.fit(train_frame, train_set.labels)
    primary.fit(train_frame, train_set.labels)

    val_probabilities = _probabilities(primary, val_set.messages)
    choice = select_threshold(
        val_set.labels,
        val_probabilities,
        target_precision=target_precision,
        min_recall=min_recall,
        false_positive_cost=false_positive_cost,
        false_negative_cost=false_negative_cost,
    )
    if threshold_policy == "validation":
        threshold_decision: dict[str, Any] = {
            "policy": "validation",
            "threshold": choice.threshold,
            "adopted": True,
            "candidate_threshold": choice.threshold,
        }
    else:
        folds = out_of_fold_probabilities(
            selection.estimator,
            train_frame,
            train_set.labels,
            train_set.groups,
            text_features=text_features,
            seed=random_state,
        )
        threshold_decision = {"policy": "cv-robust", **robust_threshold_decision(choice.threshold, folds)}
    threshold = float(threshold_decision["threshold"])
    suspicious_threshold = round(max(0.001, min(threshold - 0.001, threshold / 2.0)), 4)

    baseline_metrics, _ = _metrics(baseline, test_set, 0.5)
    primary_metrics, test_probabilities = _metrics(primary, test_set, threshold)
    primary_at_default, _ = _metrics(primary, test_set, 0.5)
    primary_val_metrics = binary_metrics(val_set.labels, val_probabilities, threshold)
    test_calibration = calibration_metrics(test_set.labels, test_probabilities)
    val_calibration = calibration_metrics(val_set.labels, val_probabilities)

    holdout = load_holdout(holdout_path, strict=True) if holdout_path else None
    holdout_metrics: dict[str, Any] | None = None
    leakage: dict[str, Any] | None = None
    holdout_categories: list[dict[str, Any]] = []
    holdout_fp_categories: dict[str, int] = {}
    holdout_calibration: dict[str, Any] | None = None
    if holdout is not None:
        leakage = group_leakage_report(dataset, holdout)
        if leakage["template_family_overlap"]:
            dataset.warnings.append(
                f"Holdout template families overlap training in {leakage['template_family_overlap']} "
                f"of {leakage['holdout_template_family_count']} groups "
                f"({leakage['template_family_overlap_ratio']:.0%}); holdout scores are optimistic."
            )
        holdout_probabilities = _probabilities(primary, holdout.messages)
        holdout_metrics = binary_metrics(holdout.labels, holdout_probabilities, threshold)
        holdout_calibration = calibration_metrics(holdout.labels, holdout_probabilities)
        holdout_categories = per_group_metrics(
            holdout.frame, holdout_probabilities, threshold, group_columns=("source_file", "category")
        )
        holdout_fp_categories = false_positive_categories(holdout.frame, holdout_probabilities, threshold)

    created_at = _now_utc()
    version = model_version or f"{Path(model_path).stem}-{created_at[:10]}"
    warnings = [*dataset.warnings, *split.warnings]
    if not leakage:
        warnings.append("No separate holdout was evaluated; only the internal test split is reported.")
    metrics: dict[str, Any] = {
        "validation_at_threshold": primary_val_metrics,
        "test_at_threshold": primary_metrics,
        "test_at_default_0.5": primary_at_default,
        "baseline_multinomial_nb_at_0.5": baseline_metrics,
        "test_by_category": per_group_metrics(
            test_set.frame, test_probabilities, threshold, group_columns=("source_file", "category", "language")
        ),
        "validation_sweep": _key_sweep(val_set.labels, val_probabilities, threshold),
        "calibration": {"validation": val_calibration, "test": test_calibration},
        "classification_report": _classification_report(test_set.labels, test_probabilities, threshold),
    }
    if holdout_metrics is not None:
        metrics["holdout_at_threshold"] = holdout_metrics
        metrics["holdout_calibration"] = holdout_calibration
        metrics["holdout_by_category"] = holdout_categories
        metrics["holdout_false_positive_categories"] = holdout_fp_categories

    artifact: dict[str, Any] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "text_feature_mode": text_features,
        "model_version": version,
        "created_at": created_at,
        "python_version": platform.python_version(),
        "sklearn_version": sklearn.__version__,
        "label_map": {"ham": "ham", "spam": "spam"},
        "classes": [str(value) for value in primary.classes_],
        "threshold": threshold,
        "decision_threshold": threshold,  # explicit alias used by some clients
        "suspicious_threshold": suspicious_threshold,
        "threshold_selection": {**choice.as_dict(), "decision": jsonable(threshold_decision)},
        "model_selection": selection.as_dict(),
        "calibration_method": "sigmoid CalibratedClassifierCV (group-aware folds, training split only)",
        "training_config": {
            "data_role": "base",
            "supplement_count": len(_supplement_paths_used(supplement_path)),
            "holdout_evaluated": holdout is not None,
            "val_size": val_size,
            "test_size": test_size,
            "random_state": random_state,
            "target_precision": target_precision,
            "min_recall": min_recall,
            "false_positive_cost": false_positive_cost,
            "false_negative_cost": false_negative_cost,
            "split_by": split_by,
            "text_features": text_features,
            "threshold_policy": threshold_policy,
            "strict_data": strict_data,
        },
        "data_sources": [record.as_dict() for record in dataset.records],
        "holdout_source": holdout.records[0].as_dict() if holdout and holdout.records else None,
        "dataset": dataset.summary(),
        "dataset_manifest": dataset_manifest(
            dataset,
            extra={
                "split_method": split.method,
                "split_seed": split.seed,
                "split_fingerprint": split.group_fingerprint(dataset.groups),
                "split_fingerprint_version": "row-membership-v1",
            },
        ),
        "split": split.as_dict(dataset.groups),
        "split_summary": _split_summary(split, dataset),
        "holdout_leakage": leakage,
        "metrics": jsonable(metrics),
        "synthetic_training_data": (
            True
            if "synthetic" in set(train_set.frame["data_kind"])
            else None
            if "unknown" in set(train_set.frame["data_kind"])
            else False
        ),
        "training_data_kind_counts": train_set.frame["data_kind"].value_counts().to_dict(),
        # Sigmoid calibration is fitted on training folds only; test/holdout ECE is reported.
        "probability_calibrated": True,
        "data_note": (
            "Training data may include synthetic examples and messages with unverified provenance. "
            "Synthetic examples are engineering checks, not proof of real-world accuracy. "
            "Real-data labels alone do not establish representative Philippine performance."
        ),
        "warnings": [str(warning) for warning in warnings],
        "model": primary,
    }

    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path, compress=3)
    if write_metadata:
        sidecar = Path(metadata_output) if metadata_output else model_path.with_suffix(".metadata.json")
        payload = {key: value for key, value in artifact.items() if key != "model"}
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_path = model_path.with_suffix(".manifest.json")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(jsonable(artifact["dataset_manifest"]), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if verbose:
        _print_report(
            artifact=artifact,
            split=split,
            dataset=dataset,
            choice=choice,
            primary_metrics=primary_metrics,
            primary_at_default=primary_at_default,
            baseline_metrics=baseline_metrics,
            test_calibration=test_calibration,
            holdout_metrics=holdout_metrics,
            holdout_fp_categories=holdout_fp_categories,
            leakage=leakage,
            model_path=model_path,
        )
    return artifact


def _frame(messages: list[str]):
    from src.features import messages_to_frame

    return messages_to_frame(messages)


def _classification_report(labels: list[str], probabilities: list[float], threshold: float) -> dict[str, Any]:
    from sklearn.metrics import classification_report

    predicted = ["spam" if probability >= threshold else "ham" for probability in probabilities]
    return classification_report(labels, predicted, output_dict=True, zero_division=0)


def _supplement_paths_used(supplement_path) -> list[Path]:
    paths, _ = resolve_supplement_paths(supplement_path, strict=False)
    return paths


def _print_report(
    *,
    artifact: dict[str, Any],
    split,
    dataset: Dataset,
    choice,
    primary_metrics: dict[str, Any],
    primary_at_default: dict[str, Any],
    baseline_metrics: dict[str, Any],
    test_calibration: dict[str, Any],
    holdout_metrics: dict[str, Any] | None,
    holdout_fp_categories: dict[str, int],
    leakage: dict[str, Any] | None,
    model_path: Path,
) -> None:
    split_summary = artifact["split_summary"]
    print("\n=== Split ===")
    print(f"method={split.method} seed={split.seed}")
    for name in ("train", "val", "test"):
        entry = split_summary[name]
        print(f"{name:>5}: rows={entry['rows']:>5} groups={entry['groups']:>4} classes={entry['class_counts']}")
    for warning in split.warnings:
        print(f"warning: {warning}")

    selection = artifact["model_selection"]
    print("\n=== Model selection (training split, cross-validated spam F1) ===")
    for row in selection["candidates"]:
        marker = " <- selected" if row["candidate"] == selection["selected"] else ""
        print(f"{row['candidate']:>32}: {row['cv_f1_mean']:.4f} +/- {row['cv_f1_std']:.4f}{marker}")
    print(f"calibration: {artifact['calibration_method']}")

    print("\n=== Threshold tuning (validation only) ===")
    print(choice.note)
    print(
        f"chosen={choice.threshold:.2f} val precision={choice.precision:.4f} "
        f"val recall={choice.recall:.4f} achieved_target={choice.achieved_target}"
    )
    decision = artifact["threshold_selection"]["decision"]
    print(
        f"policy={decision['policy']} candidate={decision['candidate_threshold']} "
        f"adopted={decision['adopted']} fold_gains={decision.get('fold_f1_gains')} -> threshold={decision['threshold']}"
    )
    print(f"{'threshold':>9} | {'precision':>9} | {'recall':>7} | {'FP':>5} | {'FN':>5}")
    for row in artifact["metrics"]["validation_sweep"]:
        marker = " <- validation pick" if abs(row["threshold"] - choice.threshold) < 1e-9 else ""
        print(
            f"{row['threshold']:>9.2f} | {row['precision']:>9.4f} | {row['recall']:>7.4f} | "
            f"{row['fp']:>5d} | {row['fn']:>5d}{marker}"
        )

    print("\n=== Test split (reported at the served threshold) ===")
    print(_format_metrics("primary", primary_metrics))
    print(_format_metrics("primary @0.5", primary_at_default))
    print(_format_metrics("baseline NB @0.5", baseline_metrics))
    report = artifact["metrics"]["classification_report"]
    for label in ("ham", "spam"):
        row = report.get(label, {})
        print(
            f"  {label}: precision={row.get('precision', 0):.4f} recall={row.get('recall', 0):.4f} "
            f"f1={row.get('f1-score', 0):.4f} support={int(row.get('support', 0))}"
        )

    print("\n=== Calibration (test) ===")
    print(
        f"Brier={test_calibration['brier_score']:.4f} log_loss={test_calibration['log_loss']:.4f} "
        f"ECE={test_calibration['expected_calibration_error']:.4f}"
    )

    if holdout_metrics is not None:
        print("\n=== Synthetic Philippine holdout benchmark (NOT real-world performance) ===")
        print(_format_metrics("holdout", holdout_metrics))
        if holdout_fp_categories:
            print(f"Legitimate messages flagged by category: {holdout_fp_categories}")
        else:
            print("Legitimate messages flagged: 0")
        if leakage:
            print(
                f"Holdout template-family overlap with training: "
                f"{leakage['template_family_overlap']}/{leakage['holdout_template_family_count']} groups"
            )
    else:
        print("\nNo holdout configured; internal test split only.")

    for warning in artifact["warnings"]:
        print(f"warning: {warning}")
    print(f"\nSaved model bundle to {model_path}")
    print(f"model_version={artifact['model_version']} threshold={artifact['threshold']:.2f}")


def _parse_supplements(args: argparse.Namespace) -> tuple[Any, bool]:
    if args.no_supplements and args.supplement:
        raise SystemExit("error: --no-supplements cannot be combined with --supplement")
    if args.no_supplements:
        return None, False
    if args.supplement is None:
        return DEFAULT_SUPPLEMENTS, False
    return args.supplement, True


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the Philippine SMS spam/scam detector.")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="Base labeled CSV (label,message or Kaggle v1/v2).")
    parser.add_argument(
        "--supplement",
        action="extend",
        nargs="+",
        default=None,
        metavar="CSV",
        help=(
            "Supplement CSV(s); repeatable. Omit to use the default synthetic supplements; "
            "pass 'none' (alone) or --no-supplements for base data only."
        ),
    )
    parser.add_argument("--no-supplements", action="store_true", help="Disable all supplement CSVs.")
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT), help="Separate holdout CSV; pass 'none' to skip.")
    parser.add_argument("--output", default=str(DEFAULT_MODEL), help="Model bundle output path.")
    parser.add_argument("--metadata-output", default=None, help="Metadata JSON sidecar path (default: next to model).")
    parser.add_argument("--no-metadata", action="store_true", help="Do not write the JSON metadata sidecar.")
    parser.add_argument("--model-version", default=None, help="Human-readable artifact version label.")
    parser.add_argument(
        "--text-features",
        choices=TEXT_FEATURE_MODES,
        default="combined",
        help="TF-IDF representation to fit (default: word+char combined).",
    )
    parser.add_argument(
        "--threshold-policy",
        choices=THRESHOLD_POLICIES,
        default="cv-robust",
        help="cv-robust: use 0.5 unless the validation-tuned threshold improves out-of-fold F1 in every fold "
        "and by >=0.01 on average; validation: always use the validation-tuned threshold.",
    )
    parser.add_argument(
        "--val-size", type=float, default=DEFAULT_VAL_SIZE, help="Validation fraction for threshold tuning."
    )
    parser.add_argument(
        "--test-size", type=float, default=DEFAULT_TEST_SIZE, help="Held-out test fraction for reporting."
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed for reproducible splits/models.")
    parser.add_argument(
        "--target-precision",
        type=float,
        default=DEFAULT_TARGET_PRECISION,
        help=f"Validation spam precision target for threshold tuning (default {DEFAULT_TARGET_PRECISION}).",
    )
    parser.add_argument(
        "--min-recall",
        type=float,
        default=DEFAULT_MIN_RECALL,
        help=f"Minimum validation spam recall for threshold tuning (default {DEFAULT_MIN_RECALL}).",
    )
    parser.add_argument(
        "--false-positive-cost",
        type=float,
        default=None,
        help="Optional exploratory FP error cost; must be paired with --false-negative-cost (no production policy implied).",
    )
    parser.add_argument(
        "--false-negative-cost",
        type=float,
        default=None,
        help="Optional exploratory FN error cost; must be paired with --false-positive-cost (no production policy implied).",
    )
    parser.add_argument(
        "--split-by",
        choices=("group", "time", "random"),
        default="group",
        help="Split by template family (default), chronological campaign groups (requires dates), or random (diagnostic only).",
    )
    parser.add_argument(
        "--lenient-data", action="store_true", help="Drop blank rows with a warning instead of failing."
    )
    args = parser.parse_args(argv)

    supplements, strict_supplement_paths = _parse_supplements(args)
    holdout: str | None = args.holdout
    if holdout and holdout.strip().lower() == "none":
        holdout = None
    try:
        train(
            data_path=args.data,
            model_path=args.output,
            supplement_path=supplements,
            holdout_path=holdout,
            val_size=args.val_size,
            test_size=args.test_size,
            random_state=args.seed,
            target_precision=args.target_precision,
            min_recall=args.min_recall,
            false_positive_cost=args.false_positive_cost,
            false_negative_cost=args.false_negative_cost,
            split_by=args.split_by,
            strict_data=not args.lenient_data,
            strict_supplement_paths=strict_supplement_paths,
            model_version=args.model_version,
            text_features=args.text_features,
            threshold_policy=args.threshold_policy,
            write_metadata=not args.no_metadata,
            metadata_output=args.metadata_output,
        )
    except DatasetError as exc:
        print(f"data error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
