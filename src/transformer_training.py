"""Opt-in local transformer fine-tuning on existing group-aware data splits.

The optional PyTorch and Transformers packages are imported only inside the
fine-tuning function. Dataset text stays in memory and is never written into
the provenance file.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import math
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.artifact_integrity import directory_sha256
from src.dataset_loading import Dataset
from src.dataset_splits import Split, grouped_splits, split_dataset
from src.metrics import select_threshold


class TransformerTrainingError(RuntimeError):
    """Transformer training inputs are incomplete or unsafe to use."""


def _validate_grouped_split(dataset: Dataset, split: Split) -> None:
    if not split.grouped:
        raise TransformerTrainingError("Transformer training requires a group-aware split; random fallback is blocked.")
    all_indices = [*split.train_idx, *split.val_idx, *split.test_idx]
    if sorted(all_indices) != list(range(len(dataset))) or len(set(all_indices)) != len(all_indices):
        raise TransformerTrainingError("The group-aware split must partition every dataset row exactly once.")
    group_sets = [
        {dataset.groups[index] for index in indices} for indices in (split.train_idx, split.val_idx, split.test_idx)
    ]
    if any(group_sets[left] & group_sets[right] for left in range(3) for right in range(left + 1, 3)):
        raise TransformerTrainingError("Campaign/template groups must not cross transformer data splits.")


def prepare_transformer_splits(
    dataset: Dataset,
    *,
    val_size: float = 0.15,
    test_size: float = 0.15,
    seed: int = 42,
    split_by: str = "group",
) -> tuple[Dataset, Dataset, Dataset, Split]:
    """Use the existing splitter and reject any random-split fallback."""
    split = grouped_splits(
        dataset,
        val_size=val_size,
        test_size=test_size,
        seed=seed,
        split_by=split_by,
    )
    _validate_grouped_split(dataset, split)
    train, validation, test = split_dataset(dataset, split)
    return train, validation, test, split


def validate_transformer_training_data(
    dataset: Dataset,
    *,
    allow_synthetic_demo: bool,
) -> dict[str, Any]:
    """Require declared provenance and mark any synthetic training as demo quality."""
    if dataset.frame.empty:
        raise TransformerTrainingError("Transformer training needs non-empty labeled data.")
    if not {"data_kind", "label", "message"}.issubset(dataset.frame.columns):
        raise TransformerTrainingError("Transformer training data is missing required provenance or label columns.")
    kinds = {
        str(value).strip().casefold() or "unknown" for value in dataset.frame["data_kind"].fillna("unknown").tolist()
    }
    unsupported = kinds - {"synthetic", "public", "consented"}
    if unsupported:
        raise TransformerTrainingError("Transformer training is blocked for data with unknown provenance.")
    real_kinds = kinds & {"public", "consented"}
    has_synthetic = "synthetic" in kinds
    if not real_kinds and not allow_synthetic_demo:
        raise TransformerTrainingError(
            "No declared non-synthetic corpus is present; pass --allow-synthetic-demo for a demo-quality model."
        )

    if not real_kinds:
        evidence_class = "synthetic_demo"
    elif has_synthetic:
        evidence_class = "mixed_demo"
    elif real_kinds == {"public", "consented"}:
        evidence_class = "public_and_consented"
    else:
        evidence_class = next(iter(real_kinds))
    return {"evidence_class": evidence_class, "demo_quality": has_synthetic}


def _training_validation_data(dataset: Dataset, split: Split) -> Dataset:
    indices = [*split.train_idx, *split.val_idx]
    frame = dataset.frame.iloc[indices].reset_index(drop=True)
    return Dataset(frame=frame, records=dataset.records, warnings=dataset.warnings)


def validate_transformer_plan(
    dataset: Dataset,
    split: Split,
    *,
    allow_synthetic_demo: bool,
) -> dict[str, Any]:
    """Validate split isolation and provenance before starting linear or GPU work."""
    _validate_grouped_split(dataset, split)
    return validate_transformer_training_data(
        _training_validation_data(dataset, split),
        allow_synthetic_demo=allow_synthetic_demo,
    )


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


class _MessageDataset:
    """Minimal in-memory dataset consumed by the Hugging Face Trainer."""

    def __init__(self, messages: Sequence[str], labels: Sequence[str]) -> None:
        self.messages = list(messages)
        self.labels = [0 if label == "ham" else 1 for label in labels]

    def __len__(self) -> int:
        return len(self.messages)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return {"text": self.messages[index], "labels": self.labels[index]}


def fine_tune_transformer(
    dataset: Dataset,
    split: Split,
    *,
    base_model_path: str | Path,
    output_dir: str | Path,
    allow_synthetic_demo: bool = False,
    seed: int = 42,
    epochs: float = 2.0,
    max_length: int = 256,
    train_batch_size: int = 8,
    eval_batch_size: int = 16,
    target_precision: float = 0.95,
    min_recall: float = 0.80,
) -> dict[str, Any]:
    """Fine-tune on train, use validation for Trainer evaluation, and seal test.

    The base checkpoint and resulting bundle are local-only. The test split is
    validated for disjointness and recorded by its membership fingerprint, but
    is never passed to model training or threshold selection.
    """
    _validate_grouped_split(dataset, split)
    evidence = validate_transformer_plan(dataset, split, allow_synthetic_demo=allow_synthetic_demo)
    base_path = Path(base_model_path)
    if not base_path.exists() or not base_path.is_dir():
        raise TransformerTrainingError("--base-model must point to an existing local model directory.")
    target_path = Path(output_dir)
    if target_path.exists() and (not target_path.is_dir() or any(target_path.iterdir())):
        raise TransformerTrainingError(
            "Transformer output path already exists and is not empty; refusing to overwrite it."
        )
    if not math.isfinite(float(epochs)) or epochs <= 0:
        raise TransformerTrainingError("epochs must be a finite value greater than zero.")
    if max_length < 8 or train_batch_size < 1 or eval_batch_size < 1:
        raise TransformerTrainingError("max_length and batch sizes must be positive, practical values.")
    if not 0.0 <= target_precision <= 1.0 or not 0.0 <= min_recall <= 1.0:
        raise TransformerTrainingError("target_precision and min_recall must be within [0, 1].")

    try:
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
    except ImportError as exc:
        raise TransformerTrainingError(
            "Transformer support is not installed. Install the optional 'transform' extra."
        ) from exc

    train_set = Dataset(
        frame=dataset.frame.iloc[split.train_idx].reset_index(drop=True),
        records=dataset.records,
        warnings=dataset.warnings,
    )
    validation_set = Dataset(
        frame=dataset.frame.iloc[split.val_idx].reset_index(drop=True),
        records=dataset.records,
        warnings=dataset.warnings,
    )
    if set(train_set.labels) != {"ham", "spam"} or set(validation_set.labels) != {"ham", "spam"}:
        raise TransformerTrainingError("Train and validation splits must each contain ham and spam examples.")

    output_parent = target_path.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=".smsd-transformer-", dir=output_parent))
    trainer_output = temporary_root / "trainer"
    model_output = temporary_root / "model"
    try:
        tokenizer = transformers.AutoTokenizer.from_pretrained(str(base_path), local_files_only=True, use_fast=True)
        model = transformers.AutoModelForSequenceClassification.from_pretrained(
            str(base_path),
            local_files_only=True,
            use_safetensors=True,
            num_labels=2,
            id2label={0: "ham", 1: "spam"},
            label2id={"ham": 0, "spam": 1},
        )
        if getattr(model.config, "model_type", None) != "xlm-roberta":
            raise TransformerTrainingError("The base checkpoint must use the XLM-RoBERTa model family.")

        class Collator:
            def __call__(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
                tokens = tokenizer(
                    [row["text"] for row in rows],
                    truncation=True,
                    max_length=max_length,
                    padding=True,
                    return_tensors="pt",
                )
                tokens["labels"] = torch.tensor([row["labels"] for row in rows], dtype=torch.long)
                return tokens

        args = transformers.TrainingArguments(
            output_dir=str(trainer_output),
            num_train_epochs=float(epochs),
            per_device_train_batch_size=train_batch_size,
            per_device_eval_batch_size=eval_batch_size,
            eval_strategy="epoch",
            save_strategy="no",
            logging_strategy="no",
            report_to=[],
            disable_tqdm=True,
            remove_unused_columns=False,
            use_cpu=True,
            seed=seed,
            data_seed=seed,
            dataloader_pin_memory=False,
        )
        training_dataset = _MessageDataset(train_set.messages, train_set.labels)
        validation_dataset = _MessageDataset(validation_set.messages, validation_set.labels)
        trainer = transformers.Trainer(
            model=model,
            args=args,
            train_dataset=training_dataset,
            eval_dataset=validation_dataset,
            data_collator=Collator(),
            processing_class=tokenizer,
        )
        trainer.train()
        validation_predictions = trainer.predict(validation_dataset).predictions
        if isinstance(validation_predictions, tuple):
            validation_predictions = validation_predictions[0]
        validation_logits = torch.as_tensor(validation_predictions)
        validation_spam_scores = torch.softmax(validation_logits, dim=-1)[:, 1].tolist()
        threshold_choice = select_threshold(
            validation_set.labels,
            validation_spam_scores,
            target_precision=target_precision,
            min_recall=min_recall,
        )
        suspicious_threshold = round(max(0.05, threshold_choice.threshold / 2.0), 4)
        model_output.mkdir()
        trainer.model.save_pretrained(model_output, safe_serialization=True)
        tokenizer.save_pretrained(model_output)
        model_content_sha256 = directory_sha256(model_output)

        metadata = {
            "schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "python_version": sys.version.split()[0],
            "base_model_sha256": directory_sha256(base_path),
            "model_content_sha256": model_content_sha256,
            "dataset_sources": [record.as_dict() for record in dataset.records],
            "data_kind_counts_train_validation": {
                str(key): int(value)
                for key, value in _training_validation_data(dataset, split)
                .frame["data_kind"]
                .fillna("unknown")
                .value_counts()
                .items()
            },
            "evidence_class": evidence["evidence_class"],
            "demo_quality": evidence["demo_quality"],
            "split_method": split.method,
            "split_seed": split.seed,
            "split_fingerprint": split.group_fingerprint(dataset.groups),
            "split_fingerprint_version": "row-membership-v1",
            "split_group_leakage": 0,
            "train_rows": len(train_set),
            "validation_rows": len(validation_set),
            "sealed_test_rows": len(split.test_idx),
            "decision_threshold": threshold_choice.threshold,
            "suspicious_threshold": suspicious_threshold,
            "threshold_selection_split": "validation",
            "threshold_selection": threshold_choice.as_dict(),
            "model_settings": {
                "epochs": float(epochs),
                "max_length": max_length,
                "train_batch_size": train_batch_size,
                "eval_batch_size": eval_batch_size,
                "seed": seed,
                "device": "cpu",
                "threshold_selection": "validation only; the final test split is not used",
                "target_precision": target_precision,
                "min_recall": min_recall,
            },
            "dependencies": {
                "torch": str(torch.__version__),
                "transformers": _version("transformers"),
                "accelerate": _version("accelerate"),
            },
            "test_metrics": None,
        }
        (model_output / "smsd-provenance.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if target_path.exists():
            target_path.rmdir()
        os.replace(model_output, target_path)
        return metadata
    except TransformerTrainingError:
        raise
    except Exception as exc:
        raise TransformerTrainingError(
            f"Local transformer fine-tuning failed ({type(exc).__name__}). Check the local checkpoint and optional dependencies."
        ) from exc
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
