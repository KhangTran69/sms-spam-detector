"""Deterministic group-aware, temporal, and random train/validation/test splits."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold, train_test_split

from src.dataset_loading import (  # noqa: F401
    Dataset,
    FileRecord,
    _is_nan,
    _load_one,
    dataset_manifest,
    group_leakage_report,
    load_dataset,
    load_holdout,
    load_training_dataset,
    resolve_supplement_paths,
)
from src.dataset_schema import (  # noqa: F401
    CANONICAL_COLUMNS,
    DEFAULT_DATA,
    DEFAULT_HOLDOUT,
    DEFAULT_SEED,
    DEFAULT_SUPPLEMENTS,
    DEFAULT_TEST_SIZE,
    DEFAULT_VAL_SIZE,
    GROUP_KEY_VERSION,
    IMBALANCE_WARN_RATIO,
    LABEL_ALIASES,
    METADATA_COLUMNS,
    MIN_CLASS_COUNT,
    RAW_DIR,
    ROOT,
    VALID_LABELS,
    DatasetError,
    _column_lookup,
    _normalize_labels,
    _normalized_message_key,
    _read_csv,
    _resolve_message_and_label_columns,
    _resolve_metadata_columns,
    _sha256,
    make_group_key,
)


@dataclass
class Split:
    train_idx: list[int]
    val_idx: list[int]
    test_idx: list[int]
    method: str
    seed: int
    requested_val_size: float
    requested_test_size: float
    warnings: list[str] = field(default_factory=list)

    @property
    def grouped(self) -> bool:
        return self.method in {"stratified_group_kfold", "chronological_group_holdout"}

    @property
    def splits(self) -> dict[str, list[int]]:
        return {"train": self.train_idx, "val": self.val_idx, "test": self.test_idx}

    def sizes(self) -> dict[str, int]:
        return {name: len(indices) for name, indices in self.splits.items()}

    def group_fingerprint(self, groups: Sequence[str]) -> str:
        # Fingerprint split membership by row positions, never by donor,
        # campaign, or template identifiers. Source hashes bind the underlying
        # data version; this fingerprint records only which rows went where.
        _ = groups
        payload = {name: sorted(indices) for name, indices in self.splits.items()}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def legacy_group_fingerprint(self, groups: Sequence[str]) -> str:
        """Reproduce the pre-privacy fingerprint for old artifact comparison."""
        payload = {name: sorted({groups[index] for index in indices}) for name, indices in self.splits.items()}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def as_dict(self, groups: Sequence[str] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "method": self.method,
            "grouped": self.grouped,
            "seed": self.seed,
            "requested_val_size": self.requested_val_size,
            "requested_test_size": self.requested_test_size,
            "sizes": self.sizes(),
            "warnings": list(self.warnings),
        }
        if groups is not None:
            payload["group_fingerprint"] = self.group_fingerprint(groups)
            payload["group_fingerprint_version"] = "row-membership-v1"
            payload["group_sizes"] = {
                name: len({groups[index] for index in indices}) for name, indices in self.splits.items()
            }
            payload["group_leakage"] = _group_leakage(self.splits, groups)
        return payload


def _group_leakage(splits: dict[str, list[int]], groups: Sequence[str]) -> int:
    group_sets = {name: {groups[index] for index in indices} for name, indices in splits.items()}
    total = 0
    names = list(group_sets)
    for left in range(len(names)):
        for right in range(left + 1, len(names)):
            total += len(group_sets[names[left]] & group_sets[names[right]])
    return total


def _class_present(indices: Sequence[int], labels: Sequence[str], *, minimum: int = 1) -> bool:
    counts = {label: 0 for label in VALID_LABELS}
    for index in indices:
        counts[labels[index]] += 1
    return all(count >= minimum for count in counts.values())


def _stratified_random_split(labels: Sequence[str], val_size: float, test_size: float, seed: int) -> Split:
    indices = list(range(len(labels)))
    train_idx, rest_idx = train_test_split(
        indices,
        test_size=val_size + test_size,
        random_state=seed,
        stratify=labels,
    )
    rest_labels = [labels[index] for index in rest_idx]
    val_idx, test_idx = train_test_split(
        rest_idx,
        test_size=test_size / (val_size + test_size),
        random_state=seed,
        stratify=rest_labels,
    )
    return Split(
        train_idx=sorted(train_idx),
        val_idx=sorted(val_idx),
        test_idx=sorted(test_idx),
        method="stratified_random",
        seed=seed,
        requested_val_size=val_size,
        requested_test_size=test_size,
        warnings=["Group-aware splitting was not used; related/templated examples may cross splits."],
    )


def _temporal_group_split(
    dataset: Dataset,
    *,
    val_size: float,
    test_size: float,
    seed: int,
    min_class_per_split: int,
) -> Split:
    """Hold out the newest campaign groups for validation and final testing.

    A campaign/template group is indivisible. Its latest message timestamp
    determines its chronological position so repeated campaigns cannot cross
    split boundaries. This is useful for future real data; synthetic rows with
    missing dates must use the ordinary group split.
    """
    dates = pd.to_datetime(dataset.frame["received_at"], errors="coerce", utc=True)
    if dates.isna().any():
        missing = int(dates.isna().sum())
        raise DatasetError(
            f"Time-based splitting needs a valid received_at/date/timestamp for every row; {missing} row(s) are missing."
        )
    frame = dataset.frame.copy()
    frame["_parsed_date"] = dates
    grouped = (
        frame.groupby("group", sort=False)
        .agg(latest=("_parsed_date", "max"), count=("label", "size"))
        .sort_values(["latest"], kind="stable")
    )
    target_test = max(1, round(len(frame) * test_size))
    target_val = max(1, round(len(frame) * val_size))
    test_groups: set[str] = set()
    val_groups: set[str] = set()
    count = 0
    for group, row in grouped.iloc[::-1].iterrows():
        if count >= target_test:
            break
        test_groups.add(str(group))
        count += int(row["count"])
    count = 0
    remaining = grouped.loc[~grouped.index.astype(str).isin(test_groups)]
    for group, row in remaining.iloc[::-1].iterrows():
        if count >= target_val:
            break
        val_groups.add(str(group))
        count += int(row["count"])
    train_groups = set(grouped.index.astype(str)) - test_groups - val_groups
    groups = dataset.groups
    splits = {
        "train": [i for i, group in enumerate(groups) if group in train_groups],
        "val": [i for i, group in enumerate(groups) if group in val_groups],
        "test": [i for i, group in enumerate(groups) if group in test_groups],
    }
    if not all(_class_present(indices, dataset.labels, minimum=min_class_per_split) for indices in splits.values()):
        raise DatasetError(
            "Chronological campaign split could not put both labels in train, validation, and test. "
            "Collect more dated campaign groups or use --split-by group; do not silently fall back to a random split."
        )
    return Split(
        train_idx=splits["train"],
        val_idx=splits["val"],
        test_idx=splits["test"],
        method="chronological_group_holdout",
        seed=seed,
        requested_val_size=val_size,
        requested_test_size=test_size,
        warnings=["Groups are assigned by their newest timestamp; temporal holdout requires real, trustworthy dates."],
    )


def grouped_splits(
    dataset: Dataset,
    *,
    val_size: float = DEFAULT_VAL_SIZE,
    test_size: float = DEFAULT_TEST_SIZE,
    seed: int = DEFAULT_SEED,
    split_by: str = "group",
    min_class_per_split: int = 1,
) -> Split:
    """Create deterministic train/validation/test splits.

    Default: ``StratifiedGroupKFold`` with group=template family, so no group
    crosses a split boundary. Validation is used only for threshold tuning and
    test only for the final reported metric. Tiny datasets where a class cannot
    be represented fall back to a stratified random split *with a warning*.
    """
    if not 0.0 < val_size < 1.0 or not 0.0 < test_size < 1.0:
        raise DatasetError("val_size and test_size must each be within (0, 1).")
    if val_size + test_size >= 1.0:
        raise DatasetError("val_size + test_size must be < 1.0.")
    labels = dataset.labels
    groups = dataset.groups
    if len(labels) < 6:
        raise DatasetError(f"Need at least 6 messages to split; found {len(labels)}.")
    if split_by == "random":
        split = _stratified_random_split(labels, val_size, test_size, seed)
        split.warnings.append("Requested random split; use split_by='group' to prevent template leakage.")
        return split
    if split_by == "time":
        return _temporal_group_split(
            dataset,
            val_size=val_size,
            test_size=test_size,
            seed=seed,
            min_class_per_split=min_class_per_split,
        )
    if split_by != "group":
        raise DatasetError("split_by must be 'group', 'time', or 'random'.")

    unique_groups = set(groups)
    if len(unique_groups) < 3:
        raise DatasetError(
            f"Only {len(unique_groups)} template group(s) found; group-aware splitting needs at least 3. "
            "Add a 'group'/'template_family' column or use --split-by random for a clearly-labelled fallback."
        )
    preferred = int(round(1.0 / min(val_size, test_size)))
    candidates = [value for value in (preferred, 10, 8, 7, 6, 5, 4, 3) if 3 <= value <= len(unique_groups)]
    seen: set[int] = set()
    for n_splits in candidates:
        if n_splits in seen:
            continue
        seen.add(n_splits)
        try:
            fold_splits = list(
                StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed).split(
                    np.zeros(len(labels)), labels, groups=groups
                )
            )
        except ValueError:
            # sklearn cannot stratify when a class has fewer members than
            # folds; try fewer folds and ultimately emit the documented
            # labelled random-split fallback.
            continue
        if len(fold_splits) < 3:
            continue
        val_idx = sorted(int(index) for index in fold_splits[0][1])
        test_idx = sorted(int(index) for index in fold_splits[1][1])
        train_idx = sorted(int(index) for _, held_out in fold_splits[2:] for index in held_out)
        if not (
            _class_present(train_idx, labels, minimum=min_class_per_split)
            and _class_present(val_idx, labels, minimum=min_class_per_split)
            and _class_present(test_idx, labels, minimum=min_class_per_split)
        ):
            continue
        split = Split(
            train_idx=train_idx,
            val_idx=val_idx,
            test_idx=test_idx,
            method="stratified_group_kfold",
            seed=seed,
            requested_val_size=val_size,
            requested_test_size=test_size,
        )
        leakage = _group_leakage(split.splits, groups)
        if leakage:  # pragma: no cover - SKFold guarantees disjoint groups
            raise DatasetError(f"Internal error: {leakage} groups leaked across splits.")
        return split

    fallback = _stratified_random_split(labels, val_size, test_size, seed)
    fallback.warnings.append(
        "Group-aware splitting could not represent both classes in every split; fell back to a "
        "stratified random split. Related examples may cross splits — treat metrics as optimistic."
    )
    return fallback


def split_dataset(dataset: Dataset, split: Split) -> tuple[Dataset, Dataset, Dataset]:
    """Slice a Dataset into train/validation/test Dataset objects."""
    frames = {
        "train": dataset.frame.iloc[split.train_idx].reset_index(drop=True),
        "val": dataset.frame.iloc[split.val_idx].reset_index(drop=True),
        "test": dataset.frame.iloc[split.test_idx].reset_index(drop=True),
    }
    return (
        Dataset(frame=frames["train"], records=dataset.records, warnings=dataset.warnings),
        Dataset(frame=frames["val"], records=dataset.records, warnings=dataset.warnings),
        Dataset(frame=frames["test"], records=dataset.records, warnings=dataset.warnings),
    )
