"""Fail when a trained artifact's internal test F1 is below a floor.

Usage: python scripts/check_quality_gate.py models/uci.metadata.json --min-f1 0.90
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

PUBLIC_LICENSES = frozenset({"cc by 4 0", "cc0", "cc0 public domain", "public domain"})
REQUIRED_HOLDOUT_CLASSES = frozenset({"consented", "public_licensed", "public_english"})
SHA256_RE = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)
HOLDOUT_SCORE_FIELDS = (
    "threshold",
    "precision",
    "recall",
    "f1",
    "accuracy",
    "false_positive_rate",
    "predicted_spam_rate",
)


def _has_evaluated_holdout_metrics(value: object) -> bool:
    """Reject absent, empty, non-finite, or internally inconsistent results."""
    if not isinstance(value, dict):
        return False
    for field in HOLDOUT_SCORE_FIELDS:
        score = value.get(field)
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return False
        if not math.isfinite(float(score)) or not 0.0 <= float(score) <= 1.0:
            return False

    support = value.get("support")
    counts = [value.get(field) for field in ("tp", "fp", "tn", "fn")]
    if isinstance(support, bool) or not isinstance(support, int) or support <= 0:
        return False
    if any(isinstance(count, bool) or not isinstance(count, int) or count < 0 for count in counts):
        return False
    if sum(counts) != support:
        return False

    tp, fp, tn, fn = counts
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    expected_scores = {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": (tp + tn) / support,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "predicted_spam_rate": (tp + fp) / support,
    }
    if any(
        not math.isclose(float(value[field]), expected, rel_tol=1e-9, abs_tol=1e-9)
        for field, expected in expected_scores.items()
    ):
        return False

    support_spam = value.get("support_spam")
    support_ham = value.get("support_ham")
    return (
        isinstance(support_spam, int)
        and not isinstance(support_spam, bool)
        and isinstance(support_ham, int)
        and not isinstance(support_ham, bool)
        and support_spam >= 0
        and support_ham >= 0
        and support_spam == value["tp"] + value["fn"]
        and support_ham == value["fp"] + value["tn"]
        and support_spam + support_ham == support
    )


def classify_holdout_evidence(metadata: dict) -> str:
    """Classify one held-out source from message-free artifact metadata."""
    metrics = metadata.get("metrics")
    source = metadata.get("holdout_source")
    if not isinstance(metrics, dict) or not _has_evaluated_holdout_metrics(metrics.get("holdout_at_threshold")):
        return "none"
    if not isinstance(source, dict):
        return "unknown"
    if source.get("role") != "holdout" or not isinstance(source.get("sha256"), str):
        return "unknown"
    if not SHA256_RE.fullmatch(source["sha256"]):
        return "unknown"

    counts = source.get("data_kind_counts")
    if not isinstance(counts, dict) or not counts:
        return "unknown"
    positive_kinds: set[str] = set()
    for kind, count in counts.items():
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return "unknown"
        if count > 0:
            positive_kinds.add(str(kind).strip().lower())
    rows_loaded = source.get("rows_loaded")
    if isinstance(rows_loaded, bool) or not isinstance(rows_loaded, int) or rows_loaded <= 0:
        return "unknown"
    if sum(counts.values()) != rows_loaded:
        return "unknown"
    if len(positive_kinds) != 1:
        return "none" if not positive_kinds else "mixed"

    kind = next(iter(positive_kinds))
    if kind in {"synthetic", "unknown"}:
        return kind
    if kind == "consented":
        return "consented"
    if kind != "public":
        return "unknown"

    provenance = source.get("provenance")
    license_name = provenance.get("license") if isinstance(provenance, dict) else None
    dataset_id = provenance.get("dataset_id") if isinstance(provenance, dict) else None
    if (
        not isinstance(license_name, str)
        or not isinstance(dataset_id, str)
        or dataset_id.strip().casefold() in {"", "unknown"}
    ):
        return "public_unlicensed"
    normalized_license = re.sub(r"[^a-z0-9]+", " ", license_name.casefold()).strip()
    if normalized_license not in PUBLIC_LICENSES:
        return "public_unlicensed"

    languages = source.get("language_counts")
    if isinstance(languages, dict) and languages:
        if any(isinstance(count, bool) or not isinstance(count, int) or count < 0 for count in languages.values()):
            return "public_licensed"
        positive_languages = {str(language).strip().casefold() for language, count in languages.items() if count > 0}
        if sum(languages.values()) == rows_loaded and positive_languages and positive_languages <= {"en", "english"}:
            return "public_english"
    return "public_licensed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path, help="Metadata JSON sidecar written by src.train.")
    parser.add_argument("--min-f1", type=float, default=0.90, help="Minimum spam F1 on the internal test split.")
    parser.add_argument(
        "--require-real-holdout",
        action="store_true",
        help="Require one non-synthetic held-out source with consent or a recognized public license.",
    )
    args = parser.parse_args(argv)
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    holdout_class = classify_holdout_evidence(metadata)
    print(f"holdout_class={holdout_class}")
    if args.require_real_holdout and holdout_class not in REQUIRED_HOLDOUT_CLASSES:
        print(
            "FAIL: --require-real-holdout requires a consented holdout or a licensed non-synthetic public holdout.",
            file=sys.stderr,
        )
        return 2

    test = metadata["metrics"]["test_at_threshold"]
    f1 = float(test["f1"])
    summary = (
        f"test spam F1={f1:.4f} precision={float(test['precision']):.4f} recall={float(test['recall']):.4f} "
        f"threshold={float(metadata['threshold']):.2f} n={test.get('n', test.get('support', '?'))} "
        f"ECE={metadata['metrics']['calibration']['test']['expected_calibration_error']:.4f}"
    )
    print(summary)
    if f1 < args.min_f1:
        print(f"FAIL: test F1 {f1:.4f} is below the {args.min_f1:.2f} floor", file=sys.stderr)
        return 1
    print(f"PASS: test F1 >= {args.min_f1:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
