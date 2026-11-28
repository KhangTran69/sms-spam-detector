"""Local SQLite storage for explicitly consented message donations.

This optional collection store is separate from prediction. The donation API
must perform explicit-consent and PII checks before calling ``create_donation``.
Exports deliberately remain unlabelled, review-only staging data.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import os
import re
import sqlite3
import stat
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

from src.privacy.scrub import detect_pii
from src.privacy.storage import ensure_private_directory

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DONATION_DB = ROOT / "data" / "donations" / "donations.sqlite3"
SCHEMA_VERSION = 3
EXPORT_SCHEMA_VERSION = 2
RETENTION_DAYS = 90
_LANGUAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")
_SUBMISSION_KEY_RE = re.compile(r"^[a-f0-9]{32}$")
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


class DonationConflict(ValueError):
    """A submission key was already used for a different or withdrawn record."""


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
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Donation storage must be a regular, unshared file.") from None
        os.chmod(path, 0o600)
    else:
        os.close(descriptor)


@contextlib.contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=2.0)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA secure_delete=ON")
        with connection:
            yield connection
    finally:
        connection.close()


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
            connection.execute("BEGIN IMMEDIATE")
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
                    authorized_to_share INTEGER NOT NULL DEFAULT 0,
                    submission_key_hash TEXT
                )"""
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(donations)")}
            for name in ("review_consent", "model_research_consent", "authorized_to_share"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE donations ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
            if "submission_key_hash" not in columns:
                connection.execute("ALTER TABLE donations ADD COLUMN submission_key_hash TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS donations_submission_key ON donations(submission_key_hash)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS donations_expiry ON donations(expires_at)")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            _purge_expired(connection)
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
    submission_key: str | None = None,
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
    if submission_key is not None and not _SUBMISSION_KEY_RE.fullmatch(submission_key):
        raise ValueError("Invalid submission key.")
    key_hash = hashlib.sha256(submission_key.encode("ascii")).hexdigest() if submission_key is not None else None
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
            connection.execute("BEGIN IMMEDIATE")
            # Recheck after acquiring the write lock: admission can wait on SQLite.
            if expires_stamp <= _timestamp(datetime.now(UTC)):
                raise ValueError("The donation retention period has already expired.")
            if key_hash is not None:
                existing = connection.execute(
                    """SELECT record_id, message, label_hint, language, notice_version,
                              review_consent, model_research_consent, authorized_to_share, withdrawn_at, expires_at
                       FROM donations WHERE submission_key_hash=?""",
                    (key_hash,),
                ).fetchone()
                if existing is not None:
                    expected = (
                        message,
                        label_hint,
                        language,
                        notice_version,
                        int(review_consent),
                        int(model_research_consent),
                        int(authorized_to_share),
                        None,
                    )
                    if existing[1:-1] != expected or existing[-1] <= _timestamp(datetime.now(UTC)):
                        raise DonationConflict("Submission key already used.")
                    return str(existing[0])
            connection.execute(
                """INSERT INTO donations
                   (record_id, message, label_hint, language, notice_version, consented_at, created_at, expires_at,
                    review_consent, model_research_consent, authorized_to_share, submission_key_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    key_hash,
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
        # secure_delete is enabled on the transaction itself. Do not turn a
        # committed erasure into a reported failure because optional compaction
        # could not acquire an additional exclusive database lock.
        return changed
    except sqlite3.Error as exc:
        raise RuntimeError(f"Could not withdraw the donation ({type(exc).__name__}).") from None


def review_export_row(
    stored: tuple[str, str, str | None, str, str, str, int, int, int],
) -> dict[str, str] | None:
    """Encode a current review-staging row identically for export and verification."""
    (
        record_id, message, language, notice_version, consented_at, expires_at,
        review_consent, model_research_consent, authorized_to_share,
    ) = stored
    if detect_pii(message, strict=True):
        return None
    row = {
        "label": "",  # No donor hint is treated as verified ground truth.
        "message": message,
        "source": "donation_intake",
        "category": "unknown",
        "language": language or "unknown",
        "received_at": "",
        "data_kind": "consented",
        "dataset_id": "local-consented-donation",
        "dataset_version": EXPORT_SCHEMA_VERSION,
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
    return {key: _spreadsheet_safe_cell(value) for key, value in row.items()}


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
            connection.execute("BEGIN")
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
    for stored in rows:
        row = review_export_row(stored)
        if row is None:
            pii_blocked += 1
            continue
        writer.writerow(row)
        exported += 1
    # Publish a complete file exclusively; never unlink a destination we did
    # not create. A same-directory hard link prevents partial CSV visibility.
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=destination.parent, prefix=".review-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(stream.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    except FileExistsError:
        raise
    except OSError as exc:
        raise RuntimeError(f"Could not write donation export ({type(exc).__name__}).") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"exported": exported, "withdrawn": withdrawn, "pending_review": exported, "pii_blocked": pii_blocked}


def donation_summary(path: Path) -> dict[str, int]:
    """Return only aggregate counts from a single snapshot; never return message values."""
    path = _validated_database_path(path)
    bootstrap_database(path)
    with _connect(path) as connection:
        total, withdrawn = connection.execute(
            "SELECT COUNT(*), COUNT(withdrawn_at) FROM donations"
        ).fetchone()
        total, withdrawn = int(total), int(withdrawn)
    return {"records": total, "withdrawn": withdrawn, "active": total - withdrawn}


def maintain_donations(path: Path, *, compact: bool = False) -> dict[str, int | bool]:
    """Purge expired records in an existing private store; optionally compact.

    This is an operator operation, not a request-path requirement. Report only
    aggregate counts. Never initialize a missing database by mistake.
    """
    database = _validated_database_path(path)
    if not database.is_file():
        raise ValueError("Existing donation database required.")
    _secure_parent(database)
    _create_private_database_file(database)
    try:
        with _connect(database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version != SCHEMA_VERSION:
                raise ValueError("Donation storage requires the supported schema before maintenance.")
            purged = _purge_expired(connection)
            remaining = int(connection.execute("SELECT COUNT(*) FROM donations").fetchone()[0])
    except sqlite3.Error as exc:
        raise RuntimeError(f"Donation maintenance failed ({type(exc).__name__}).") from None

    compacted = False
    if compact:
        try:
            with _connect(database) as connection:
                connection.execute("VACUUM")
            compacted = True
        except sqlite3.Error:
            # The purge already committed; retry only the compaction later.
            pass
    return {"purged": purged, "remaining": remaining, "compaction_requested": compact, "compacted": compacted}
