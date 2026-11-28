"""Project fixed-threshold public diagnostic results under hypothetical class priors."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "docs" / "benchmarks" / "v2-1-0-gates-20261128.json"
PUBLIC_SETS = ("tagalog_heldout_groups", "ph_inbox")
MODEL_ROLES = ("old_model", "new_model")
PRIORS = (0.01, 0.05, 0.10, 0.25, 0.50)
MAX_REPORT_BYTES = 2 * 1024 * 1024


def project_confusion(confusion: dict[str, int], prevalence: float) -> dict[str, float | None]:
    """Return expected counts per 1,000, conditional on fixed TPR and FPR."""
    if set(confusion) != {"tp", "fp", "tn", "fn"} or any(
        type(count) is not int or count < 0 for count in confusion.values()
    ):
        raise ValueError("Invalid aggregate confusion counts.")
    if isinstance(prevalence, bool) or not math.isfinite(prevalence) or not 0 < prevalence < 1:
        raise ValueError("Hypothetical prevalence must be strictly between zero and one.")
    tp, fp, tn, fn = (confusion[key] for key in ("tp", "fp", "tn", "fn"))
    if not (tp + fn and fp + tn):
        raise ValueError("Both observed classes are required for projection.")
    recall = tp / (tp + fn)
    fpr = fp / (fp + tn)
    expected_tp = 1000 * prevalence * recall
    expected_fp = 1000 * (1 - prevalence) * fpr
    return {
        "hypothetical_spam_prevalence": prevalence,
        "expected_true_positive_per_1000": round(expected_tp, 6),
        "expected_false_positive_per_1000": round(expected_fp, 6),
        "expected_false_negative_per_1000": round(1000 * prevalence * (1 - recall), 6),
        "expected_true_negative_per_1000": round(1000 * (1 - prevalence) * (1 - fpr), 6),
        "expected_precision": round(expected_tp / (expected_tp + expected_fp), 6)
        if expected_tp + expected_fp
        else None,
    }


def analyze_report(path: Path) -> dict[str, Any]:
    """Read only existing aggregate evidence; do not open datasets or artifacts."""
    with path.open("rb") as handle:
        content = handle.read(MAX_REPORT_BYTES + 1)
    if len(content) > MAX_REPORT_BYTES:
        raise ValueError("Aggregate report exceeds the input size limit.")
    report = json.loads(content)
    if (
        not isinstance(report, dict)
        or report.get("record") != "v2.1.0-candidate preregistered gate evaluation on frozen sets"
    ):
        raise ValueError("Expected the published v2.1.0 gate diagnostic record.")
    output: dict[str, Any] = {}
    for corpus in PUBLIC_SETS:
        dataset = report["frozen_sets"][corpus]
        models: dict[str, Any] = {}
        supports = set()
        thresholds = set()
        for role in MODEL_ROLES:
            result = dataset[role]
            confusion = result["confusion"]
            scenarios = [project_confusion(confusion, prevalence) for prevalence in PRIORS]
            ham = confusion["tn"] + confusion["fp"]
            spam = confusion["tp"] + confusion["fn"]
            if ham != result["ham"] or spam != result["spam"] or ham + spam != result["n"]:
                raise ValueError("Observed support does not match aggregate counts.")
            threshold = result["decision_threshold"]
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
                raise ValueError("Invalid stored threshold in aggregate report.")
            supports.add((ham, spam))
            thresholds.add(threshold)
            models[role] = {
                "threshold": threshold,
                "observed_confusion": confusion,
                "observed_prevalence": round(spam / (spam + ham), 6),
                "observed_recall": round(confusion["tp"] / spam, 6),
                "observed_fpr": round(confusion["fp"] / ham, 6),
                "scenarios": scenarios,
            }
        if len(supports) != 1 or len(thresholds) != 1:
            raise ValueError("Compared public results must have identical class support and threshold.")
        output[corpus] = models
    return {
        "schema_version": 1,
        "purpose": "hypothetical_prior_shift_diagnostic",
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "public_diagnostics": output,
        "limitations": [
            "Hypothetical prevalence values are not measured Philippine prevalence.",
            "Expected counts assume unchanged within-class error rates; actual distribution shifts can change them.",
            "Uncertainty, donor dependence and campaign dependence are not modeled in these scenarios.",
            "No threshold selection, model fitting, sealed evaluation or release decision is performed.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        result = analyze_report(args.report)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        print("Prior-shift diagnostic refused: invalid published aggregate report.", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
