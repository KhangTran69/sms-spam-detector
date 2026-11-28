"""Paired synthetic-only formatting robustness diagnostic at a frozen threshold."""

from __future__ import annotations

import argparse
import json
import math
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.corpus_audit import Corpus, load_corpus
from src.dataset_schema import DEFAULT_HOLDOUT
from src.predict import ModelArtifactError, load_model, spam_probabilities

FORMATS: dict[str, Callable[[str], str]] = {
    "uppercase": str.upper,
    "decomposed_unicode": lambda text: unicodedata.normalize("NFD", text),
    "whitespace": lambda text: "  ".join(text.split()),
    "fullwidth_ascii": lambda text: "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in text),
}


def _decisions(score: Callable[[list[str]], list[float]], messages: list[str], threshold: float) -> list[bool]:
    values = score(messages)
    if len(values) != len(messages) or any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError("Invalid score vector.")
    return [value >= threshold for value in values]


def _errors(labels: tuple[str, ...], decisions: list[bool]) -> dict[str, int]:
    return {
        "fp": sum(label == "ham" and decision for label, decision in zip(labels, decisions)),
        "fn": sum(label == "spam" and not decision for label, decision in zip(labels, decisions)),
    }


def audit(corpus: Corpus, score: Callable[[list[str]], list[float]], threshold: float) -> dict[str, Any]:
    if (
        corpus.role != "synthetic_holdout"
        or len(corpus.messages) != len(corpus.labels)
        or set(corpus.labels) != {"ham", "spam"}
        or not math.isfinite(threshold)
        or not 0 < threshold < 1
    ):
        raise ValueError("Expected a labeled synthetic holdout and a valid fixed threshold.")
    messages = list(corpus.messages)
    baseline = _decisions(score, messages, threshold)
    baseline_errors = _errors(corpus.labels, baseline)
    variants: dict[str, Any] = {}
    for name, transform in FORMATS.items():
        altered = [transform(message) for message in messages]
        decisions = _decisions(score, altered, threshold)
        errors = _errors(corpus.labels, decisions)
        variants[name] = {
            "changed_rows": sum(before != after for before, after in zip(messages, altered)),
            "prediction_flips": sum(before != after for before, after in zip(baseline, decisions)),
            "errors": errors,
            "error_delta": {key: errors[key] - baseline_errors[key] for key in baseline_errors},
            "new_errors": sum(
                before == (label == "spam") and after != before
                for label, before, after in zip(corpus.labels, baseline, decisions)
            ),
            "corrected_errors": sum(
                before != (label == "spam") and after != before
                for label, before, after in zip(corpus.labels, baseline, decisions)
            ),
        }
    return {
        "schema_version": 1,
        "purpose": "synthetic_formatting_diagnostic_only",
        "source_sha256": list(corpus.source_hashes),
        "threshold": threshold,
        "class_counts": {label: corpus.labels.count(label) for label in ("ham", "spam")},
        "baseline_errors": baseline_errors,
        "variants": variants,
        "limitations": [
            "All rows are synthetic; formatting changes do not constitute independent observations.",
            "No threshold selection, calibration, field evaluation, or release decision is performed.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path, help="Trusted local model artifact")
    args = parser.parse_args(argv)
    try:
        corpus = load_corpus("synthetic_holdout", [DEFAULT_HOLDOUT])
        bundle = load_model(args.model, identify_artifact=True)
        report = audit(corpus, lambda messages: spam_probabilities(bundle, messages), bundle.threshold)
        report["model_sha256"] = bundle.artifact_sha256
    except (OSError, ValueError, ModelArtifactError):
        print("Synthetic robustness audit refused: check the local fixture and trusted model.", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
