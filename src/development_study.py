"""Aggregate-only, development-only class weight and formatting study.

Never writes a model artifact or opens a sealed holdout. Public inputs must be
separately approved development snapshots; a matching hash alone is not consent
or proof that rows are independent of a frozen evaluation set.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from sklearn.linear_model import LogisticRegression

from src.corpus_audit import PUBLIC_IDS, Corpus, compare_corpora, load_corpus
from src.dataset_schema import _normalized_message_key, make_group_key
from src.features import make_model, messages_to_frame
from src.metrics import binary_metrics, calibration_metrics
from src.model_selection import cv_splits
from src.robustness_audit import FORMATS

# Historical input hashes from docs/benchmarks/v2-1-0-gates-20261128.json.
# Reject whole frozen inputs, including the base/supplement containing held-out
# membership. Renaming/re-encoding does not prove independence: the custodian
# must approve and verify the separate development snapshot before use.
FROZEN_INPUTS = frozenset(
    {
        "ec218ffbb1dae2f3a4fca95e92cfe2cd38960c3219759a978f795636355784d8",
        "6cf7676c2216cc62a7e0ae0675b2a1849d242ffd2582ee93fa4e53d58c9ffe6e",
        "981f837ca8eb7f88848e8756e89321aee2a6b139e52b4c8828683afc712674e2",
        "ec5ff937c0e2b55e160fa45cb5639b8afd9b1d86c481c230dd3213608a16ac51",
    }
)
THRESHOLD = 0.5
MAX_DEVELOPMENT_ROWS = 4000
SEED = 42


def canonical_message(text: str) -> str:
    """Experimental feature input; never used by the production predictor."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _subset(corpus: Corpus, indices: list[int], role: str) -> Corpus:
    return Corpus(
        role,
        tuple(corpus.messages[index] for index in indices),
        tuple(corpus.labels[index] for index in indices),
        corpus.source_hashes,
    )


def _score(pipeline: Any, messages: list[str], *, canonical: bool) -> list[float]:
    values = [canonical_message(message) for message in messages] if canonical else messages
    probabilities = pipeline.predict_proba(messages_to_frame(values))
    return [float(row[list(pipeline.classes_).index("spam")]) for row in probabilities]


def study(corpus: Corpus, expected_sha256: str, *, folds: int = 3) -> dict[str, Any]:
    """Fit fixed comparison recipes on disjoint development folds only."""
    if (
        corpus.role not in {*PUBLIC_IDS, "synthetic_training"}
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or corpus.source_hashes != (expected_sha256,)
        or expected_sha256 in FROZEN_INPUTS
    ):
        raise ValueError("Development provenance or fingerprint refused.")
    if not 2 <= folds <= 5 or not 4 <= len(corpus.messages) <= MAX_DEVELOPMENT_ROWS:
        raise ValueError("Development row or fold budget exceeded.")
    if len(corpus.messages) != len(corpus.labels) or set(corpus.labels) != {"ham", "spam"}:
        raise ValueError("Both aligned classes are required.")
    keys = [_normalized_message_key(message) for message in corpus.messages]
    # Refuse rather than silently remove observations or resolve disagreements.
    if len(set(keys)) != len(keys):
        raise ValueError("Resolve normalized duplicates and label conflicts before the study.")
    groups = [make_group_key(message) for message in corpus.messages]
    splits = cv_splits(corpus.labels, groups, n_splits=folds, seed=SEED, require_group_isolation=True)
    if len(splits) != folds:
        raise ValueError("Requested fold count unavailable.")
    memberships = []
    prepared = []
    for train_idx, validation_idx in splits:
        train = _subset(corpus, train_idx.tolist(), "development_train")
        validation = _subset(corpus, validation_idx.tolist(), "development_validation")
        overlap = compare_corpora(train, validation)
        if (
            overlap["normalized"]["row_pairs"]
            or overlap["category_independent_template"]["row_pairs"]
            or overlap["near_duplicate_pairs_excluding_normalized"]
        ):
            raise ValueError("Cross-fold duplicate or near-duplicate candidates require private reconciliation.")
        membership = hashlib.sha256(
            json.dumps([expected_sha256, train_idx.tolist(), validation_idx.tolist()]).encode("ascii")
        ).hexdigest()
        memberships.append(
            {
                "sha256": membership,
                "train_rows": len(train.messages),
                "validation_rows": len(validation.messages),
                "validation_class_counts": {label: validation.labels.count(label) for label in ("ham", "spam")},
            }
        )
        prepared.append((train, validation))
    recipes = []
    for weight in (None, "balanced"):
        for canonical in (False, True):
            labels: list[str] = []
            original_scores: list[float] = []
            altered_scores: dict[str, list[float]] = {name: [] for name in FORMATS}
            for train, validation in prepared:
                pipeline = make_model(
                    LogisticRegression(C=1.0, class_weight=weight, solver="liblinear", max_iter=5000, random_state=SEED),
                    text_features="combined",
                )
                training = [canonical_message(message) for message in train.messages] if canonical else train.messages
                pipeline.fit(messages_to_frame(training), train.labels)
                original_scores.extend(_score(pipeline, list(validation.messages), canonical=canonical))
                labels.extend(validation.labels)
                for name, transform in FORMATS.items():
                    altered_scores[name].extend(
                        _score(pipeline, [transform(message) for message in validation.messages], canonical=canonical)
                    )
            metrics = binary_metrics(labels, original_scores, THRESHOLD)
            variants = {}
            for name, scores in altered_scores.items():
                altered = binary_metrics(labels, scores, THRESHOLD)
                variants[name] = {
                    "prediction_flips": sum(
                        (before >= THRESHOLD) != (after >= THRESHOLD)
                        for before, after in zip(original_scores, scores)
                    ),
                    "fp": altered["fp"],
                    "fn": altered["fn"],
                }
            recipes.append(
                {
                    "class_weight": weight or "none",
                    "canonical_input": canonical,
                    "metrics": metrics,
                    "calibration": calibration_metrics(labels, original_scores),
                    "formatting": variants,
                }
            )
    return {
        "schema_version": 1,
        "purpose": "development_comparison_only",
        "role": corpus.role,
        "source_sha256": expected_sha256,
        "seed": SEED,
        "threshold": THRESHOLD,
        "folds": memberships,
        "versions": {
            "python": platform.python_version(),
            "scikit-learn": importlib.metadata.version("scikit-learn"),
            "numpy": importlib.metadata.version("numpy"),
        },
        "recipes": recipes,
        "limitations": [
            "Out-of-fold development diagnostics are not independent field evidence or a release decision.",
            "No threshold optimization, calibration fitting, model selection, or model persistence occurs.",
            "Corpus custodians must independently verify approval, frozen-set separation, and representative sampling.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=[*PUBLIC_IDS, "synthetic_training"])
    parser.add_argument("--development", required=True, type=Path)
    parser.add_argument("--approved-sha256", required=True, help="Independently approved development snapshot digest.")
    parser.add_argument("--folds", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        if args.approved_sha256 in FROZEN_INPUTS:
            raise ValueError("Frozen input refused.")
        corpus = load_corpus(args.role, [args.development])
        report = study(corpus, args.approved_sha256, folds=args.folds)
    except (OSError, ValueError, csv.Error, RuntimeError):
        print("Development study refused: check provenance, class support, duplicates and fold separation.", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
