"""Evaluate a trained artifact on the internal test split and a separate holdout.

Important: the checked-in Philippine holdout is synthetic. Its scores are a
pipeline/benchmark sanity check, **not** evidence of real-world performance.
Every report is labelled accordingly, and per-source / per-category breakdowns
are reported when that metadata exists.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import ConfusionMatrixDisplay, confusion_matrix

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
from src.metrics import (
    binary_metrics,
    calibration_metrics,
    false_positive_categories,
    jsonable,
    per_group_metrics,
    select_threshold,
    threshold_sweep,
)
from src.predict import ModelBundle, load_model, spam_probabilities
from src.preprocess import redact_message

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "spam_detector_v1.pkl"
DEFAULT_PLOT = ROOT / "data" / "processed" / "evaluation.png"
KEY_THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
SYNTHETIC_BANNER = "SYNTHETIC BENCHMARK — NOT REAL-WORLD PERFORMANCE"
LEGIT_CATEGORIES = ("otp", "bank_alert", "delivery", "bill", "personal_taglish", "promo")

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
    config = bundle.metadata.get("training_config", {})
    val_size = overrides.get("val_size") or config.get("val_size", DEFAULT_VAL_SIZE)
    test_size = overrides.get("test_size") or config.get("test_size", DEFAULT_TEST_SIZE)
    seed_value = overrides.get("seed") if overrides.get("seed") is not None else config.get("random_state")
    seed = int(seed_value) if seed_value is not None else DEFAULT_SEED
    split_by = overrides.get("split_by") or config.get("split_by", "group")
    return grouped_splits(dataset, val_size=val_size, test_size=test_size, seed=seed, split_by=split_by)


def _data_hash_warnings(bundle: ModelBundle, dataset: Dataset) -> list[str]:
    recorded = {
        str(record.get("path")): str(record.get("sha256")) for record in bundle.metadata.get("data_sources", [])
    }
    warnings: list[str] = []
    for record in dataset.records:
        expected = recorded.get(str(record.path))
        if expected and expected != record.sha256:
            warnings.append(
                f"Data changed since training: {record.path} sha256 differs from the artifact. "
                "Metrics may not reproduce the trained model's results; retrain before trusting this report."
            )
    if recorded and not warnings:
        warnings.append("Data files match the artifact hashes recorded at training time.")
    return warnings


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
    show_messages: bool = False,
    val_size: float | None = None,
    test_size: float | None = None,
    seed: int | None = None,
    split_by: str | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Evaluate the artifact; returns a JSON-safe metrics dictionary."""
    bundle = load_model(model_path)
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
    artifact_split = bundle.metadata.get("split", {})
    if artifact_split.get("group_fingerprint"):
        current_fingerprint = split.group_fingerprint(dataset.groups)
        if current_fingerprint != artifact_split["group_fingerprint"]:
            warnings.append(
                "The reproduced split fingerprint differs from the artifact's training split; "
                "the data or split configuration changed since training."
            )

    val_probabilities = _probabilities(bundle, val_set)
    test_probabilities = _probabilities(bundle, test_set)
    config = bundle.metadata.get("training_config", {})
    recomputed = select_threshold(
        val_set.labels,
        val_probabilities,
        target_precision=float(config.get("target_precision", 0.98)),
        min_recall=float(config.get("min_recall", 0.0)),
    )
    if abs(recomputed.threshold - threshold) > 1e-9:
        warnings.append(
            f"Artifact threshold {threshold:.2f} differs from the threshold recomputed on the current "
            f"validation split ({recomputed.threshold:.2f}); data may have changed."
        )

    test_metrics = binary_metrics(test_set.labels, test_probabilities, threshold)
    test_at_default = binary_metrics(test_set.labels, test_probabilities, 0.5)
    test_calibration = calibration_metrics(test_set.labels, test_probabilities)
    test_groups = per_group_metrics(
        test_set.frame, test_probabilities, threshold, group_columns=("source_file", "category")
    )
    thresholds = sorted({*KEY_THRESHOLDS, round(threshold, 4)})
    validation_sweep = threshold_sweep(val_set.labels, val_probabilities, thresholds=thresholds)

    results: dict[str, Any] = {
        "banner": SYNTHETIC_BANNER,
        "model": bundle.model_info(),
        "threshold": threshold,
        "dataset": dataset.summary(),
        "split": split.as_dict(dataset.groups),
        "split_summary": {
            name: {
                "rows": len(indices),
                "class_counts": {
                    label: int((dataset.frame.iloc[indices]["label"] == label).sum()) for label in ("ham", "spam")
                },
                "groups": int(dataset.frame.iloc[indices]["group"].nunique()),
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
            "by_source_category": test_groups,
        },
        "warnings": warnings,
    }

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
        results["holdout"] = {
            "banner": SYNTHETIC_BANNER,
            "data_note": bundle.data_note,
            "at_threshold": holdout_metrics,
            "at_default_0.5": holdout_at_default,
            "calibration": holdout_calibration,
            "by_source_category_language": holdout_groups,
            "false_positive_categories": fp_categories,
            "legitimate_flagged_total": flagged_legit,
            "by_category": by_category,
            "leakage": leakage,
            "errors": _errors(holdout, holdout_probabilities, threshold, show_messages=show_messages),
        }

    results = jsonable(results)
    diagnostic_probabilities = spam_probabilities(bundle, list(PHILIPPINE_EXAMPLES))
    results["diagnostic_examples"] = [
        {
            "message": redact_message(message, max_length=120),
            "prediction": "spam" if probability >= threshold else "ham",
            "spam_probability": round(float(probability), 4),
        }
        for message, probability in zip(PHILIPPINE_EXAMPLES, diagnostic_probabilities)
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
        _print_report(results, threshold, holdout, show_messages)
    return results


def _errors(
    dataset: Dataset, probabilities: list[float], threshold: float, *, show_messages: bool
) -> list[dict[str, Any]]:
    predictions = ["spam" if probability >= threshold else "ham" for probability in probabilities]
    errors: list[dict[str, Any]] = []
    for index, (label, prediction) in enumerate(zip(dataset.labels, predictions)):
        if label == prediction:
            continue
        message = dataset.messages[index]
        errors.append(
            {
                "index": index,
                "label": label,
                "prediction": prediction,
                "spam_probability": round(float(probabilities[index]), 4),
                "category": str(dataset.frame.iloc[index].get("category", "unknown")),
                "language": str(dataset.frame.iloc[index].get("language", "unknown")),
                "message": message if show_messages else redact_message(message),
                "redacted": not show_messages,
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
    axes[1, 0].set_xlabel("mean predicted spam probability")
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
    figure.suptitle(f"{SYNTHETIC_BANNER}\nmodel={results['model']['model_version']}", fontsize=10)
    figure.tight_layout()
    output = Path(plot_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)


def _print_report(results: dict[str, Any], threshold: float, holdout: Dataset | None, show_messages: bool) -> None:
    print(f"\n=== {SYNTHETIC_BANNER} ===")
    print(results["model"]["data_note"])
    print(f"model_version={results['model']['model_version']} threshold={threshold:.2f}")
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
    calibration = results["test"]["calibration"]
    print(
        f"Calibration: Brier={calibration['brier_score']:.4f} log_loss={calibration['log_loss']:.4f} "
        f"ECE={calibration['expected_calibration_error']:.4f}"
    )

    if "holdout" in results:
        holdout_results = results["holdout"]
        print(f"\n=== {SYNTHETIC_BANNER} (separate holdout) ===")
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
            print(f"Errors ({len(holdout_results['errors'])}); messages are redacted unless --show-messages:")
            for error in holdout_results["errors"]:
                print(
                    f"  [{error['label']} -> {error['prediction']} p={error['spam_probability']:.3f}] "
                    f"category={error['category']} {error['message']}"
                )
    else:
        print("\nNo separate holdout configured; internal test split only.")

    print("\n=== Diagnostic examples from the project brief (not a benchmark) ===")
    for entry in results["diagnostic_examples"]:
        print(f"{entry['prediction']:>4} (p={entry['spam_probability']:.3f}) | {entry['message']}")

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
    parser.add_argument(
        "--show-messages", action="store_true", help="Print full holdout messages in errors (synthetic data only)."
    )
    parser.add_argument("--lenient-data", action="store_true")
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
            show_messages=args.show_messages,
        )
    except DatasetError as exc:
        print(f"data error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
