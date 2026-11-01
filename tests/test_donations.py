from __future__ import annotations

import csv
import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta

import pytest

from api.donations import bootstrap_database, create_donation, delete_donation, export_donations


def test_bootstrap_is_idempotent_and_records_current_schema(tmp_path):
    database = tmp_path / "donations.sqlite3"

    bootstrap_database(database)
    bootstrap_database(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        columns = {row[1] for row in connection.execute("PRAGMA table_info(donations)")}
    assert {
        "record_id",
        "message",
        "label_hint",
        "language",
        "notice_version",
        "consented_at",
        "expires_at",
        "withdrawn_at",
        "review_consent",
        "model_research_consent",
        "authorized_to_share",
    } <= columns


def test_v1_rows_migrate_closed_to_research_and_authorization(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """CREATE TABLE donations (
                record_id TEXT PRIMARY KEY, message TEXT NOT NULL, label_hint TEXT, language TEXT,
                notice_version TEXT NOT NULL, consented_at TEXT NOT NULL, created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, withdrawn_at TEXT
            ); PRAGMA user_version=1;"""
        )

    bootstrap_database(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT dflt_value FROM pragma_table_info('donations') WHERE name='model_research_consent'"
            ).fetchone()[0]
            == "0"
        )
        assert (
            connection.execute(
                "SELECT dflt_value FROM pragma_table_info('donations') WHERE name='authorized_to_share'"
            ).fetchone()[0]
            == "0"
        )


def test_create_donation_persists_consent_metadata_without_diagnostics(tmp_path, caplog):
    database = tmp_path / "donations.sqlite3"
    private_text = "Synthetic fixture only: please never log this private phrase"
    consented_at = datetime.now(UTC).replace(microsecond=0)

    record_id = create_donation(
        database,
        message=private_text,
        label_hint="spam",
        language="tl",
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=False,
        consented_at=consented_at,
    )

    with sqlite3.connect(database) as connection:
        record = connection.execute(
            "SELECT message, label_hint, language, notice_version, consented_at, withdrawn_at, "
            "review_consent, model_research_consent, authorized_to_share FROM donations WHERE record_id=?",
            (record_id,),
        ).fetchone()
    assert record == (private_text, "spam", "tl", "2026-11-01-v1", consented_at.isoformat(), None, 1, 0, 1)
    assert private_text not in caplog.text
    assert len(record_id) >= 32


def test_create_donation_rechecks_pii_before_storage(tmp_path):
    with pytest.raises(ValueError, match="likely personal information"):
        create_donation(
            tmp_path / "donations.sqlite3",
            message="Synthetic message with 09171234567",
            label_hint=None,
            language=None,
            notice_version="2026-11-01-v4",
            review_consent=True,
            authorized_to_share=True,
            model_research_consent=False,
        )

    assert not (tmp_path / "donations.sqlite3").exists()


def test_withdrawal_erases_text_and_is_idempotent(tmp_path):
    database = tmp_path / "donations.sqlite3"
    record_id = create_donation(
        database,
        message="Synthetic opt-in fixture message",
        label_hint="ham",
        language=None,
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=False,
    )

    assert delete_donation(database, record_id) is True
    assert delete_donation(database, record_id) is False
    with sqlite3.connect(database) as connection:
        message, withdrawn_at = connection.execute(
            "SELECT message, withdrawn_at FROM donations WHERE record_id=?", (record_id,)
        ).fetchone()
    assert message == ""
    assert withdrawn_at
    assert b"Synthetic opt-in fixture message" not in database.read_bytes()


