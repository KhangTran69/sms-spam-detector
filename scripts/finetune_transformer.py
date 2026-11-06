#!/usr/bin/env python3
"""Fine-tune the optional transformer on explicit, local CSV inputs only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    from src.dataset_loading import DatasetError, load_training_dataset
    from src.transformer_training import (
        TransformerTrainingError,
        fine_tune_transformer,
        prepare_transformer_splits,
    )

    parser = argparse.ArgumentParser(
        description="Fine-tune a local transformer using group-isolated splits; never downloads data or weights."
    )
    parser.add_argument("--data", required=True, help="Explicit labeled CSV path.")
    parser.add_argument(
        "--supplement",
        action="extend",
        nargs="+",
        default=None,
        metavar="CSV",
        help="Optional explicit supplement CSV(s); no implicit supplements are added.",
    )
    parser.add_argument("--base-model", required=True, help="Existing local pretrained model directory.")
    parser.add_argument("--output", required=True, help="New or empty directory for the fine-tuned model.")
    parser.add_argument("--split-by", choices=("group", "time", "random"), default="group")
    parser.add_argument("--val-size", type=float, default=0.15)
    parser.add_argument("--test-size", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--train-batch-size", type=int, default=8)
    parser.add_argument("--eval-batch-size", type=int, default=16)
    parser.add_argument("--target-precision", type=float, default=0.95)
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument(
        "--allow-synthetic-demo",
        action="store_true",
        help="Explicitly permit synthetic-only research output, which is labeled demo-quality.",
    )
    args = parser.parse_args(argv)

    try:
        dataset = load_training_dataset(
            args.data,
            args.supplement,
            strict_data=True,
            strict_supplement_paths=bool(args.supplement),
        )
        train_set, validation_set, test_set, split = prepare_transformer_splits(
            dataset,
            val_size=args.val_size,
            test_size=args.test_size,
            seed=args.seed,
            split_by=args.split_by,
        )
        metadata = fine_tune_transformer(
            dataset,
            split,
            base_model_path=args.base_model,
            output_dir=args.output,
            allow_synthetic_demo=args.allow_synthetic_demo,
            seed=args.seed,
            epochs=args.epochs,
            max_length=args.max_length,
            train_batch_size=args.train_batch_size,
            eval_batch_size=args.eval_batch_size,
            target_precision=args.target_precision,
            min_recall=args.min_recall,
        )
    except (DatasetError, TransformerTrainingError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": "trained",
                "output": str(Path(args.output)),
                "evidence_class": metadata["evidence_class"],
                "demo_quality": metadata["demo_quality"],
                "split_method": split.method,
                "train_rows": len(train_set),
                "validation_rows": len(validation_set),
                "sealed_test_rows": len(test_set),
                "test_metrics": None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
