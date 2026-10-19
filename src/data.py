"""Loading, validation, deduplication, and leakage-aware splitting of SMS data.

Design goals
------------
* One code path for base data, supplements, and holdouts.
* Fail loudly and actionably on schema/label/empty/class problems instead of
  silently dropping rows.
* Deduplicate *before* splitting and split by template/campaign group so
  near-identical templates cannot leak across train/validation/test.
* Emit file hashes and split fingerprints (never raw message text) so a model
  artifact can be traced back to exactly the data that produced it.

Optional metadata columns accepted in any CSV:
``source``, ``category`` (or ``message_type``/``type``), ``language``,
``labeling_confidence``, ``group`` (or ``template_family``/``campaign``), and
``received_at`` (or ``message_date``/``timestamp``) for temporal holdouts.
Missing metadata is filled with ``"unknown"``; it is never invented.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold, train_test_split

from src.preprocess import MONEY_RE, PHONE_RE, URL_RE, normalize_taglish

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_DATA = RAW_DIR / "spam.csv"
DEFAULT_SUPPLEMENTS: tuple[Path, ...] = (
    RAW_DIR / "ph_supplement.csv",
    RAW_DIR / "ph_supplement_2.csv",
    RAW_DIR / "ph_supplement_3.csv",
)
DEFAULT_HOLDOUT = RAW_DIR / "ph_holdout.csv"

VALID_LABELS = ("ham", "spam")
LABEL_ALIASES = {
    "ham": "ham",
    "legit": "ham",
    "legitimate": "ham",
    "not spam": "ham",
    "non-spam": "ham",
    "0": "ham",
    "spam": "spam",
    "scam": "spam",
    "phishing": "spam",
    "1": "spam",
}

METADATA_COLUMNS = ("source", "category", "language", "labeling_confidence", "group", "received_at", "data_kind")
CANONICAL_COLUMNS = ("message", "label", *METADATA_COLUMNS, "source_file")
DEFAULT_VAL_SIZE = 0.15
DEFAULT_TEST_SIZE = 0.15
DEFAULT_SEED = 42
GROUP_KEY_VERSION = "1"
MIN_CLASS_COUNT = 2
IMBALANCE_WARN_RATIO = 20.0


class DatasetError(ValueError):
    """An actionable data-quality problem (safe to show to an operator)."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise DatasetError(
            f"Dataset file not found: {path}. "
            "Pass an existing CSV (label,message or Kaggle v1/v2 columns) or update the default path."
        )
    if path.is_dir():
        raise DatasetError(f"{path} is a directory; pass individual CSV files instead.")
    if path.stat().st_size == 0:
        raise DatasetError(f"{path} is empty (0 bytes). Provide a CSV with at least a header and rows.")
    try:
        try:
            return pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="latin-1", dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError as exc:
        raise DatasetError(f"{path} has no readable CSV header/rows: {exc}") from exc
    except pd.errors.ParserError as exc:
        raise DatasetError(f"{path} is not valid CSV: {exc}") from exc


def _column_lookup(df: pd.DataFrame, path: Path) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for column in df.columns:
        canonical = str(column).strip().lower().replace(" ", "_")
        if canonical in lookup:
            raise DatasetError(f"{path}: duplicate column {canonical!r} after normalization; rename one of them.")
        lookup[canonical] = column
    return lookup


def _resolve_message_and_label_columns(lookup: dict[str, str], path: Path) -> tuple[str, str]:
    if "label" in lookup and "message" in lookup:
        return "message", "label"
    if "label" in lookup and "text" in lookup:
        return "text", "label"
    if "v1" in lookup and "v2" in lookup:  # Kaggle SMS Spam Collection layout
        return "v2", "v1"
    if "class" in lookup and "message" in lookup:
        return "message", "class"
    if "target" in lookup and "message" in lookup:
        return "message", "target"
    raise DatasetError(
        f"{path}: could not find message/label columns. "
        f"Found columns {list(lookup)}; accepted layouts are label+message, label+text, or Kaggle v1(label)+v2(message)."
    )


