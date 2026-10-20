"""Fail when a trained artifact's internal test F1 is below a floor.

Usage: python scripts/check_quality_gate.py models/uci.metadata.json --min-f1 0.90
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path, help="Metadata JSON sidecar written by src.train.")
    parser.add_argument("--min-f1", type=float, default=0.90, help="Minimum spam F1 on the internal test split.")
    args = parser.parse_args(argv)
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    test = metadata["metrics"]["test_at_threshold"]
    f1 = float(test["f1"])
    summary = (
        f"test spam F1={f1:.4f} precision={float(test['precision']):.4f} recall={float(test['recall']):.4f} "
        f"threshold={float(metadata['threshold']):.2f} n={test.get('n', test.get('support', '?'))} "
        f"ECE={metadata['metrics']['calibration']['test']['expected_calibration_error']:.4f}"
    )
    print(summary)
    if f1 < args.min_f1:
        print(f"FAIL: test F1 {f1:.4f} is below the {args.min_f1:.2f} floor", file=sys.stderr)
        return 1
    print(f"PASS: test F1 >= {args.min_f1:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
