"""Reproduce the checked-in synthetic SMS pipeline benchmark.

This command trains from the tracked synthetic fixtures with a fixed split and
model seed. Its metrics are pipeline checks, not real-world accuracy claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from src.data import DEFAULT_HOLDOUT, ROOT as DATA_ROOT
from src.train import train

BENCHMARK_SEED = 42
TRAINING_FILES = (
    "ph_supplement.csv",
    "ph_supplement_2.csv",
    "ph_supplement_3.csv",
    "ph_supplement_4.csv",
    "ph_supplement_5.csv",
)
BENCHMARK_BANNER = "SYNTHETIC BENCHMARK — NOT REAL-WORLD PERFORMANCE"


def run_benchmark() -> dict[str, Any]:
    """Train and return a deterministic, JSON-safe report from tracked fixtures."""
    paths = [DATA_ROOT / "data" / "raw" / name for name in TRAINING_FILES]
    with TemporaryDirectory(prefix="sms-synthetic-benchmark-") as temp_dir:
        artifact = train(
            data_path=paths[0],
            supplement_path=paths[1:],
            model_path=Path(temp_dir) / "benchmark-model.pkl",
            holdout_path=DEFAULT_HOLDOUT,
            random_state=BENCHMARK_SEED,
            model_version=f"synthetic-benchmark-seed-{BENCHMARK_SEED}",
            strict_supplement_paths=True,
            write_metadata=False,
            verbose=False,
        )

    holdout_path = Path(DEFAULT_HOLDOUT)
    holdout_digest = hashlib.sha256(holdout_path.read_bytes()).hexdigest()
    return {
        "schema_version": 1,
        "benchmark": "checked-in Philippine SMS synthetic fixtures",
        "banner": BENCHMARK_BANNER,
        "real_world_performance_claim": False,
        "seed": BENCHMARK_SEED,
        "split_method": artifact["training_config"]["split_by"],
        "data_kind_counts": {
            str(kind): int(count) for kind, count in sorted(artifact["training_data_kind_counts"].items())
        },
        "input_files": [Path(record["path"]).name for record in artifact["data_sources"]],
        "input_sha256": {Path(record["path"]).name: record["sha256"] for record in artifact["data_sources"]},
        "holdout_file": holdout_path.name,
        "holdout_sha256": holdout_digest,
        "split_summary": artifact["split_summary"],
        "test_metrics": artifact["metrics"]["test_at_threshold"],
        "synthetic_holdout_metrics": artifact["metrics"]["holdout_at_threshold"],
        "holdout_leakage": artifact["holdout_leakage"],
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the fixed-seed synthetic SMS benchmark.")
    parser.add_argument("--json-out", type=Path, help="Write the report to this path; stdout is the default.")
    args = parser.parse_args(argv)
    report = run_benchmark()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
