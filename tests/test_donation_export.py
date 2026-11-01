from __future__ import annotations

import csv
from pathlib import Path

import pytest
from scripts.export_donations import main

from api.donations import DEFAULT_DONATION_DB, EXPORT_COLUMNS, create_donation, delete_donation, export_donations

ROOT = Path(__file__).resolve().parents[1]


def test_export_refuses_tracked_repository_destinations(tmp_path):
    database = tmp_path / "donations.sqlite3"
    create_donation(
        database,
        message="Synthetic private fixture string",
        label_hint=None,
        language=None,
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=False,
    )

    with pytest.raises(ValueError, match="outside the repository"):
        export_donations(database, ROOT / "docs" / "accidental-donation-export.csv")


def test_export_uses_staging_schema_and_counts_withdrawals_and_label_status(tmp_path):
    database = tmp_path / "donations.sqlite3"
    hinted = create_donation(
        database,
        message="Synthetic review-only hinted example",
        label_hint="spam",
        language="tl",
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=True,
    )
    unlabelled = create_donation(
        database,
        message="Synthetic review-only unlabelled example",
        label_hint=None,
        language=None,
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=False,
    )
    deleted = create_donation(
        database,
        message="Synthetic withdrawn example",
        label_hint="ham",
        language="en",
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=False,
    )
    delete_donation(database, deleted)
    output = tmp_path / "private" / "staging.csv"

    counts = export_donations(database, output)

    with output.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert tuple(reader.fieldnames or ()) == EXPORT_COLUMNS
    assert counts == {"exported": 2, "withdrawn": 1, "pending_review": 2, "pii_blocked": 0}
    assert {row["record_id"] for row in rows} == {hinted, unlabelled}
    assert all(row["label"] == "" for row in rows)
    assert all(row["review_status"] == "pending_review" for row in rows)
    assert all(row["eligible_for_modeling"] == "false" for row in rows)
    by_id = {row["record_id"]: row for row in rows}
    assert "label_hint" not in by_id[hinted]
    assert "label_hint" not in by_id[unlabelled]
    assert by_id[hinted]["review_consent"] == "true"
    assert by_id[hinted]["model_research_consent"] == "true"
    assert by_id[unlabelled]["model_research_consent"] == "false"
    assert all(row["authorized_to_share"] == "true" for row in rows)
    assert all(row["data_kind"] == "consented" for row in rows)
    assert "Synthetic withdrawn example" not in output.read_text(encoding="utf-8")


def test_export_command_prints_counts_without_message_text(tmp_path, capsys):
    database = tmp_path / "donations.sqlite3"
    private_text = "Synthetic unique phrase that must not appear in output"
    create_donation(
        database,
        message=private_text,
        label_hint=None,
        language=None,
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=False,
    )
    output = tmp_path / "external" / "review.csv"

    assert main(["--database", str(database), "--output", str(output)]) == 0

    stdout = capsys.readouterr().out
    assert "1" in stdout and "pending review" in stdout.lower()
    assert "0 pii-flagged" in stdout.lower()
    assert private_text not in stdout
    assert output.is_file()


def test_export_command_defaults_to_ignored_database(tmp_path, monkeypatch, capsys):
    database = tmp_path / "local.sqlite3"
    output = tmp_path / "export.csv"
    create_donation(
        database,
        message="Synthetic fixture",
        label_hint=None,
        language=None,
        notice_version="2026-11-01-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=False,
    )
    monkeypatch.setattr("scripts.export_donations.DEFAULT_DONATION_DB", database)

    assert main(["--output", str(output)]) == 0

    assert "1" in capsys.readouterr().out
    assert DEFAULT_DONATION_DB.name == "donations.sqlite3"
