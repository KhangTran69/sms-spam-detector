"""Create a private chronological campaign holdout from approved consented data."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.consented_data import _read_intake_csv, normalize_intake_columns, validate_batch
from src.dataset_loading import load_dataset
from src.dataset_schema import ROOT, DatasetError, _normalized_message_key
from src.dataset_splits import grouped_splits
from src.privacy.storage import ensure_private_directory


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_metadata() -> dict[str, Any]:
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
    for package in ("pandas", "scikit-learn"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unknown"
    return {
        "source_revision": revision,
        "source_tree_dirty": dirty,
        "python_version": platform.python_version(),
        "libraries": versions,
    }


def _private_output_directory(path: str | Path) -> Path:
    directory = Path(path).expanduser().resolve()
    repository = ROOT.resolve()
    private_root = (repository / "data" / "donations").resolve()
    if (
        (directory == repository or repository in directory.parents)
        and directory != private_root
        and private_root not in directory.parents
    ):
        raise DatasetError(
            "Consented split files must be written outside the repository or under ignored data/donations/."
        )
    try:
        return ensure_private_directory(directory)
    except (OSError, ValueError) as exc:
        raise DatasetError(f"Private split output directory is not safe ({type(exc).__name__}).") from None


def _write_private_outputs(outputs: list[tuple[Path, bytes]]) -> None:
    if any(path.exists() for path, _ in outputs):
        raise DatasetError("A consented split output already exists; refusing to overwrite private data.")
    created: list[Path] = []
    try:
        for path, content in outputs:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
    except OSError as exc:
        for path in created:
            path.unlink(missing_ok=True)
        raise DatasetError(f"Could not write protected split output ({type(exc).__name__}).") from None


def _membership_hash(source_sha256: str, name: str, indices: list[int]) -> str:
    payload = f"{source_sha256}\n{name}\n" + "\n".join(str(index) for index in sorted(indices))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _file_membership_hash(dataset_sha256: str, row_count: int) -> str:
    members = "\n".join(f"{dataset_sha256}:{index}" for index in range(row_count))
    return hashlib.sha256(members.encode("ascii")).hexdigest()


def _label_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts = frame["label"].value_counts().to_dict()
    return {label: int(counts.get(label, 0)) for label in ("ham", "spam")}


def _coverage_counts(frame: pd.DataFrame) -> dict[str, dict[str, int]]:
    return {
        dimension: {
            str(value): int(count)
            for value, count in frame[dimension]
            .fillna("unknown")
            .astype(str)
            .replace("", "unknown")
            .value_counts()
            .items()
        }
        for dimension in ("language", "category")
    }


def split_consented_dataset(
    input_path: str | Path,
    *,
    development_output_dir: str | Path,
    evaluation_output_dir: str | Path,
    validation_size: float = 0.15,
    test_size: float = 0.15,
    seed: int = 42,
) -> dict[str, Any]:
    """Validate consent and write disjoint development and sealed test CSVs.

    ``src.train`` makes its internal train/validation split from the development
    output. The separate chronological test output is never passed to training.
    """
    source_path = Path(input_path).expanduser()
    try:
        source_bytes, raw_frame = _read_intake_csv(source_path)
        source_sha256 = _sha256(source_bytes)
        training_report = validate_batch(raw_frame, purpose="training")
        evaluation_report = validate_batch(raw_frame, purpose="evaluation")
    except (OSError, ValueError) as exc:
        raise DatasetError(f"Consented input preflight failed ({type(exc).__name__}).") from None
    findings = sorted({item.rule for item in (*training_report.findings, *evaluation_report.findings)})
    if findings:
        raise DatasetError(f"Consented split rejected; fix these row/rule findings first: {json.dumps(findings)}")

    dataset = load_dataset(source_path, role="holdout", require_both_classes=True, min_class_count=0)
    if not dataset.records or dataset.records[0].sha256 != source_sha256:
        raise DatasetError("Consented input changed after preflight; rerun with a stable private file.")
    if set(dataset.frame["data_kind"].astype(str)) != {"consented"}:
        raise DatasetError("Only a single-provenance consented batch can be split for this workflow.")
    split = grouped_splits(
        dataset,
        val_size=validation_size,
        test_size=test_size,
        seed=seed,
        split_by="time",
        min_class_per_split=1,
    )
    if split.method != "chronological_group_holdout" or split.as_dict(dataset.groups).get("group_leakage") != 0:
        raise DatasetError("Could not establish a chronological campaign-separated holdout; no files were written.")

    normalized_frame = normalize_intake_columns(raw_frame)
    source_indices = {
        _normalized_message_key(str(message).strip()): index
        for index, message in enumerate(normalized_frame["message"])
    }
    if len(source_indices) != len(normalized_frame):
        raise DatasetError("Duplicate messages must be reconciled before splitting; no files were written.")
    development_indices = sorted(split.train_idx + split.val_idx)
    evaluation_indices = sorted(split.test_idx)
    if len(development_indices) + len(evaluation_indices) != len(normalized_frame):
        raise DatasetError("Split membership did not cover every validated input row; no files were written.")
    development_source_indices = [
        source_indices[_normalized_message_key(dataset.messages[index])] for index in development_indices
    ]
    evaluation_source_indices = [
        source_indices[_normalized_message_key(dataset.messages[index])] for index in evaluation_indices
    ]

    development_dir = _private_output_directory(development_output_dir)
    evaluation_dir = _private_output_directory(evaluation_output_dir)
    if (
        development_dir == evaluation_dir
        or development_dir in evaluation_dir.parents
        or evaluation_dir in development_dir.parents
    ):
        raise DatasetError("Development and sealed evaluation outputs must use separate private directories.")

    suffix = source_sha256[:12]
    development_name = f"consented-development-{suffix}.csv"
    evaluation_name = f"consented-evaluation-{suffix}.csv"
    manifest_name = f"consented-split-{suffix}.json"
    development_frame = normalized_frame.iloc[development_source_indices].reset_index(drop=True)
    evaluation_frame = normalized_frame.iloc[evaluation_source_indices].reset_index(drop=True)
    development_bytes = development_frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    evaluation_bytes = evaluation_frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    development_sha256 = _sha256(development_bytes)
    evaluation_sha256 = _sha256(evaluation_bytes)
    split_manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_dataset_sha256": source_sha256,
        "source_rows": len(dataset),
        "development": {
            "filename": development_name,
            "sha256": development_sha256,
            "membership_sha256": _file_membership_hash(development_sha256, len(development_frame)),
            "source_membership_sha256": _membership_hash(source_sha256, "development", development_indices),
            "rows": len(development_indices),
            "label_counts": _label_counts(development_frame),
            "coverage_counts": _coverage_counts(development_frame),
            "campaign_groups": int(dataset.frame.iloc[development_indices]["group"].nunique()),
        },
        "sealed_evaluation": {
            "filename": evaluation_name,
            "sha256": evaluation_sha256,
            "membership_sha256": _file_membership_hash(evaluation_sha256, len(evaluation_frame)),
            "source_membership_sha256": _membership_hash(source_sha256, "sealed_evaluation", evaluation_indices),
            "rows": len(evaluation_indices),
            "label_counts": _label_counts(evaluation_frame),
            "coverage_counts": _coverage_counts(evaluation_frame),
            "campaign_groups": int(dataset.frame.iloc[evaluation_indices]["group"].nunique()),
            "sealed": True,
        },
        "split": {
            "method": split.method,
            "seed": split.seed,
            "validation_size": validation_size,
            "test_size": test_size,
            "row_membership_sha256": split.group_fingerprint(dataset.groups),
            "group_leakage": 0,
            "cross_split_duplicate_preflight": "passed",
            "temporal_ordering": "chronological_campaign_holdout",
        },
        "run": _source_metadata(),
        "message_text_included": False,
        "limitations": [
            "This split manifest records local file hashes and aggregate membership only; it does not prove that the test data remained unseen by an operator.",
            "Protect the sealed evaluation directory and plan with a separate data custodian. Do not use the sealed evaluation file in training, threshold selection, feature selection, or calibration.",
        ],
    }
    manifest_bytes = (json.dumps(split_manifest, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    outputs = [
        (development_dir / development_name, development_bytes),
        (evaluation_dir / evaluation_name, evaluation_bytes),
        (development_dir / manifest_name, manifest_bytes),
    ]
    _write_private_outputs(outputs)
    return {
        "status": "split",
        "development": split_manifest["development"],
        "sealed_evaluation": split_manifest["sealed_evaluation"],
        "manifest": manifest_name,
        "split_method": split.method,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create private chronological development and sealed evaluation files."
    )
    parser.add_argument(
        "--input", required=True, help="Private consented CSV that passes both training and evaluation preflight."
    )
    parser.add_argument(
        "--development-output-dir",
        required=True,
        help="Owner-only directory for training data and the aggregate manifest.",
    )
    parser.add_argument(
        "--evaluation-output-dir",
        required=True,
        help="Separate owner-only directory controlled by the test-set custodian.",
    )
    parser.add_argument("--validation-size", type=float, default=0.15)
    parser.add_argument("--test-size", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    try:
        result = split_consented_dataset(
            args.input,
            development_output_dir=args.development_output_dir,
            evaluation_output_dir=args.evaluation_output_dir,
            validation_size=args.validation_size,
            test_size=args.test_size,
            seed=args.seed,
        )
    except (DatasetError, ValueError) as exc:
        print(f"consented split blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