def test_export_is_review_only_excludes_withdrawn_and_refuses_overwrite(tmp_path):
    database = tmp_path / "donations.sqlite3"
    pending_id = create_donation(
        database,
        message="Synthetic pending review message",
        label_hint="spam",
        language="fil",
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=True,
    )
    withdrawn_id = create_donation(
        database,
        message="Synthetic withdrawn message",
        label_hint=None,
        language="en",
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=False,
    )
    delete_donation(database, withdrawn_id)
    output = tmp_path / "review.csv"

    counts = export_donations(database, output)

    with output.open(newline="", encoding="utf-8") as handle:
        exported = list(csv.DictReader(handle))
    assert counts == {"exported": 1, "withdrawn": 1, "pending_review": 1, "pii_blocked": 0}
    assert len(exported) == 1
    assert exported[0]["record_id"] == pending_id
    assert exported[0]["message"] == "Synthetic pending review message"
    assert exported[0]["label"] == ""
    assert "label_hint" not in exported[0]
    assert exported[0]["review_status"] == "pending_review"
    assert exported[0]["eligible_for_modeling"] == "false"
    assert exported[0]["data_kind"] == "consented"
    assert "Synthetic withdrawn message" not in output.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        export_donations(database, output)


def test_export_rescreens_pii_and_reports_only_aggregate_count(tmp_path):
    database = tmp_path / "donations.sqlite3"
    private_text = "Synthetic fixture with 09171234567"
    record_id = create_donation(
        database,
        message="Synthetic fixture staged for manual review",
        label_hint=None,
        language=None,
        notice_version="2026-11-01-v4",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=True,
    )
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE donations SET message=? WHERE record_id=?", (private_text, record_id))
    output = tmp_path / "review.csv"

    counts = export_donations(database, output)

    assert counts["exported"] == 0
    assert counts["pii_blocked"] == 1
    assert private_text not in output.read_text(encoding="utf-8")


def test_expired_rows_are_purged_before_export(tmp_path):
    database = tmp_path / "donations.sqlite3"
    record_id = create_donation(
        database,
        message="Synthetic expired message",
        label_hint=None,
        language=None,
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=False,
    )
    with sqlite3.connect(database) as connection:
        expired = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="seconds")
        connection.execute("UPDATE donations SET expires_at=? WHERE record_id=?", (expired, record_id))
    output = tmp_path / "expired.csv"

    result = export_donations(database, output)

    assert result == {"exported": 0, "withdrawn": 0, "pending_review": 0, "pii_blocked": 0}
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM donations WHERE record_id=?", (record_id,)).fetchone()[0] == 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes are not available on this host")
def test_database_and_export_files_have_private_permissions(tmp_path):
    database = tmp_path / "donations" / "donations.sqlite3"
    create_donation(
        database,
        message="Synthetic private file-mode fixture",
        label_hint=None,
        language=None,
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=False,
    )
    output = tmp_path / "exports" / "review.csv"
    export_donations(database, output)

    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes are not available on this host")
def test_storage_refuses_an_accessible_parent_without_chmodding_it(tmp_path):
    exposed_parent = tmp_path / "shared"
    exposed_parent.mkdir()
    exposed_parent.chmod(0o755)

    with pytest.raises(ValueError, match="restrictive permissions"):
        create_donation(
            exposed_parent / "donations.sqlite3",
            message="Synthetic fixture stored only after safe permission checks",
            label_hint=None,
            language=None,
            notice_version="2026-11-01-v1",
            review_consent=True,
            authorized_to_share=True,
        )

    assert stat.S_IMODE(exposed_parent.stat().st_mode) == 0o755
    assert not (exposed_parent / "donations.sqlite3").exists()


def test_database_refuses_tracked_repository_paths(tmp_path, monkeypatch):
    import api.donations as donations

    repo = tmp_path / "repository"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(donations, "ROOT", repo)

    with pytest.raises(ValueError, match="outside the repository"):
        donations.create_donation(
            repo / "docs" / "accidental-donation.sqlite3",
            message="Synthetic path safety fixture",
            label_hint=None,
            language=None,
            notice_version="2026-11-01-v1",
            review_consent=True,
            authorized_to_share=True,
            model_research_consent=False,
        )

    assert not (repo / "docs" / "accidental-donation.sqlite3").exists()
