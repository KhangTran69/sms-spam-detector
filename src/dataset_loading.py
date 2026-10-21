"""Load, validate, and describe labeled SMS CSV files."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.dataset_schema import (  # noqa: F401
    CANONICAL_COLUMNS,
    DEFAULT_DATA,
    DEFAULT_HOLDOUT,
    DEFAULT_SEED,
    DEFAULT_SUPPLEMENTS,
    DEFAULT_TEST_SIZE,
    DEFAULT_VAL_SIZE,
    EMAIL_RE,
    GROUP_KEY_VERSION,
    IMBALANCE_WARN_RATIO,
    LABEL_ALIASES,
    METADATA_COLUMNS,
    METADATA_TOKEN_RE,
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
from src.preprocess import PHONE_RE, URL_RE


def _source_label(role: str) -> str:
    return {"base": "base CSV", "supplement": "supplement CSV", "holdout": "holdout CSV"}.get(role, "dataset CSV")


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
    provenance: dict[str, str] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)
    language_counts: dict[str, int] = field(default_factory=dict)
    data_kind_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            # Do not leak a private workspace path into manifests or artifacts.
            "path": f"{self.role}:{self.sha256[:12]}",
            "role": self.role,
            "sha256": self.sha256,
            "rows_in": self.rows_in,
            "rows_loaded": self.rows_loaded,
            "duplicates_removed": self.duplicates_removed,
            "class_counts": dict(self.class_counts),
            "metadata_columns": list(self.metadata_columns),
            "provenance": dict(self.provenance),
            "category_counts": dict(self.category_counts),
            "language_counts": dict(self.language_counts),
            "data_kind_counts": dict(self.data_kind_counts),
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
            "data_kind_counts": self._counts("data_kind"),
            "language_counts": self._counts("language"),
            "category_counts": self._counts("category"),
            "files": [record.as_dict() for record in self.records],
            "warnings": list(self.warnings),
        }

    def _counts(self, column: str) -> dict[str, int]:
        counts = self.frame[column].fillna("unknown").astype(str).replace("", "unknown").value_counts()
        return {str(key): int(value) for key, value in counts.items()}


def _load_one(
    path: str | Path,
    *,
    role: str,
    require_both_classes: bool,
    strict: bool,
    min_class_count: int,
) -> Dataset:
    path = Path(path)
    source_label = _source_label(role)
    df = _read_csv(path)
    try:
        source_hash = _sha256(path)
    except OSError:
        raise DatasetError(f"{source_label} cannot be hashed; keep the input available during preflight.") from None
    if df.empty:
        raise DatasetError(f"{source_label} has columns but no data rows.")
    lookup = _column_lookup(df, path)
    message_column, label_column = _resolve_message_and_label_columns(lookup, path)
    metadata_columns = _resolve_metadata_columns(lookup)

    messages = df[message_column].astype(str).str.strip()
    labels = _normalize_labels(df[label_column], source_label=source_label)
    blank_mask = messages.eq("")
    if blank_mask.any():
        row_numbers = (np.flatnonzero(blank_mask.to_numpy()) + 2).tolist()[:10]
        if strict:
            raise DatasetError(
                f"{source_label}: {int(blank_mask.sum())} row(s) have a blank message (CSV data rows {row_numbers}). "
                "Remove or fix them; pass --lenient-data to drop them with a warning."
            )
        messages = messages[~blank_mask]
        labels = labels[~blank_mask]

    working = pd.DataFrame({"message": messages, "label": labels})
    working["source"] = (
        df[metadata_columns["source"]].astype(str).str.strip().replace("", "unknown")
        if "source" in metadata_columns
        else "unknown"
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
    if "data_kind" in metadata_columns:
        working["data_kind"] = working["data_kind"].replace({"real": "consented"})
    if not working["data_kind"].isin(["synthetic", "public", "consented", "real", "unknown"]).all():
        raise DatasetError(f"{source_label}: data_kind must be synthetic, public, consented, real, or unknown.")
    consented_mask = working["data_kind"].eq("consented")
    if consented_mask.any():
        from src.consented_data import validate_batch

        consented_rows = df.loc[consented_mask].reset_index(drop=True).copy()
        consented_rows["data_kind"] = "consented"
        try:
            consent_report = validate_batch(
                consented_rows,
                purpose="evaluation" if role == "holdout" else "training",
            )
        except ValueError:
            raise DatasetError(
                f"{source_label}: consented rows must use the approved consented intake schema."
            ) from None
        if not consent_report.valid:
            rules = sorted({finding.rule for finding in consent_report.findings})
            raise DatasetError(
                f"{source_label}: consented rows failed consent/privacy checks; correct these rule codes: {rules}."
            )
    for column in ("source", "category", "language"):
        invalid = ~working[column].astype(str).str.fullmatch(METADATA_TOKEN_RE)
        if invalid.any():
            rows = (np.flatnonzero(invalid.to_numpy()) + 2).tolist()[:10]
            raise DatasetError(
                f"{source_label}: {column} metadata must use short category codes; invalid CSV data rows {rows}."
            )
    working["source_file"] = f"{role}:{source_hash[:12]}"
    if "group" in metadata_columns:
        working["_provided_group"] = df[metadata_columns["group"]].astype(str).str.strip().replace("", "unknown")
    else:
        working["_provided_group"] = "unknown"
    # Remove leading/trailing whitespace variants before duplicate detection.
    working["message"] = working["message"].str.strip()
    working = working[working["message"].ne("")].reset_index(drop=True)
    if working.empty:
        raise DatasetError(f"{source_label}: no usable rows after dropping blank messages.")

    working["_message_key"] = working["message"].map(_normalized_message_key)
    conflicts = working.groupby("_message_key")["label"].nunique()
    conflicting_messages = conflicts[conflicts > 1]
    if len(conflicting_messages):
        raise DatasetError(
            f"{source_label}: {len(conflicting_messages)} message(s) have conflicting labels. "
            "Resolve the labels before training; duplicate text cannot be both ham and spam."
        )

    exact_duplicates = int(working.duplicated(subset="message", keep="first").sum())
    duplicates = int(working.duplicated(subset="_message_key", keep="first").sum())
    if duplicates:
        working = working.drop_duplicates(subset="_message_key", keep="first").reset_index(drop=True)
    working = working.drop(columns=["_message_key"])

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
            f"{source_label}: training data must contain both ham and spam; found {class_counts}. "
            "Add labeled examples for the missing class (include legitimate OTPs/bank alerts as ham)."
        )
    if min_class_count > 0:
        for label, count in class_counts.items():
            if 0 < count < min_class_count:
                raise DatasetError(
                    f"{source_label}: class {label!r} has only {count} row(s); at least {min_class_count} are required "
                    "to build a stratified split."
                )

    warnings: list[str] = []
    if duplicates:
        warnings.append(
            f"{source_label}: removed {duplicates} exact or normalized duplicate message(s) before splitting "
            f"({exact_duplicates} exact; Unicode NFKC, case-folding, and whitespace normalization; first occurrence kept)."
        )
    nonzero = [count for count in class_counts.values() if count > 0]
    if len(nonzero) == 2 and min(nonzero) > 0 and max(nonzero) / min(nonzero) > IMBALANCE_WARN_RATIO:
        warnings.append(
            f"{source_label}: imbalanced classes {class_counts} (ratio {max(nonzero) / min(nonzero):.1f}:1). "
            "Metrics for the minority class will be noisy; consider collecting more examples."
        )

    frame = working[list(CANONICAL_COLUMNS)].reset_index(drop=True)
    provenance: dict[str, str] = {}
    for field_name in ("dataset_id", "dataset_version", "license", "collection_period"):
        provenance_column = metadata_columns.get(field_name)
        values = set(df[provenance_column].astype(str).str.strip()) - {"", "unknown"} if provenance_column else set()
        if len(values) > 1:
            raise DatasetError(f"{source_label}: {field_name} must be consistent across rows in one source file.")
        value = next(iter(values), "unknown")
        if value != "unknown" and (EMAIL_RE.search(value) or PHONE_RE.search(value) or URL_RE.search(value)):
            raise DatasetError(f"{source_label}: {field_name} metadata must not contain contact details or URLs.")
        provenance[field_name] = value

    record = FileRecord(
        path=str(path),
        role=role,
        sha256=source_hash,
        rows_in=len(df),
        rows_loaded=len(frame),
        duplicates_removed=duplicates,
        class_counts=class_counts,
        metadata_columns=sorted(metadata_columns),
        provenance=provenance,
        category_counts={str(key): int(value) for key, value in frame["category"].value_counts().items()},
        language_counts={str(key): int(value) for key, value in frame["language"].value_counts().items()},
        data_kind_counts={str(key): int(value) for key, value in frame["data_kind"].value_counts().items()},
    )
    return Dataset(frame=frame, records=[record], warnings=warnings)


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
                    "Supplement CSV not found (private path omitted). Pass an existing file, or omit --supplement "
                    "to use defaults, or use --supplement none to train on base data only."
                )
            warnings.append("Optional supplement not found; skipped (private path omitted).")
            continue
        if path.is_dir():
            raise DatasetError("Supplement path is a directory, not a CSV.")
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
    combined["_message_key"] = combined["message"].map(_normalized_message_key)
    conflicts = combined.groupby("_message_key")["label"].nunique()
    conflicting = conflicts[conflicts > 1]
    if len(conflicting):
        raise DatasetError(
            f"{len(conflicting)} message(s) appear in multiple sources with conflicting labels. "
            "Fix the labels before training; identical text cannot be both ham and spam."
        )
    before = len(combined)
    combined = (
        combined.drop_duplicates(subset="_message_key", keep="first")
        .drop(columns="_message_key")
        .reset_index(drop=True)
    )
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

    Exact or normalized duplicate messages between training and the holdout
    are a hard leakage error. Template-family overlap is reported (synthetic Philippine
    templates deliberately share families) and must be disclosed wherever
    holdout metrics are shown.
    """
    train_messages = set(training.messages)
    holdout_messages = set(holdout.messages)
    exact_overlap_count = len(train_messages & holdout_messages)
    normalized_train = {_normalized_message_key(message) for message in train_messages}
    normalized_holdout = {_normalized_message_key(message) for message in holdout_messages}
    normalized_overlap = normalized_train & normalized_holdout
    if normalized_overlap:
        raise DatasetError(
            f"Holdout contains {len(normalized_overlap)} exact or normalized message duplicate(s) from training data; "
            "this leaks the answer. Remove overlapping rows from the holdout or training files."
        )
    train_groups = set(training.groups)
    holdout_groups = set(holdout.groups)
    overlapping_groups = sorted(train_groups & holdout_groups)
    return {
        "exact_message_overlap": exact_overlap_count,
        "normalized_message_overlap": 0,
        "template_family_overlap": len(overlapping_groups),
        "holdout_template_family_count": len(holdout_groups),
        "template_family_overlap_ratio": (
            round(len(overlapping_groups) / len(holdout_groups), 4) if holdout_groups else 0.0
        ),
    }


def dataset_manifest(dataset: Dataset, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """JSON-safe provenance manifest (no message text)."""
    manifest = {
        "schema_version": 1,
        "dataset": dataset.summary(),
        "sources": [record.as_dict() for record in dataset.records],
        "policy": {
            "exact_duplicates_removed_before_splitting": True,
            "campaign_groups_kept_within_one_split": True,
            "threshold_tuned_on_validation_only": True,
            "message_text_included": False,
            "private_source_paths_included": False,
            "group_identifiers_included": False,
        },
    }
    if extra:
        manifest.update(extra)
    return manifest


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)
