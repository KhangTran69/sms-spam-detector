"""Export local donations as unlabelled, review-only staging data."""

from __future__ import annotations

import argparse
from pathlib import Path

from api.donations import DEFAULT_DONATION_DB, export_donations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DONATION_DB, help="Local ignored SQLite database.")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New CSV destination outside the repository or under ignored data/donations/ storage.",
    )
    args = parser.parse_args(argv)
    try:
        counts = export_donations(args.database, args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(
        f"Exported {counts['exported']} active message(s) to pending review; "
        f"{counts['withdrawn']} withdrawn and {counts['pii_blocked']} PII-flagged record(s) omitted. "
        "No row is labeled for model use."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