def _resolve_metadata_columns(lookup: dict[str, str]) -> dict[str, str]:
    aliases = {
        "source": ("source", "data_source"),
        "data_kind": ("data_kind",),
        "category": ("category", "message_type", "type", "scam_type"),
        "language": ("language", "lang"),
        "labeling_confidence": ("labeling_confidence", "label_confidence", "confidence"),
        "group": ("group", "template_family", "campaign", "family"),
        "received_at": ("received_at", "message_date", "received_date", "timestamp", "date"),
    }
    resolved: dict[str, str] = {}
    for canonical, candidates in aliases.items():
        for candidate in candidates:
            if candidate in lookup:
                resolved[canonical] = lookup[candidate]
                break
    return resolved


def _normalize_labels(series: pd.Series, path: Path) -> pd.Series:
    raw = series.astype(str).str.replace("\ufeff", "", regex=False).str.strip().str.lower()
    raw = raw.str.replace(r"\s+", " ", regex=True)
    normalized = raw.map(LABEL_ALIASES)
    unknown = raw[normalized.isna()]
    if len(unknown):
        counts = unknown.value_counts().head(10).to_dict()
        raise DatasetError(
            f"{path}: unrecognized labels {counts}. "
            f"Allowed values: {sorted(set(LABEL_ALIASES))}; unknown rows must be fixed or removed."
        )
    return normalized.astype(str)


def make_group_key(message: str, *, category: str | None = None, source: str | None = None) -> str:
    """Derive a deterministic template-family key without storing the message.

    Entities (URLs, phones, amounts, digits) are masked before taking a short
    token prefix, so "Nag-claim ka ng ₱100,000 sa GMA..." and "Nag-claim ka ng
    ₱900,000 sa GMA..." share a group. Explicit ``category`` metadata is folded
    in when available; ``source`` is accepted for API symmetry but deliberately
    not folded in, so the same template found in two files is still recognised
    as one family (important for holdout-overlap reporting).
    """
    text = normalize_taglish(message)
    text = URL_RE.sub(" <url> ", text)
    text = MONEY_RE.sub(" <money> ", text)
    text = PHONE_RE.sub(" <phone> ", text)
    text = re.sub(r"\d+", " <num> ", text)
    text = re.sub(r"[^\w<>\s]", " ", text, flags=re.UNICODE).lower()
    tokens = text.split()
    signature = " ".join(tokens[:8]) or "<empty>"
    if category and category.strip().lower() not in {"", "unknown"}:
        return f"cat:{category.strip().lower()}|{signature}"
    _ = source  # intentionally not part of the family key
    return signature


@dataclass
class FileRecord:
    path: str
    role: str
    sha256: str
    rows_in: int
    rows_loaded: int
    duplicates_removed: int
    class_counts: dict[str, int] = field(default_factory=dict)
    metadata_columns: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "role": self.role,
            "sha256": self.sha256,
            "rows_in": self.rows_in,
            "rows_loaded": self.rows_loaded,
            "duplicates_removed": self.duplicates_removed,
            "class_counts": dict(self.class_counts),
            "metadata_columns": list(self.metadata_columns),
        }


@dataclass
class Dataset:
    frame: pd.DataFrame
    records: list[FileRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.frame)

    @property
    def messages(self) -> list[str]:
        return self.frame["message"].tolist()

    @property
    def labels(self) -> list[str]:
        return self.frame["label"].tolist()

    @property
    def groups(self) -> list[str]:
        return self.frame["group"].tolist()

    @property
    def class_counts(self) -> dict[str, int]:
        counts = self.frame["label"].value_counts().to_dict()
        return {label: int(counts.get(label, 0)) for label in VALID_LABELS}

    def summary(self) -> dict[str, Any]:
        imbalance = None
        if min(self.class_counts.values()) > 0:
            imbalance = round(max(self.class_counts.values()) / min(self.class_counts.values()), 3)
        return {
            "rows": len(self),
            "class_counts": self.class_counts,
            "class_imbalance_ratio": imbalance,
            "group_count": int(self.frame["group"].nunique()),
            "files": [record.as_dict() for record in self.records],
            "warnings": list(self.warnings),
        }


