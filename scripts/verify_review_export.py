"""Operator CLI for read-only reconciliation of a private review export."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from src.review_reconciliation import verify_export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--export", required=True, type=Path)
    parser.add_argument("--require-model-research", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = verify_export(args.database, args.export, require_model_research=args.require_model_research)
    except (OSError, ValueError, csv.Error, RuntimeError):
        print(json.dumps({"status": "verification_refused"}), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
