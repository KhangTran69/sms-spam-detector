from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src.dataset_loading import Dataset
from src.transformer_training import (
    TransformerTrainingError,
    fine_tune_transformer,
    prepare_transformer_splits,
    validate_transformer_training_data,
)


def _dataset(data_kind: str, size: int = 60) -> Dataset:
    rows = []
    for index in range(size):
        label = "spam" if index % 2 else "ham"
        rows.append(
            {
                "message": f"Synthetic fixture {label} groupword{index} https://example.test/{index}",
                "label": label,
                "group": f"synthetic-campaign-{index}",
                "data_kind": data_kind,
                "source": "synthetic-test",
                "category": "other",
                "language": "taglish",
                "received_at": "",
            }
        )
    return Dataset(frame=pd.DataFrame(rows))


def test_transformer_split_uses_existing_grouped_membership_and_keeps_test_separate():
    dataset = _dataset("public")

    train, validation, test, split = prepare_transformer_splits(
        dataset,
        val_size=0.15,
        test_size=0.15,
        seed=17,
        split_by="group",
    )

    assert split.grouped
    assert split.method == "stratified_group_kfold"
    assert train.frame["group"].is_unique
    assert validation.frame["group"].is_unique
    assert test.frame["group"].is_unique
    train_groups = set(train.groups)
    validation_groups = set(validation.groups)
    test_groups = set(test.groups)
    assert not train_groups & validation_groups
    assert not train_groups & test_groups
    assert not validation_groups & test_groups
    assert len(train) + len(validation) + len(test) == len(dataset)


def test_transformer_refuses_random_split_that_can_leak_groups():
    with pytest.raises(TransformerTrainingError, match="group-aware split"):
        prepare_transformer_splits(_dataset("public"), split_by="random")


def test_synthetic_only_training_requires_explicit_demo_opt_in():
    train, _validation, _test, _split = prepare_transformer_splits(_dataset("synthetic"))

    with pytest.raises(TransformerTrainingError, match="--allow-synthetic-demo"):
        validate_transformer_training_data(train, allow_synthetic_demo=False)


def test_synthetic_demo_outputs_are_explicitly_labeled():
    train, _validation, _test, _split = prepare_transformer_splits(_dataset("synthetic"))

    evidence = validate_transformer_training_data(train, allow_synthetic_demo=True)

    assert evidence == {"evidence_class": "synthetic_demo", "demo_quality": True}


def test_importing_linear_training_does_not_import_transformer_dependencies():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import src.train; assert 'torch' not in sys.modules; assert 'transformers' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, "linear training imported optional transformer dependencies"


def test_finetune_uses_train_and_validation_only_and_writes_content_free_demo_metadata(monkeypatch, tmp_path):
    from src import transformer_training

    dataset = _dataset("synthetic")
    train, validation, test, split = prepare_transformer_splits(dataset, seed=9)
    seen_train: list[str] = []
    seen_validation: list[str] = []

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, _path, **kwargs):
            assert kwargs["local_files_only"] is True
            return cls()

        def __call__(self, messages, **_kwargs):
            return {"input_ids": [[1, 2] for _ in messages]}

        def save_pretrained(self, destination):
            (destination / "tokenizer.json").write_text("synthetic tokenizer fixture", encoding="utf-8")

    class FakeModel:
        config = SimpleNamespace(model_type="xlm-roberta")

        @classmethod
        def from_pretrained(cls, _path, **kwargs):
            assert kwargs["local_files_only"] is True
            return cls()

        def save_pretrained(self, destination, *, safe_serialization):
            assert safe_serialization is True
            (destination / "model.safetensors").write_bytes(b"synthetic model fixture")

    class FakeTrainer:
        def __init__(self, *, model, args, train_dataset, eval_dataset, data_collator, processing_class):
            self.model = model
            self.train_dataset = train_dataset
            self.eval_dataset = eval_dataset
            self.data_collator = data_collator
            self.processing_class = processing_class
            seen_train.extend(train_dataset.messages)
            seen_validation.extend(eval_dataset.messages)
            assert args.use_cpu is True
            assert args.report_to == []

        def train(self):
            self.data_collator([self.train_dataset[0]])
            self.data_collator([self.eval_dataset[0]])

        def predict(self, dataset):
            predictions = [[0.9, 0.1] if label == 0 else [0.1, 0.9] for label in dataset.labels]
            return SimpleNamespace(predictions=predictions)

    class FakeProbabilities:
        def __init__(self, logits):
            self.logits = logits

        def __getitem__(self, index):
            assert index == (slice(None), 1)
            scores = [0.83 if row[1] == 1 else 0.16 for row in self.logits]
            return SimpleNamespace(tolist=lambda: scores)

    fake_torch = SimpleNamespace(
        __version__="test",
        long="long",
        tensor=lambda values, dtype: values,
        as_tensor=lambda values: values,
        softmax=lambda logits, dim: FakeProbabilities(logits),
    )
    fake_transformers = SimpleNamespace(
        AutoTokenizer=FakeTokenizer,
        AutoModelForSequenceClassification=FakeModel,
        TrainingArguments=lambda **kwargs: SimpleNamespace(**kwargs),
        Trainer=FakeTrainer,
    )
    monkeypatch.setattr(
        transformer_training.importlib,
        "import_module",
        lambda name: {"torch": fake_torch, "transformers": fake_transformers}[name],
    )
    base_model = tmp_path / "base-xlm-roberta"
    base_model.mkdir()
    (base_model / "config.json").write_text("synthetic base config", encoding="utf-8")
    output = tmp_path / "fine-tuned"

    metadata = fine_tune_transformer(
        dataset,
        split,
        base_model_path=base_model,
        output_dir=output,
        allow_synthetic_demo=True,
    )

    assert metadata["evidence_class"] == "synthetic_demo"
    assert metadata["demo_quality"] is True
    assert metadata["test_metrics"] is None
    assert len(metadata["model_content_sha256"]) == 64
    assert metadata["threshold_selection_split"] == "validation"
    assert 0.0 < metadata["decision_threshold"] < 1.0
    assert set(seen_train) == set(train.messages)
    assert set(seen_validation) == set(validation.messages)
    assert not set(test.messages) & (set(seen_train) | set(seen_validation))
    provenance = (output / "smsd-provenance.json").read_text(encoding="utf-8")
    assert "Synthetic fixture" not in provenance