def _load_one(
    path: str | Path,
    *,
    role: str,
    require_both_classes: bool,
    strict: bool,
    min_class_count: int,
) -> Dataset:
    path = Path(path)
    df = _read_csv(path)
    if df.empty:
        raise DatasetError(f"{path}: CSV has columns but no data rows.")
    lookup = _column_lookup(df, path)
    message_column, label_column = _resolve_message_and_label_columns(lookup, path)
    metadata_columns = _resolve_metadata_columns(lookup)

    messages = df[message_column].astype(str).str.strip()
    labels = _normalize_labels(df[label_column], path)
    blank_mask = messages.eq("")
    if blank_mask.any():
        row_numbers = (np.flatnonzero(blank_mask.to_numpy()) + 2).tolist()[:10]
        if strict:
            raise DatasetError(
                f"{path}: {int(blank_mask.sum())} row(s) have a blank message (CSV data rows {row_numbers}). "
                "Remove or fix them; pass --lenient-data to drop them with a warning."
            )
        messages = messages[~blank_mask]
        labels = labels[~blank_mask]

    working = pd.DataFrame({"message": messages, "label": labels})
    working["source"] = (
        df[metadata_columns["source"]].astype(str).str.strip().replace("", "unknown")
        if "source" in metadata_columns
        else path.stem
    )
    working["category"] = (
        df[metadata_columns["category"]].astype(str).str.strip().replace("", "unknown")
        if "category" in metadata_columns
        else "unknown"
    )
    working["language"] = (
        df[metadata_columns["language"]].astype(str).str.strip().replace("", "unknown")
        if "language" in metadata_columns
        else "unknown"
    )
    working["labeling_confidence"] = (
        df[metadata_columns["labeling_confidence"]].astype(str).str.strip().replace("", "unknown")
        if "labeling_confidence" in metadata_columns
        else "unknown"
    )
    if "received_at" in metadata_columns:
        parsed_dates = pd.to_datetime(df[metadata_columns["received_at"]], errors="coerce", utc=True)
        working["received_at"] = parsed_dates.dt.strftime("%Y-%m-%dT%H:%M:%SZ").fillna("")
    else:
        working["received_at"] = ""
    working["data_kind"] = (
        df[metadata_columns["data_kind"]].astype(str).str.strip().str.lower().replace("", "unknown")
        if "data_kind" in metadata_columns
        else "unknown"
    )
    if not working["data_kind"].isin(["synthetic", "real", "unknown"]).all():
        raise DatasetError(f"{path}: data_kind must be synthetic, real, or unknown.")
    working["source_file"] = path.name
    if "group" in metadata_columns:
        working["_provided_group"] = df[metadata_columns["group"]].astype(str).str.strip().replace("", "unknown")
    else:
        working["_provided_group"] = "unknown"

    # Remove leading/trailing whitespace variants before duplicate detection.
    working["message"] = working["message"].str.strip()
    working = working[working["message"].ne("")].reset_index(drop=True)
    if working.empty:
        raise DatasetError(f"{path}: no usable rows after dropping blank messages.")

    conflicts = working.groupby("message")["label"].nunique()
    conflicting_messages = conflicts[conflicts > 1]
    if len(conflicting_messages):
        examples = [
            {
                "message": _redacted(message),
                "labels": sorted(working.loc[working["message"] == message, "label"].unique()),
            }
            for message in conflicting_messages.index[:5]
        ]
        raise DatasetError(
            f"{path}: {len(conflicting_messages)} message(s) have conflicting labels, e.g. {examples}. "
            "Resolve the labels before training; duplicate text cannot be both ham and spam."
        )

    duplicates = int(working.duplicated(subset="message", keep="first").sum())
    if duplicates:
        working = working.drop_duplicates(subset="message", keep="first").reset_index(drop=True)

    working["group"] = [
        provided
        if str(provided).strip().lower() not in {"", "unknown"}
        else make_group_key(row.message, category=row.category, source=row.source)
        for provided, row in zip(working["_provided_group"], working.itertuples(index=False))
    ]
    working = working.drop(columns=["_provided_group"])

    class_counts = {label: int((working["label"] == label).sum()) for label in VALID_LABELS}
    if require_both_classes and 0 in class_counts.values():
        raise DatasetError(
            f"{path}: training data must contain both ham and spam; found {class_counts}. "
            "Add labeled examples for the missing class (include legitimate OTPs/bank alerts as ham)."
        )
    if min_class_count > 0:
        for label, count in class_counts.items():
            if 0 < count < min_class_count:
                raise DatasetError(
                    f"{path}: class {label!r} has only {count} row(s); at least {min_class_count} are required "
                    "to build a stratified split."
                )

    warnings: list[str] = []
    if duplicates:
        warnings.append(
            f"{path}: removed {duplicates} exact duplicate message(s) before splitting "
            "(first occurrence kept; prevents a template from being double-counted)."
        )
    nonzero = [count for count in class_counts.values() if count > 0]
    if len(nonzero) == 2 and min(nonzero) > 0 and max(nonzero) / min(nonzero) > IMBALANCE_WARN_RATIO:
        warnings.append(
            f"{path}: imbalanced classes {class_counts} (ratio {max(nonzero) / min(nonzero):.1f}:1). "
            "Metrics for the minority class will be noisy; consider collecting more examples."
        )

    frame = working[list(CANONICAL_COLUMNS)].reset_index(drop=True)
    record = FileRecord(
        path=str(path),
        role=role,
        sha256=_sha256(path),
        rows_in=len(df),
        rows_loaded=len(frame),
        duplicates_removed=duplicates,
        class_counts=class_counts,
        metadata_columns=sorted(metadata_columns.values()),
    )
    return Dataset(frame=frame, records=[record], warnings=warnings)


