"""Download and normalize approved public Philippine SMS datasets.

Only metadata and aggregate counts are written to sidecars. The source SMS
remains in ignored local storage and must never be committed to the repository.
"""

from __future__ import annotations

import base64
import contextlib
import csv
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from src.dataset_schema import DatasetError, _normalized_message_key

KAGGLE_DATASET_ID = "scottleechua/ph-spam-marketing-sms-w-timestamps"
KAGGLE_DATASET_URL = f"https://www.kaggle.com/datasets/{KAGGLE_DATASET_ID}"
KAGGLE_DOWNLOAD_URL = f"https://www.kaggle.com/api/v1/datasets/download/{KAGGLE_DATASET_ID}"
KAGGLE_LICENSE = "CC BY 4.0"
KAGGLE_ATTRIBUTION = "Scott Lee Chua, PH Spam + Marketing SMS (w/ timestamps), CC BY 4.0"
SOURCE_ID = "ph_spam_marketing_sms_timestamps"
DATASET_ID = "ph-spam-marketing-sms-w-timestamps"
PH_GITHUB_CSV_URL = "https://raw.githubusercontent.com/scottleechua/data/main/spam-and-marketing-sms/text-messages.csv"
PH_GITHUB_SOURCE_URL = "https://github.com/scottleechua/data/tree/main/spam-and-marketing-sms"
TAGALOG_KAGGLE_DATASET_ID = "onzero0/tagalog-sms"
TAGALOG_KAGGLE_DATASET_URL = f"https://www.kaggle.com/datasets/{TAGALOG_KAGGLE_DATASET_ID}"
TAGALOG_KAGGLE_DOWNLOAD_URL = f"https://www.kaggle.com/api/v1/datasets/download/{TAGALOG_KAGGLE_DATASET_ID}"
TAGALOG_KAGGLE_LICENSE = "CC0: Public Domain"
TAGALOG_KAGGLE_ATTRIBUTION = "ZERO (onzero0), Tagalog-SMS, Kaggle, CC0: Public Domain"
TAGALOG_SOURCE_ID = "tagalog_sms"
TAGALOG_DATASET_ID = "tagalog-sms"
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_CSV_BYTES = 100 * 1024 * 1024
REDACTED_RE = re.compile(r"^\s*(?:<\s*redacted\s*>|\[\s*redacted\s*\])\s*$", re.IGNORECASE)
CATEGORY_LABELS = {"spam": "spam", "ads": "spam", "gov": "ham", "notifs": "ham", "otp": "ham"}


def _prepare_private_directory(path: Path, *, secure_existing: bool = False) -> None:
    """Create a local data directory that only its owner can access."""
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not existed or secure_existing:
        os.chmod(path, 0o700)


