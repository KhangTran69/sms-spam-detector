"""Dataset constants, column resolution, label normalization, and group keys."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

import pandas as pd

from src.preprocess import MONEY_RE, PHONE_RE, URL_RE, normalize_taglish

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_DATA = RAW_DIR / "spam.csv"
DEFAULT_SUPPLEMENTS: tuple[Path, ...] = (
    RAW_DIR / "ph_supplement.csv",
    RAW_DIR / "ph_supplement_2.csv",
    RAW_DIR / "ph_supplement_3.csv",
    RAW_DIR / "ph_supplement_4.csv",
    RAW_DIR / "ph_supplement_5.csv",
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
        "dataset_id": ("dataset_id",),
        "dataset_version": ("dataset_version", "version"),
        "license": ("license", "licence", "usage_terms"),
        "collection_period": ("collection_period", "collection_dates"),
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


def _normalized_message_key(message: str) -> str:
    """Normalize Unicode, case, and whitespace for duplicate detection only."""
    return " ".join(unicodedata.normalize("NFKC", message).casefold().split())


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