def _redacted(message: str, limit: int = 60) -> str:
    text = str(message)
    return (text[:limit] + "…") if len(text) > limit else text


def load_dataset(
    path: str | Path,
    *,
    role: str = "data",
    require_both_classes: bool = True,
    strict: bool = True,
    min_class_count: int = MIN_CLASS_COUNT,
) -> Dataset:
    """Load and validate one CSV.

    Raises :class:`DatasetError` with an operator-actionable message for a
    missing/empty file, unknown schema, unknown labels, blank messages,
    conflicting duplicate labels, missing classes, or too-small classes.
    """
    return _load_one(
        path,
        role=role,
        require_both_classes=require_both_classes,
        strict=strict,
        min_class_count=min_class_count,
    )


def resolve_supplement_paths(
    specs: str | Path | Iterable[str | Path] | None,
    *,
    strict: bool,
) -> tuple[list[Path], list[str]]:
    """Resolve supplement CLI/API input into existing CSV paths.

    ``None`` disables supplements. ``"none"`` (case-insensitive, alone) also
    disables them. When ``strict`` is true (the operator explicitly named the
    files), a missing path is an error; otherwise (default supplement list)
    missing optional files are skipped with a warning.
    """
    if specs is None:
        return [], []
    if isinstance(specs, (str, Path)):
        values: list[str | Path] = [specs]
    else:
        values = list(specs)
    if values and all(isinstance(value, str) and value.strip().lower() == "none" for value in values):
        return [], []
    if any(isinstance(value, str) and value.strip().lower() == "none" for value in values):
        raise DatasetError(
            "'none' cannot be combined with supplement CSV paths; use either --supplement none or a list of files."
        )

    paths: list[Path] = []
    warnings: list[str] = []
    seen: set[Path] = set()
    for value in values:
        path = Path(value)
        if path in seen:
            continue
        seen.add(path)
        if not path.exists():
            if strict:
                raise DatasetError(
                    f"Supplement CSV not found: {path}. Pass an existing file, or omit --supplement to use the defaults, "
                    "or use --supplement none to train on the base dataset only."
                )
            warnings.append(f"Optional supplement not found and skipped: {path}")
            continue
        if path.is_dir():
            raise DatasetError(f"Supplement path is a directory, not a CSV: {path}")
        paths.append(path)
    return paths, warnings


