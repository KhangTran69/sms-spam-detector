#!/usr/bin/env python3
"""Fail a build when an inference benchmark report exceeds latency budgets.

Reads the message-free JSON written by `scripts/benchmark_performance.py` and
checks the two numbers that most directly affect user-visible responsiveness:
model load time and single-message p95 latency. Budgets are deliberately
generous by default so they catch regressions, not machine-to-machine noise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_MAX_P95_MS = 250.0
DEFAULT_MAX_LOAD_MS = 10_000.0


def _number(container: Any, key: str) -> float | None:
    if not isinstance(container, dict):
        return None
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def check_budget(
    result: dict[str, Any],
    *,
    max_p95_ms: float = DEFAULT_MAX_P95_MS,
    max_load_ms: float = DEFAULT_MAX_LOAD_MS,
) -> list[str]:
    """Return human-readable budget failures; an empty list means within budget."""
    failures: list[str] = []

    p95 = _number(result.get("single_prediction_latency_ms"), "p95")
    if p95 is None:
        failures.append("benchmark report has no numeric single_prediction_latency_ms.p95")
    elif p95 > max_p95_ms:
        failures.append(f"single-prediction p95 {p95:.1f} ms exceeds budget {max_p95_ms:.1f} ms")

    load_ms = _number(result.get("model_load"), "load_time_ms")
    if load_ms is None:
        failures.append("benchmark report has no numeric model_load.load_time_ms")
    elif load_ms > max_load_ms:
        failures.append(f"model load {load_ms:.1f} ms exceeds budget {max_load_ms:.1f} ms")

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check an inference benchmark against latency budgets.")
    parser.add_argument("report", type=Path, help="Path to a benchmark JSON report.")
    parser.add_argument("--max-p95-ms", type=float, default=DEFAULT_MAX_P95_MS)
    parser.add_argument("--max-load-ms", type=float, default=DEFAULT_MAX_LOAD_MS)
    args = parser.parse_args(argv)

    try:
        result = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: could not read benchmark report: {exc}", file=sys.stderr)
        return 2
    if not isinstance(result, dict):
        print("error: benchmark report must contain a JSON object", file=sys.stderr)
        return 2

    failures = check_budget(result, max_p95_ms=args.max_p95_ms, max_load_ms=args.max_load_ms)
    if failures:
        for failure in failures:
            print(f"budget failure: {failure}", file=sys.stderr)
        return 1

    print(f"Performance within budget: p95 <= {args.max_p95_ms:.1f} ms, load <= {args.max_load_ms:.1f} ms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
