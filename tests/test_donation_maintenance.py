from __future__ import annotations

import json

from api.donations import bootstrap_database
from scripts.maintain_donations import main
from scripts.rehearse_donation_recovery import rehearse


def test_maintenance_cli_requires_existing_database_and_reports_counts(tmp_path, capsys):
    database = tmp_path / "private.sqlite3"
    assert main(["--database", str(database)]) == 2
    assert json.loads(capsys.readouterr().err) == {"status": "maintenance_refused"}
    bootstrap_database(database)
    assert main(["--database", str(database), "--compact"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["remaining"] == 0
    assert str(database) not in output


def test_disposable_recovery_rehearsal_reconciles_withdrawal_and_blocks_replay():
    report = rehearse()
    assert report["sqlite_integrity_ok"] is True
    assert report["stale_snapshot_resurrection_risk_reproduced"] is True
    assert report["withdrawal_reconciled_before_export"] is True
    assert report["retry_blocked_after_reconciliation"] is True
    assert report["exported_rows"] == 0
    assert report["real_restore_verified"] is False