def load_training_dataset(
    data_path: str | Path = DEFAULT_DATA,
    supplement_path: str | Path | Iterable[str | Path] | None = DEFAULT_SUPPLEMENTS,
    *,
    strict_data: bool = True,
    strict_supplement_paths: bool = False,
) -> Dataset:
    """Load the base CSV plus any supplements, then deduplicate globally.

    ``supplement_path`` may be ``None`` (disable), one path, or any iterable of
    paths. ``strict_supplement_paths`` is set when the operator explicitly named
    supplement files; missing explicit files then fail instead of being skipped.
    """
    if data_path is None:
        raise DatasetError("data_path is required; pass the base label,message CSV.")
    base = load_dataset(data_path, role="base", require_both_classes=True, strict=strict_data)
    supplement_paths, path_warnings = resolve_supplement_paths(supplement_path, strict=strict_supplement_paths)
    frames = [base.frame]
    records = list(base.records)
    warnings = [*base.warnings, *path_warnings]
    for path in supplement_paths:
        supplement = load_dataset(
            path,
            role="supplement",
            require_both_classes=False,
            strict=strict_data,
            min_class_count=0,
        )
        frames.append(supplement.frame)
        records.extend(supplement.records)
        warnings.extend(supplement.warnings)

    combined = pd.concat(frames, ignore_index=True)
    conflicts = combined.groupby("message")["label"].nunique()
    conflicting = conflicts[conflicts > 1]
    if len(conflicting):
        examples = [
            {
                "message": _redacted(message),
                "labels": sorted(combined.loc[combined["message"] == message, "label"].unique()),
            }
            for message in conflicting.index[:5]
        ]
        raise DatasetError(
            f"{len(conflicting)} message(s) appear in multiple sources with conflicting labels, e.g. {examples}. "
            "Fix the labels before training; identical text cannot be both ham and spam."
        )
    before = len(combined)
    combined = combined.drop_duplicates(subset="message", keep="first").reset_index(drop=True)
    cross_source_duplicates = before - len(combined)
    if cross_source_duplicates:
        warnings.append(f"Removed {cross_source_duplicates} duplicate message(s) across sources before splitting.")

    class_counts = {label: int((combined["label"] == label).sum()) for label in VALID_LABELS}
    for label, count in class_counts.items():
        if count < MIN_CLASS_COUNT:
            raise DatasetError(
                f"Combined training data needs at least {MIN_CLASS_COUNT} {label} examples; found {count}. "
                "Check the supplement files and labels."
            )
    dataset = Dataset(frame=combined[list(CANONICAL_COLUMNS)], records=records, warnings=warnings)
    return dataset


def load_holdout(path: str | Path | None = DEFAULT_HOLDOUT, *, strict: bool = True) -> Dataset | None:
    """Load the separate evaluation holdout (never used for training)."""
    if path is None:
        return None
    if isinstance(path, str) and path.strip().lower() == "none":
        return None
    return load_dataset(path, role="holdout", require_both_classes=True, strict=strict)


def group_leakage_report(training: Dataset, holdout: Dataset) -> dict[str, Any]:
    """Compare training and holdout at message/template-family level.

    Exact duplicate messages between training and the holdout are a hard
    leakage error. Template-family overlap is reported (synthetic Philippine
    templates deliberately share families) and must be disclosed wherever
    holdout metrics are shown.
    """
    train_messages = set(training.messages)
    holdout_messages = set(holdout.messages)
    exact_overlap = sorted(train_messages & holdout_messages)
    if exact_overlap:
        raise DatasetError(
            f"Holdout contains {len(exact_overlap)} message(s) that are also in training data; "
            "this leaks the answer. Remove them from the holdout or training files. "
            f"Example: {_redacted(exact_overlap[0])}"
        )
    train_groups = set(training.groups)
    holdout_groups = set(holdout.groups)
    overlapping_groups = sorted(train_groups & holdout_groups)
    return {
        "exact_message_overlap": 0,
        "template_family_overlap": len(overlapping_groups),
        "holdout_template_family_count": len(holdout_groups),
        "template_family_overlap_ratio": (
            round(len(overlapping_groups) / len(holdout_groups), 4) if holdout_groups else 0.0
        ),
        "template_family_overlap_examples": overlapping_groups[:10],
    }


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
    candidates = [value for value in (preferred, 10, 8, 7, 6, 5, 4, 3) if value >= 3]
    seen: set[int] = set()
    for n_splits in candidates:
        if n_splits in seen:
            continue
        seen.add(n_splits)
        if n_splits > len(unique_groups):
            continue
        fold_splits = list(
            StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed).split(
                np.zeros(len(labels)), labels, groups=groups
            )
        )
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


def dataset_manifest(dataset: Dataset, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """JSON-safe provenance manifest (no message text)."""
    manifest = dataset.summary()
    if extra:
        manifest.update(extra)
    return manifest


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)
