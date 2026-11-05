"""Local SQLite storage for explicitly consented message donations.

This optional collection store is separate from prediction. The donation API
must perform explicit-consent and PII checks before calling ``create_donation``.
Exports deliberately remain unlabelled, review-only staging data.
"""

from __future__ import annotations

import contextlib
import csv
import os
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

from src.privacy.scrub import detect_pii
from src.privacy.storage import ensure_private_directory

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DONATION_DB = ROOT / "data" / "donations" / "donations.sqlite3"
SCHEMA_VERSION = 2
RETENTION_DAYS = 90
_LANGUAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")
_NOTICE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EXPORT_COLUMNS = (
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
    "review_status",
    "eligible_for_modeling",
    "review_consent",
    "model_research_consent",
    "authorized_to_share",
    "consent_notice_version",
    "consented_at",
    "expires_at",
)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Consent timestamp must include a timezone.")
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _secure_parent(path: Path) -> None:
    ensure_private_directory(path.parent)


def _spreadsheet_safe_cell(value: object) -> str:
    """Keep untrusted CSV values from being evaluated as spreadsheet formulas."""
    text = "" if value is None else str(value)
    formula_candidate = text.lstrip()
    while formula_candidate.startswith("\ufeff"):
        formula_candidate = formula_candidate[1:].lstrip()
    if formula_candidate and ord(formula_candidate[0]) < 0x20:
        return "'" + text
    if formula_candidate.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _validated_database_path(path: Path) -> Path:
    database = Path(path).expanduser().resolve()
    repository = ROOT.resolve()
    private_root = (repository / "data" / "donations").resolve()
    if repository in database.parents and private_root not in database.parents:
        raise ValueError("Donation storage must be outside the repository or under ignored data/donations/ storage.")
    return database


def _create_private_database_file(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    except FileExistsError:
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    else:
        os.close(descriptor)


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=2.0)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA secure_delete=ON")
    return connection


def _purge_expired(connection: sqlite3.Connection, *, now: datetime | None = None) -> int:
    cutoff = _timestamp(now or datetime.now(UTC))
    cursor = connection.execute("DELETE FROM donations WHERE expires_at <= ?", (cutoff,))
    return cursor.rowcount


def bootstrap_database(path: Path) -> None:
    """Create/migrate the donation database and purge expired rows."""
    database = _validated_database_path(path)
    _secure_parent(database)
    try:
        _create_private_database_file(database)
        with _connect(database) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError("Donation database schema is newer than this application supports.")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS donations (
                    record_id TEXT PRIMARY KEY,
                    message TEXT NOT NULL,
                    label_hint TEXT,
                    language TEXT,
                    notice_version TEXT NOT NULL,
                    consented_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    withdrawn_at TEXT,
                    review_consent INTEGER NOT NULL DEFAULT 0,
                    model_research_consent INTEGER NOT NULL DEFAULT 0,
                    authorized_to_share INTEGER NOT NULL DEFAULT 0
                )"""
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(donations)")}
            for name in ("review_consent", "model_research_consent", "authorized_to_share"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE donations ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            expired = _purge_expired(connection)
        if expired:
            with _connect(database) as connection:
                connection.execute("VACUUM")
        with contextlib.suppress(OSError):
            os.chmod(database, 0o600)
    except sqlite3.Error as exc:
        raise RuntimeError(f"Could not initialize local donation storage ({type(exc).__name__}).") from None


def create_donation(
    path: Path,
    *,
    message: str,
    label_hint: str | None,
    language: str | None,
    notice_version: str,
    review_consent: bool,
    authorized_to_share: bool,
    model_research_consent: bool = False,
    consented_at: datetime | None = None,
) -> str:
    """Persist one donation after the API has checked consent and PII."""
    if not isinstance(message, str) or not message.strip() or len(message) > 10_000:
        raise ValueError("Donation message is blank or exceeds the supported limit.")
    if detect_pii(message, strict=True):
        raise ValueError("Donation message contains likely personal information; redact it before storage.")
    if label_hint not in {None, "ham", "spam"}:
        raise ValueError("Label hint must be ham or spam.")
    if language is not None and not _LANGUAGE_RE.fullmatch(language):
        raise ValueError("Language must be a short language code.")
    if not _NOTICE_VERSION_RE.fullmatch(notice_version):
        raise ValueError("Privacy notice version is invalid.")
    if review_consent is not True:
        raise ValueError("Explicit consent to local human review is required.")
    if authorized_to_share is not True:
        raise ValueError("The submitter must confirm they are authorized to share this message.")
    if type(model_research_consent) is not bool:
        raise ValueError("Model research consent must be an explicit yes or no.")
    accepted_at = consented_at or datetime.now(UTC)
    accepted_stamp = _timestamp(accepted_at)
    now = datetime.now(UTC)
    if accepted_at.astimezone(UTC) > now + timedelta(minutes=5):
        raise ValueError("Consent timestamp cannot be in the future.")
    expires_stamp = _timestamp(accepted_at.astimezone(UTC) + timedelta(days=RETENTION_DAYS))
    if accepted_at.astimezone(UTC) + timedelta(days=RETENTION_DAYS) <= now:
        raise ValueError("The donation retention period has already expired.")
    created_stamp = _timestamp(now)
    record_id = uuid.uuid4().hex
    path = _validated_database_path(path)
    bootstrap_database(path)
    try:
        with _connect(Path(path)) as connection:
            connection.execute(
                """INSERT INTO donations
                   (record_id, message, label_hint, language, notice_version, consented_at, created_at, expires_at,
                    review_consent, model_research_consent, authorized_to_share)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record_id,
                    message,
                    label_hint,
                    language,
                    notice_version,
                    accepted_stamp,
                    created_stamp,
                    expires_stamp,
                    int(review_consent),
                    int(model_research_consent),
                    int(authorized_to_share),
                ),
            )
    except sqlite3.Error as exc:
        raise RuntimeError(f"Could not save the donation ({type(exc).__name__}).") from None
    with contextlib.suppress(OSError):
        os.chmod(Path(path), 0o600)
    return record_id