def _write_private_bytes(path: Path, content: bytes) -> None:
    """Create a new private file, refusing overwrites and symlink targets."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.chmod(path, 0o600)
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink()
        raise


@dataclass(frozen=True)
class MessageRecord:
    """One labeled message in the shared internal dataset representation."""

    text: str
    label: str | None
    source: str
    record_id: str
    lang: str | None = None
    received_at: str | None = None
    category: str | None = None


def _normalized_headers(headers: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for header in headers:
        canonical = re.sub(r"[-\s]+", "_", header.strip().lower())
        if canonical in result:
            raise DatasetError("Dataset has duplicate columns after normalization.")
        result[canonical] = header
    return result


def _normalize_kaggle_sms_csv(
    path: str | Path,
    *,
    source_id: str,
) -> tuple[list[MessageRecord], dict[str, Any]]:
    """Map a Kaggle text/category export into the existing ham/spam schema.

    Unknown categories and blank/redacted records are excluded but counted.
    The report does not contain message values.
    """
    source_path = Path(path)
    if not source_path.is_file():
        raise DatasetError("Kaggle SMS CSV was not found; run `make datasets` first.")
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise DatasetError("Kaggle SMS CSV has no header row.")
            headers = _normalized_headers(reader.fieldnames)
            text_column = headers.get("text") or headers.get("message")
            category_column = headers.get("category") or headers.get("label")
            if text_column is None or category_column is None:
                raise DatasetError("Kaggle SMS CSV must contain text and category columns.")
            date_column = next(
                (headers[key] for key in ("date_received", "received_at", "date", "timestamp") if key in headers),
                None,
            )
            language_column = headers.get("language") or headers.get("lang")
            rows = list(reader)
    except UnicodeDecodeError:
        try:
            with source_path.open("r", encoding="latin-1", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    raise DatasetError("Kaggle SMS CSV has no header row.")
                headers = _normalized_headers(reader.fieldnames)
                text_column = headers.get("text") or headers.get("message")
                category_column = headers.get("category") or headers.get("label")
                if text_column is None or category_column is None:
                    raise DatasetError("Kaggle SMS CSV must contain text and category columns.")
                date_column = next(
                    (headers[key] for key in ("date_received", "received_at", "date", "timestamp") if key in headers),
                    None,
                )
                language_column = headers.get("language") or headers.get("lang")
                rows = list(reader)
        except (OSError, csv.Error):
            raise DatasetError("Kaggle SMS CSV could not be parsed.") from None
    except (OSError, csv.Error):
        raise DatasetError("Kaggle SMS CSV could not be parsed.") from None

    records: list[MessageRecord] = []
    seen_messages: set[str] = set()
    blank_or_redacted = 0
    duplicates_removed = 0
    unknown_categories: set[str] = set()
    unknown_category_rows = 0

    for row_number, row in enumerate(rows, start=2):
        text = (row.get(text_column) or "").strip()
        if not text or REDACTED_RE.fullmatch(text):
            blank_or_redacted += 1
            continue
        category = (row.get(category_column) or "").strip().lower()
        label = CATEGORY_LABELS.get(category)
        if label is None:
            unknown_category_rows += 1
            unknown_categories.add(category or "<blank>")
            continue
        message_key = _normalized_message_key(text)
        if message_key in seen_messages:
            duplicates_removed += 1
            continue
        seen_messages.add(message_key)
        record_id = hashlib.sha256(f"{source_hash}:{row_number}".encode()).hexdigest()
        records.append(
            MessageRecord(
                text=text,
                label=label,
                source=source_id,
                record_id=record_id,
                lang=((row.get(language_column) or "").strip() or None) if language_column else None,
                received_at=((row.get(date_column) or "").strip() or None) if date_column else None,
                category=category,
            )
        )

    report = {
        "rows_seen": len(rows),
        "rows_loaded": len(records),
        "blank_or_redacted_excluded": blank_or_redacted,
        "unknown_category_rows": unknown_category_rows,
        "duplicates_removed": duplicates_removed,
        "distinct_unknown_category_count": len(unknown_categories),
    }
    return records, report


def normalize_kaggle_ph_csv(path: str | Path) -> tuple[list[MessageRecord], dict[str, Any]]:
    """Normalize the PH Spam + Marketing SMS export."""
    return _normalize_kaggle_sms_csv(path, source_id=SOURCE_ID)


def normalize_kaggle_tagalog_csv(path: str | Path) -> tuple[list[MessageRecord], dict[str, Any]]:
    """Normalize Tagalog-SMS; sender metadata is deliberately not retained."""
    return _normalize_kaggle_sms_csv(path, source_id=TAGALOG_SOURCE_ID)


def _write_normalized_kaggle_dataset(
    records: list[MessageRecord],
    report: dict[str, Any],
    output_path: str | Path,
    *,
    dataset_id: str,
    license_name: str,
) -> tuple[Path, dict[str, Any]]:
    """Write normalized public rows under ignored ``data/external`` storage."""
    from src.import_public_dataset import ROOT

    destination = Path(output_path).resolve()
    external_root = (ROOT / "data" / "external").resolve()
    if external_root not in destination.parents:
        raise DatasetError("Normalized Kaggle output must be inside data/external/ ignored storage.")
    if destination.exists():
        raise DatasetError("Refusing to overwrite an existing normalized dataset.")
    if not records:
        raise DatasetError("No labeled, non-redacted rows remain after normalization.")
    _prepare_private_directory(destination.parent, secure_existing=True)
    snapshot_date = datetime.now(UTC).date().isoformat()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "label",
                "message",
                "source",
                "category",
                "language",
                "received_at",
                "data_kind",
                "dataset_id",
                "dataset_version",
                "license",
                "record_id",
            ),
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "label": record.label,
                    "message": record.text,
                    "source": record.source,
                    "category": record.category,
                    "language": record.lang,
                    "received_at": record.received_at,
                    "data_kind": "public",
                    "dataset_id": dataset_id,
                    "dataset_version": f"snapshot-{snapshot_date}",
                    "license": license_name,
                    "record_id": record.record_id,
                }
            )
    os.chmod(destination, 0o600)
    return destination, report


def import_kaggle_ph_dataset(path: str | Path, output_path: str | Path) -> tuple[Path, dict[str, Any]]:
    """Normalize the CC BY PH Spam + Marketing SMS export."""
    records, report = normalize_kaggle_ph_csv(path)
    return _write_normalized_kaggle_dataset(
        records,
        report,
        output_path,
        dataset_id=DATASET_ID,
        license_name=KAGGLE_LICENSE,
    )


def import_kaggle_tagalog_dataset(path: str | Path, output_path: str | Path) -> tuple[Path, dict[str, Any]]:
    """Normalize the CC0 Tagalog-SMS export, omitting sender fields."""
    records, report = normalize_kaggle_tagalog_csv(path)
    return _write_normalized_kaggle_dataset(
        records,
        report,
        output_path,
        dataset_id=TAGALOG_DATASET_ID,
        license_name=TAGALOG_KAGGLE_LICENSE,
    )


def _safe_csv_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    members = archive.infolist()
    for member in members:
        normalized_name = member.filename.replace("\\", "/")
        member_path = PurePosixPath(normalized_name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError("Kaggle archive contains an unsafe archive path.")
        if member.file_size < 0 or member.file_size > MAX_CSV_BYTES:
            raise ValueError("Kaggle archive CSV exceeds the supported size limit.")
    csv_members = [member for member in members if PurePosixPath(member.filename).suffix.lower() == ".csv"]
    if len(csv_members) != 1:
        raise ValueError("Kaggle archive must contain exactly one CSV dataset file.")
    return csv_members[0]


def _same_origin(left: str, right: str) -> bool:
    try:
        left_parts = urlsplit(left)
        right_parts = urlsplit(right)
        left_scheme = left_parts.scheme.lower()
        right_scheme = right_parts.scheme.lower()
        left_port = left_parts.port
        right_port = right_parts.port
    except ValueError:
        return False
    if left_port is None:
        left_port = 443 if left_scheme == "https" else 80 if left_scheme == "http" else None
    if right_port is None:
        right_port = 443 if right_scheme == "https" else 80 if right_scheme == "http" else None
    left_host = left_parts.hostname
    right_host = right_parts.hostname
    return (
        left_scheme == right_scheme
        and left_host is not None
        and right_host is not None
        and left_host.lower() == right_host.lower()
        and left_port == right_port
    )


class _KaggleCredentialRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent Kaggle Basic credentials from reaching a redirected host."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None or _same_origin(req.full_url, newurl):
            return redirected
        for header_store in (redirected.headers, redirected.unredirected_hdrs):
            for name in tuple(header_store):
                if name.lower() == "authorization":
                    del header_store[name]
        return redirected


def _download_kaggle_csv(
    destination: str | Path,
    username: str,
    key: str,
    *,
    dataset_id: str,
    source_url: str,
    download_url: str,
    license_name: str,
    attribution: str,
) -> Path:
    """Download and safely extract one Kaggle CSV without a new dependency."""
    output = Path(destination)
    metadata_path = output.with_suffix(output.suffix + ".metadata.json")
    if output.exists() or metadata_path.exists():
        raise ValueError("Refusing to overwrite an existing Kaggle download or metadata file.")
    if not username.strip() or not key.strip():
        raise ValueError("Kaggle download requires KAGGLE_USERNAME and KAGGLE_KEY credentials.")
    credentials = base64.b64encode(f"{username}:{key}".encode()).decode("ascii")
    request = urllib.request.Request(
        download_url,
        headers={"Authorization": f"Basic {credentials}", "User-Agent": "sms-spam-detector-dataset-loader/1"},
    )
    try:
        opener = urllib.request.build_opener(_KaggleCredentialRedirectHandler())
        with opener.open(request, timeout=90) as response:
            archive_bytes = response.read(MAX_ARCHIVE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Could not download the Kaggle dataset; verify credentials and network access.") from None
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ValueError("Kaggle archive exceeds the supported download size limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            member = _safe_csv_member(archive)
            csv_bytes = archive.read(member)
    except (zipfile.BadZipFile, KeyError, OSError):
        raise ValueError("Kaggle returned an invalid dataset archive.") from None
    from src.import_public_dataset import ROOT

    external_root = (ROOT / "data" / "external").resolve()
    output_parent = output.parent.resolve()
    managed_external_path = output_parent == external_root or external_root in output_parent.parents
    _prepare_private_directory(output_parent, secure_existing=managed_external_path)
    _write_private_bytes(output, csv_bytes)
    manifest = {
        "dataset_id": dataset_id,
        "source_url": source_url,
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "license": license_name,
        "attribution": attribution,
        "archive_member": Path(member.filename).name,
        "archive_bytes": len(archive_bytes),
        "csv_bytes": len(csv_bytes),
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "message_text_in_manifest": False,
    }
    _write_private_bytes(metadata_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return output


def download_kaggle_ph(destination: str | Path, username: str, key: str) -> Path:
    """Download the CC BY PH Spam + Marketing SMS CSV."""
    return _download_kaggle_csv(
        destination,
        username,
        key,
        dataset_id=DATASET_ID,
        source_url=KAGGLE_DATASET_URL,
        download_url=KAGGLE_DOWNLOAD_URL,
        license_name=KAGGLE_LICENSE,
        attribution=KAGGLE_ATTRIBUTION,
    )


def download_ph_github_csv(destination: str | Path) -> Path:
    """Fetch the publisher's current raw PH corpus without Kaggle credentials."""
    output = Path(destination)
    metadata_path = output.with_suffix(output.suffix + ".metadata.json")
    if output.exists() or metadata_path.exists():
        raise ValueError("Refusing to overwrite an existing PH dataset download or metadata file.")
    request = urllib.request.Request(
        PH_GITHUB_CSV_URL,
        headers={"User-Agent": "sms-spam-detector-dataset-loader/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            csv_bytes = response.read(MAX_CSV_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Could not download the publisher's PH CSV; verify network access and try again.") from None
    if len(csv_bytes) > MAX_CSV_BYTES:
        raise ValueError("Publisher PH CSV exceeds the supported download size limit.")
    try:
        header_text = csv_bytes.decode("utf-8-sig")
        headers = next(csv.reader(io.StringIO(header_text)), None)
        if headers is None:
            raise ValueError("Publisher PH CSV is empty; expected text and category columns.")
        normalized_headers = _normalized_headers(headers)
    except (UnicodeDecodeError, csv.Error, DatasetError):
        raise ValueError("Publisher PH response is not a valid UTF-8 CSV with unique headers.") from None
    if not (normalized_headers.get("text") or normalized_headers.get("message")) or not (
        normalized_headers.get("category") or normalized_headers.get("label")
    ):
        raise ValueError("Publisher PH CSV is missing the expected text and category columns.")

    from src.import_public_dataset import ROOT

    external_root = (ROOT / "data" / "external").resolve()
    output_parent = output.parent.resolve()
    managed_external_path = output_parent == external_root or external_root in output_parent.parents
    _prepare_private_directory(output_parent, secure_existing=managed_external_path)
    _write_private_bytes(output, csv_bytes)
    manifest = {
        "dataset_id": DATASET_ID,
        "source_url": PH_GITHUB_CSV_URL,
        "dataset_page": PH_GITHUB_SOURCE_URL,
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "license": KAGGLE_LICENSE,
        "attribution": KAGGLE_ATTRIBUTION,
        "csv_bytes": len(csv_bytes),
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "message_text_in_manifest": False,
    }
    _write_private_bytes(metadata_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return output


def download_kaggle_tagalog(destination: str | Path, username: str, key: str) -> Path:
    """Download the CC0 Tagalog-SMS CSV."""
    return _download_kaggle_csv(
        destination,
        username,
        key,
        dataset_id=TAGALOG_DATASET_ID,
        source_url=TAGALOG_KAGGLE_DATASET_URL,
        download_url=TAGALOG_KAGGLE_DOWNLOAD_URL,
        license_name=TAGALOG_KAGGLE_LICENSE,
        attribution=TAGALOG_KAGGLE_ATTRIBUTION,
    )
