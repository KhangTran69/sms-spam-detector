"""Disposable SQLite recovery rehearsal. No user database or model is accepted."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from api.donations import DonationConflict, create_donation, delete_donation, donation_summary, export_donations


def rehearse() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="smsd-recovery-fixture-") as root:
        source = Path(root) / "source.sqlite3"
        backup = Path(root) / "backup.sqlite3"
        restored = Path(root) / "restored.sqlite3"
        payload = {
            "message": "Synthetic recovery fixture",
            "label_hint": None,
            "language": "en",
            "notice_version": "fixture-v1",
            "review_consent": True,
            "authorized_to_share": True,
            "submission_key": "a" * 32,
        }
        receipt = create_donation(source, **payload)
        with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(backup)) as copy:
            original.backup(copy)
        backup.chmod(0o600)
        if not delete_donation(source, receipt):
            raise RuntimeError("Fixture withdrawal failed.")
        with closing(sqlite3.connect(backup)) as copy, closing(sqlite3.connect(restored)) as target:
            copy.backup(target)
        restored.chmod(0o600)
        if donation_summary(restored)["active"] != 1:
            raise RuntimeError("Stale backup fixture did not reproduce the expected risk.")
        # In a real recovery the custodian must reconcile against current
        # consent/withdrawal records BEFORE reopening or exporting the store.
        if not delete_donation(restored, receipt):
            raise RuntimeError("Fixture reconciliation failed.")
        try:
            create_donation(restored, **payload)
        except DonationConflict:
            blocked = True
        else:
            blocked = False
        export = export_donations(restored, Path(root) / "review.csv")
        if not blocked or export["exported"] != 0:
            raise RuntimeError("Fixture restore safety check failed.")
        with closing(sqlite3.connect(restored)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        if not integrity:
            raise RuntimeError("Fixture integrity check failed.")
        return {
            "purpose": "synthetic_recovery_rehearsal_only",
            "sqlite_integrity_ok": integrity,
            "stale_snapshot_resurrection_risk_reproduced": True,
            "withdrawal_reconciled_before_export": True,
            "retry_blocked_after_reconciliation": blocked,
            "exported_rows": export["exported"],
            "real_restore_verified": False,
        }


def main() -> int:
    print(json.dumps(rehearse(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
