from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import closing

import pytest

from api.donations import create_donation, delete_donation, export_donations, maintain_donations
from scripts.verify_review_export import main, verify_export


def _create(database, *, research=True):
    return create_donation(
        database,
        message="Synthetic review reconciliation fixture",
        label_hint=None,
        language="en",
        notice_version="fixture-v1",
        review_consent=True,
        authorized_to_share=True,
        model_research_consent=research,
        submission_key="a" * 32,
    )


def test_current_snapshot_then_withdrawal_blocks_reuse(tmp_path, capsys):
    database = tmp_path / "private.sqlite3"
    export = tmp_path / "review.csv"
    receipt = _create(database)
    export_donations(database, export)
    original = export.read_bytes()
    assert main(["--database", str(database), "--export", str(export), "--require-model-research"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] == 1
    assert report["consent_approval_verified"] is False
    assert delete_donation(database, receipt)
    assert main(["--database", str(database), "--export", str(export)]) == 1
    raw = capsys.readouterr().out
    assert json.loads(raw)["unavailable"] == 1
    assert receipt not in raw and "Synthetic" not in raw and str(database) not in raw
    assert export.read_bytes() == original


def test_expiry_is_blocked_even_before_maintenance(tmp_path):
    database = tmp_path / "private.sqlite3"
    export = tmp_path / "review.csv"
    receipt = _create(database)
    export_donations(database, export)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE donations SET expires_at=? WHERE record_id=?", ("2000-01-01T00:00:00+00:00", receipt))
    assert verify_export(database, export)["unavailable"] == 1
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM donations").fetchone()[0] == 1
    assert maintain_donations(database)["purged"] == 1
    assert verify_export(database, export)["unavailable"] == 1


def test_review_only_consent_is_not_research_consent(tmp_path):
    database = tmp_path / "private.sqlite3"
    export = tmp_path / "review.csv"
    _create(database, research=False)
    export_donations(database, export)
    assert verify_export(database, export)["status"] == "matched"
    report = verify_export(database, export, require_model_research=True)
    assert report["status"] == "blocked"
    assert report["research_consent_missing"] == 1


@pytest.mark.parametrize("field", ["message", "model_research_consent", "expires_at", "label"])
def test_modified_export_metadata_or_content_is_blocked(tmp_path, field):
    database = tmp_path / "private.sqlite3"
    export = tmp_path / "review.csv"
    _create(database)
    export_donations(database, export)
    with export.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    rows[0][field] = "modified fictional value"
    with export.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    assert verify_export(database, export)["changed_or_flagged"] == 1


def test_duplicate_or_missing_store_refused_without_creating_database(tmp_path, capsys):
    database = tmp_path / "private.sqlite3"
    export = tmp_path / "review.csv"
    _create(database)
    export_donations(database, export)
    lines = export.read_text(encoding="utf-8").splitlines()
    export.write_text("\n".join([*lines, lines[1]]) + "\n", encoding="utf-8")
    assert main(["--database", str(database), "--export", str(export)]) == 2
    assert json.loads(capsys.readouterr().err) == {"status": "verification_refused"}
    missing = tmp_path / "missing.sqlite3"
    assert main(["--database", str(missing), "--export", str(export)]) == 2
    assert not missing.exists()
