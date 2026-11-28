"""Operator-only retention maintenance; never opens a default store implicitly."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.donations import maintain_donations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = maintain_donations(args.database, compact=args.compact)
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({"status": "maintenance_refused"}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1 if args.compact and not result["compacted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
