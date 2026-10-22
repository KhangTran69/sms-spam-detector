"""Run one auditable train-and-evaluate workflow and keep its outputs together."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _commands(args: argparse.Namespace, model: Path, report: Path) -> tuple[list[str], list[str]]:
    common = ["--data", str(args.data)]
    supplements = [path for group in (args.supplement or []) for path in group]
    supplement_args = ["--supplement", *supplements] if supplements else ["--no-supplements"]
    holdout_args = ["--holdout", str(args.holdout)] if args.holdout else ["--holdout", "none"]
    train = [
        sys.executable,
        "-m",
        "src.train",
        *common,
        *supplement_args,
        *holdout_args,
        "--output",
        str(model),
        "--model-version",
        args.model_version,
        "--seed",
        str(args.seed),
        "--split-by",
        args.split_by,
        "--text-features",
        args.text_features,
        "--threshold-policy",
        args.threshold_policy,
        "--val-size",
        str(args.val_size),
        "--test-size",
        str(args.test_size),
        "--target-precision",
        str(args.target_precision),
        "--min-recall",
        str(args.min_recall),
    ]
    evaluate = [
        sys.executable,
        "-m",
        "src.evaluate",
        *common,
        *supplement_args,
        *holdout_args,
        "--model",
        str(model),
        "--plot",
        "none",
        "--json-out",
        str(report),
    ]
    return train, evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the selected CSV inputs, train a candidate, and write a message-free benchmark report. "
            "Use protected storage for any consented inputs or derived outputs."
        )
    )
    parser.add_argument("--data", type=Path, required=True, help="Approved base training CSV.")
    parser.add_argument(
        "--supplement",
        action="append",
        nargs="+",
        type=Path,
        help="Approved training supplement CSV(s); repeat the option as needed. Omitted means no supplements.",
    )
    parser.add_argument("--holdout", type=Path, help="Frozen approved holdout CSV; omit to skip holdout evaluation.")
    parser.add_argument("--output-dir", type=Path, required=True, help="New or empty directory for model and report.")
    parser.add_argument("--model-version", default="benchmark-candidate")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--split-by", choices=("group", "time", "random"), default="group")
    parser.add_argument("--text-features", choices=("word", "char", "combined"), default="combined")
    parser.add_argument("--threshold-policy", choices=("cv-robust", "validation"), default="cv-robust")
    parser.add_argument("--val-size", type=float, default=0.15)
    parser.add_argument("--test-size", type=float, default=0.15)
    parser.add_argument("--target-precision", type=float, default=0.95)
    parser.add_argument("--min-recall", type=float, default=0.80)
    args = parser.parse_args(argv)

    input_paths = [args.data, *(path for group in (args.supplement or []) for path in group)]
    if args.holdout:
        input_paths.append(args.holdout)
    missing = [str(path) for path in input_paths if not path.is_file()]
    if missing:
        print("data error: input file(s) not found: " + ", ".join(missing), file=sys.stderr)
        return 2

    output_dir = args.output_dir.expanduser().resolve()
    model = output_dir / "candidate.pkl"
    report = output_dir / "benchmark.json"
    if any(
        path.exists()
        for path in (model, model.with_suffix(".metadata.json"), model.with_suffix(".manifest.json"), report)
    ):
        print(
            f"output error: benchmark outputs already exist in {output_dir}; choose a new or empty directory",
            file=sys.stderr,
        )
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)

    train, evaluate = _commands(args, model, report)
    for command in (train, evaluate):
        result = subprocess.run(command, check=False)
        if result.returncode:
            return result.returncode
    print(f"Benchmark report: {report}")
    print(f"Evaluated artifact: {model}")
    print("Reports contain aggregate metrics and hashes only; protect outputs derived from consented data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
