"""Reconcile an unmodified private review export with the current live donation store.

This check neither grants consent nor deletes external copies. It must be
repeated before reuse and cannot establish that a restored store is current.
"""

from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from api.donations import EXPORT_COLUMNS, SCHEMA_VERSION, _timestamp, _validated_database_path, review_export_row

MAX_EXPORT_BYTES = 50 * 1024 * 1024
MAX_EXPORT_ROWS = 20_000


def _private_file(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("A regular unshared private file is required.")
    if os.name == "posix" and (info.st_mode & 0o077 or resolved.parent.stat().st_mode & 0o077):
        raise ValueError("Private file and directory permissions are required.")
    return resolved


def _read_export(path: Path) -> list[dict[str, str]]:
    with _private_file(path).open("rb") as handle:
        content = handle.read(MAX_EXPORT_BYTES + 1)
    if len(content) > MAX_EXPORT_BYTES:
        raise ValueError("Review export exceeds byte budget.")
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
    if tuple(reader.fieldnames or ()) != EXPORT_COLUMNS:
        raise ValueError("Expected the unmodified review export schema.")
    rows = []
    seen = set()
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Malformed review export row.")
        record_id = row["record_id"]
        if not re.fullmatch(r"[a-f0-9]{32}", record_id) or record_id in seen:
            raise ValueError("Invalid or duplicate export record identifier.")
        seen.add(record_id)
        rows.append(row)
        if len(rows) > MAX_EXPORT_ROWS:
            raise ValueError("Review export exceeds row budget.")
    return rows


def verify_export(database: Path, export: Path, *, require_model_research: bool = False) -> dict[str, object]:
    """Compare full encoded rows in a read-only SQLite snapshot, without printing values."""
    database = _private_file(_validated_database_path(database))
    rows = _read_export(export)
    unavailable = changed = research_missing = matched = 0
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2.0)) as connection:
            connection.execute("BEGIN")
            if int(connection.execute("PRAGMA user_version").fetchone()[0]) != SCHEMA_VERSION:
                raise ValueError("Current supported donation schema required.")
            now = _timestamp(datetime.now(UTC))
            for row in rows:
                stored = connection.execute(
                    """SELECT record_id, message, language, notice_version, consented_at, expires_at,
                              review_consent, model_research_consent, authorized_to_share
                       FROM donations WHERE record_id=? AND withdrawn_at IS NULL AND expires_at>?
                         AND review_consent=1 AND authorized_to_share=1""",
                    (row["record_id"], now),
                ).fetchone()
                if stored is None:
                    unavailable += 1
                elif review_export_row(stored) != row:
                    changed += 1
                elif require_model_research and stored[7] != 1:
                    research_missing += 1
                else:
                    matched += 1
    except sqlite3.Error as exc:
        raise RuntimeError(f"Review reconciliation unavailable ({type(exc).__name__}).") from None
    return {
        "purpose": "current_store_snapshot_check_only",
        "status": "matched" if rows and matched == len(rows) else "blocked",
        "rows": len(rows),
        "matched": matched,
        "unavailable": unavailable,
        "changed_or_flagged": changed,
        "research_consent_missing": research_missing,
        "model_research_required": require_model_research,
        "consent_approval_verified": False,
    }


@contextmanager
def current_review_rows(database: Path, export: Path) -> Iterator[dict[str, dict[str, str]]]:
    """Hold a short write reservation through a private intake publication.

    No human review or training is performed while locked. Withdrawals and
    maintenance either precede this check or follow publication. The output
    is still a revocable copy, not permanent consent.
    """
    database = _private_file(_validated_database_path(database))
    rows = _read_export(export)
    if not rows:
        raise ValueError("Nonempty review export required.")
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=2.0)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if int(connection.execute("PRAGMA user_version").fetchone()[0]) != SCHEMA_VERSION:
                raise ValueError("Current supported donation schema required.")
            current: dict[str, dict[str, str]] = {}
            cutoff = _timestamp(datetime.now(UTC))
            for row in rows:
                stored = connection.execute(
                    """SELECT record_id, message, language, notice_version, consented_at, expires_at,
                              review_consent, model_research_consent, authorized_to_share
                       FROM donations WHERE record_id=? AND withdrawn_at IS NULL AND expires_at>?
                         AND review_consent=1 AND authorized_to_share=1 AND model_research_consent=1""",
                    (row["record_id"], cutoff),
                ).fetchone()
                if stored is None or review_export_row(stored) != row:
                    raise ValueError("Review export is no longer eligible.")
                current[row["record_id"]] = row
            yield current
            # This transaction made no database changes.
            connection.rollback()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Current review reservation unavailable ({type(exc).__name__}).") from None