def delete_donation(path: Path, record_id: str) -> bool:
    """Erase message and label content while retaining a short-lived tombstone."""
    path = _validated_database_path(path)
    bootstrap_database(path)
    withdrawn_at = _timestamp(datetime.now(UTC))
    try:
        with _connect(Path(path)) as connection:
            cursor = connection.execute(
                """UPDATE donations SET message='', label_hint=NULL, language=NULL, withdrawn_at=?
                   WHERE record_id=? AND withdrawn_at IS NULL""",
                (withdrawn_at, record_id),
            )
            changed = cursor.rowcount == 1
        if changed:
            with _connect(Path(path)) as connection:
                connection.execute("VACUUM")
        return changed
    except sqlite3.Error as exc:
        raise RuntimeError(f"Could not withdraw the donation ({type(exc).__name__}).") from None


def export_donations(path: Path, output: Path) -> dict[str, int]:
    """Create an exclusive, restrictive, unlabelled review-staging CSV."""
    destination = Path(output).expanduser().resolve()
    private_root = (ROOT / "data" / "donations").resolve()
    if ROOT.resolve() in destination.parents and private_root not in destination.parents:
        raise ValueError("Donation exports must be outside the repository or under ignored data/donations/ storage.")
    path = _validated_database_path(path)
    bootstrap_database(path)
    _secure_parent(destination)
    now = _timestamp(datetime.now(UTC))
    try:
        with _connect(Path(path)) as connection:
            rows = connection.execute(
                """SELECT record_id, message, language, notice_version, consented_at, expires_at,
                          review_consent, model_research_consent, authorized_to_share
                   FROM donations WHERE withdrawn_at IS NULL AND expires_at > ?
                     AND review_consent=1 AND authorized_to_share=1
                   ORDER BY created_at, record_id""",
                (now,),
            ).fetchall()
            withdrawn = int(
                connection.execute("SELECT COUNT(*) FROM donations WHERE withdrawn_at IS NOT NULL").fetchone()[0]
            )
    except sqlite3.Error as exc:
        raise RuntimeError(f"Could not read donation storage for export ({type(exc).__name__}).") from None

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    pii_blocked = 0
    exported = 0
    for (
        record_id,
        message,
        language,
        notice_version,
        consented_at,
        expires_at,
        review_consent,
        model_research_consent,
        authorized_to_share,
    ) in rows:
        if detect_pii(message, strict=True):
            pii_blocked += 1
            continue
        row = {
            "label": "",  # No donor hint is treated as verified ground truth.
            "message": message,
            "source": "donation_intake",
            "category": "unknown",
            "language": language or "unknown",
            "received_at": "",
            "data_kind": "consented",
            "dataset_id": "local-consented-donation",
            "dataset_version": SCHEMA_VERSION,
            "license": "consented-private",
            "record_id": record_id,
            "review_status": "pending_review",
            "eligible_for_modeling": "false",
            "review_consent": str(bool(review_consent)).lower(),
            "model_research_consent": str(bool(model_research_consent)).lower(),
            "authorized_to_share": str(bool(authorized_to_share)).lower(),
            "consent_notice_version": notice_version,
            "consented_at": consented_at,
            "expires_at": expires_at,
        }
        writer.writerow({key: _spreadsheet_safe_cell(value) for key, value in row.items()})
        exported += 1
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(stream.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        raise
    except OSError as exc:
        with contextlib.suppress(OSError):
            destination.unlink()
        raise RuntimeError(f"Could not write donation export ({type(exc).__name__}).") from None
    return {"exported": exported, "withdrawn": withdrawn, "pending_review": exported, "pii_blocked": pii_blocked}


def donation_summary(path: Path) -> dict[str, int]:
    """Return only aggregate counts; never return message values."""
    bootstrap_database(path)
    with _connect(Path(path)) as connection:
        total = int(connection.execute("SELECT COUNT(*) FROM donations").fetchone()[0])
        withdrawn = int(
            connection.execute("SELECT COUNT(*) FROM donations WHERE withdrawn_at IS NOT NULL").fetchone()[0]
        )
    return {"records": total, "withdrawn": withdrawn, "active": total - withdrawn}
