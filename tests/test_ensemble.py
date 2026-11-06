from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ensemble import ConfidenceBandRouter, TransformerModelError
from src.predict import ModelBundle, analyze_message


def _directory_digest(directory: Path, *, excluded_paths: tuple[str, ...] = ()) -> str:
    digest = hashlib.sha256()
    excluded = set(excluded_paths)
    for path in sorted(file for file in directory.rglob("*") if file.is_file()):
        relative_path = path.relative_to(directory).as_posix()
        if relative_path in excluded:
            continue
        relative = relative_path.encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_outside_confidence_band_does_not_load_transformer(tmp_path):
    loads: list[Path] = []

    def loader(path: Path):
        loads.append(path)
        raise AssertionError("transformer loader must stay lazy outside the confidence band")

    model_path = tmp_path / "not-loaded"
    router = ConfidenceBandRouter(model_path, confidence_band=0.05, model_loader=loader)

    probabilities, routed_indices = router.route(["synthetic example"], [0.9], threshold=0.5)

    assert router.model_path == model_path
    assert probabilities == [0.9]
    assert routed_indices == set()
    assert loads == []


def test_router_lazily_loads_once_and_only_scores_uncertain_messages(tmp_path):
    loaded_paths: list[Path] = []
    scored_batches: list[list[str]] = []

    def loader(path: Path):
        loaded_paths.append(path)

        def scorer(messages: list[str]) -> list[float]:
            scored_batches.append(messages)
            return [0.91 for _ in messages]

        return scorer

    model_path = tmp_path / "synthetic-transformer"
    router = ConfidenceBandRouter(model_path, confidence_band=0.05, model_loader=loader)

    probabilities, routed_indices = router.route(
        ["outside one", "inside one", "outside two"],
        [0.1, 0.52, 0.95],
        threshold=0.5,
    )
    second_probabilities, second_indices = router.route(["inside two"], [0.49], threshold=0.5)

    assert probabilities == [0.1, 0.91, 0.95]
    assert routed_indices == {1}
    assert second_probabilities == [0.91]
    assert second_indices == {0}
    assert loaded_paths == [model_path]
    assert scored_batches == [["inside one"], ["inside two"]]


def test_router_rejects_invalid_transformer_scores(tmp_path):
    router = ConfidenceBandRouter(
        tmp_path / "synthetic-transformer",
        model_loader=lambda _path: lambda _messages: [float("nan")],
    )

    with pytest.raises(TransformerModelError, match="finite spam scores"):
        router.route(["synthetic uncertain"], [0.5], threshold=0.5)


def test_missing_local_model_directory_fails_before_optional_import(monkeypatch, tmp_path):
    from src import ensemble

    imports: list[str] = []

    def record_import(name: str):
        imports.append(name)
        raise AssertionError("optional dependency import must follow local artifact validation")

    monkeypatch.setattr(ensemble.importlib, "import_module", record_import)

    with pytest.raises(TransformerModelError, match="existing local model directory"):
        ensemble.load_local_transformer_scorer(tmp_path / "missing")

    assert imports == []


def test_local_loader_requires_validation_threshold_before_optional_import(monkeypatch, tmp_path):
    from src import ensemble

    model_path = tmp_path / "synthetic-checkpoint"
    model_path.mkdir()
    imports: list[str] = []

    def record_import(name: str):
        imports.append(name)
        raise AssertionError("optional dependencies must not load without threshold provenance")

    monkeypatch.setattr(ensemble.importlib, "import_module", record_import)
    with pytest.raises(TransformerModelError, match="validation-selected decision threshold"):
        ensemble.load_local_transformer_scorer(model_path)

    assert imports == []


def test_local_loader_rejects_multiclass_checkpoint(tmp_path, monkeypatch):
    from src import ensemble

    model_path = tmp_path / "synthetic-multiclass"
    model_path.mkdir()
    (model_path / "config.json").write_text("synthetic multiclass config", encoding="utf-8")
    (model_path / "model.safetensors").write_bytes(b"synthetic multiclass weights")
    (model_path / "smsd-provenance.json").write_text(
        json.dumps(
            {
                "decision_threshold": 0.65,
                "model_content_sha256": _directory_digest(model_path),
                "threshold_selection_split": "validation",
                "split_method": "stratified_group_kfold",
                "split_group_leakage": 0,
            }
        ),
        encoding="utf-8",
    )

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, _path, **_kwargs):
            return cls()

    class FakeModel:
        config = SimpleNamespace(
            model_type="xlm-roberta",
            id2label={0: "ham", 1: "spam", 2: "other"},
            num_labels=3,
        )

        @classmethod
        def from_pretrained(cls, _path, **_kwargs):
            return cls()

    fake_transformers = SimpleNamespace(AutoTokenizer=FakeTokenizer, AutoModelForSequenceClassification=FakeModel)
    monkeypatch.setattr(
        ensemble.importlib,
        "import_module",
        lambda name: SimpleNamespace() if name == "torch" else fake_transformers,
    )

    with pytest.raises(TransformerModelError, match="exactly two labels"):
        ensemble.load_local_transformer_scorer(model_path)


def test_local_loader_rejects_inconsistent_label_maps(tmp_path, monkeypatch):
    from src import ensemble

    model_path = tmp_path / "synthetic-inconsistent-label-map"
    model_path.mkdir()
    (model_path / "config.json").write_text("synthetic binary config", encoding="utf-8")
    (model_path / "model.safetensors").write_bytes(b"synthetic binary weights")
    (model_path / "smsd-provenance.json").write_text(
        json.dumps(
            {
                "decision_threshold": 0.65,
                "model_content_sha256": _directory_digest(model_path),
                "threshold_selection_split": "validation",
                "split_method": "stratified_group_kfold",
                "split_group_leakage": 0,
            }
        ),
        encoding="utf-8",
    )

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, _path, **_kwargs):
            return cls()

    class FakeModel:
        config = SimpleNamespace(
            model_type="xlm-roberta",
            id2label={0: "ham", 1: "spam"},
            label2id={"ham": 1, "spam": 0},
            num_labels=2,
        )

        @classmethod
        def from_pretrained(cls, _path, **_kwargs):
            return cls()

        def eval(self):
            return None

        def to(self, _device):
            return None

    fake_transformers = SimpleNamespace(AutoTokenizer=FakeTokenizer, AutoModelForSequenceClassification=FakeModel)
    monkeypatch.setattr(
        ensemble.importlib,
        "import_module",
        lambda name: SimpleNamespace() if name == "torch" else fake_transformers,
    )

    with pytest.raises(TransformerModelError, match="label mappings must agree"):
        ensemble.load_local_transformer_scorer(model_path)


def test_local_loader_uses_only_local_xlm_roberta_checkpoint(monkeypatch, tmp_path):
    from src import ensemble

    calls: list[tuple[str, object]] = []

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls.append(("tokenizer", kwargs))
            assert Path(path) == tmp_path / "model"
            return cls()

        def __call__(self, messages, **kwargs):
            calls.append(("messages", list(messages)))
            return {"input_ids": "synthetic-token-fixture"}

    class FakeModel:
        config = SimpleNamespace(
            model_type="xlm-roberta",
            id2label={0: "ham", 1: "spam"},
            label2id={"ham": 0, "spam": 1},
            num_labels=2,
        )

        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls.append(("model", kwargs))
            assert Path(path) == tmp_path / "model"
            return cls()

        def eval(self):
            calls.append(("eval", True))

        def to(self, device):
            calls.append(("device", device))

        def __call__(self, **_kwargs):
            return SimpleNamespace(logits="synthetic-logits")

    class FakeProbabilities:
        def __getitem__(self, index):
            assert index == (slice(None), 1)
            return SimpleNamespace(tolist=lambda: [0.83, 0.16])

    fake_torch = SimpleNamespace(
        inference_mode=nullcontext,
        softmax=lambda _logits, dim: FakeProbabilities(),
    )
    fake_transformers = SimpleNamespace(AutoTokenizer=FakeTokenizer, AutoModelForSequenceClassification=FakeModel)
    monkeypatch.setattr(
        ensemble.importlib,
        "import_module",
        lambda name: {"torch": fake_torch, "transformers": fake_transformers}[name],
    )
    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "config.json").write_text("synthetic model config", encoding="utf-8")
    (model_path / "model.safetensors").write_bytes(b"synthetic model weights")
    (model_path / "smsd-provenance.json").write_text(
        json.dumps(
            {
                "decision_threshold": 0.65,
                "model_content_sha256": _directory_digest(model_path),
                "threshold_selection_split": "validation",
                "split_method": "stratified_group_kfold",
                "split_group_leakage": 0,
            }
        ),
        encoding="utf-8",
    )

    scorer = ensemble.load_local_transformer_scorer(model_path)
    scores = scorer(["Synthetic first", "Synthetic second"])

    assert scores == [0.83, 0.16]
    assert scorer.decision_threshold == pytest.approx(0.65)
    assert scorer.model_version == (
        f"transformer-{_directory_digest(model_path, excluded_paths=('smsd-provenance.json',))[:12]}"
    )
    assert calls[0][1] == {"local_files_only": True, "use_fast": True}
    assert calls[1][1] == {"local_files_only": True, "use_safetensors": True}
    assert ("device", "cpu") in calls
    assert ("messages", ["Synthetic first", "Synthetic second"]) in calls


def test_analysis_marks_only_transformer_routed_results_uncalibrated(monkeypatch, tmp_path):
    class FixedPipeline:
        classes_ = ["ham", "spam"]

        def predict_proba(self, frame):
            return [[0.48, 0.52] for _ in range(len(frame))]

    bundle = ModelBundle(
        pipeline=FixedPipeline(),
        threshold=0.5,
        metadata={"model_version": "synthetic-router-fixture", "probability_calibrated": True},
    )

    def loader(_path):
        def scorer(messages):
            return [0.6 for _ in messages]

        scorer.model_version = "transformer-a1b2c3d4e5f6"
        return scorer

    router = ConfidenceBandRouter(
        tmp_path / "synthetic-checkpoint",
        confidence_band=0.05,
        model_loader=loader,
        decision_threshold=0.7,
    )
    monkeypatch.setattr("src.predict._confidence_router", lambda _path, _band: router)

    result = analyze_message(
        "Synthetic fixture https://example.test/route",
        model=bundle,
        transformer_model_path=tmp_path / "synthetic-checkpoint",
        confidence_band=0.05,
    )

    assert result["prediction"] == "ham"
    assert result["spam_probability"] == pytest.approx(0.6)
    assert result["probability_calibrated"] is False
    assert result["model_path"] == "ensemble"
    assert result["model_version"] == "transformer-a1b2c3d4e5f6"
    assert result["decision_threshold"] == pytest.approx(0.7)


def test_local_loader_rejects_model_content_hash_mismatch_before_optional_import(monkeypatch, tmp_path):
    from src import ensemble

    model_path = tmp_path / "synthetic-tampered-checkpoint"
    model_path.mkdir()
    (model_path / "config.json").write_text("synthetic model config", encoding="utf-8")
    (model_path / "smsd-provenance.json").write_text(
        json.dumps(
            {
                "decision_threshold": 0.65,
                "model_content_sha256": "0" * 64,
                "threshold_selection_split": "validation",
                "split_method": "stratified_group_kfold",
                "split_group_leakage": 0,
            }
        ),
        encoding="utf-8",
    )
    imports: list[str] = []

    def record_import(name: str):
        imports.append(name)
        raise AssertionError("optional dependencies must not load for a mismatched checkpoint")

    monkeypatch.setattr(ensemble.importlib, "import_module", record_import)

    with pytest.raises(TransformerModelError, match="content hash mismatch"):
        ensemble.load_local_transformer_scorer(model_path)

    assert imports == []


def test_uncalibrated_linear_bundle_never_uses_confidence_band(monkeypatch, tmp_path):
    class FixedPipeline:
        classes_ = ["ham", "spam"]

        def predict_proba(self, frame):
            return [[0.48, 0.52] for _ in range(len(frame))]

    bundle = ModelBundle(
        pipeline=FixedPipeline(),
        threshold=0.5,
        metadata={"model_version": "synthetic-uncalibrated-fixture", "probability_calibrated": False},
    )

    def should_not_route(_path, _band):
        raise AssertionError("uncalibrated linear scores must not enter a confidence-band router")

    monkeypatch.setattr("src.predict._confidence_router", should_not_route)
    result = analyze_message(
        "Synthetic fixture https://example.test/linear",
        model=bundle,
        transformer_model_path=tmp_path / "synthetic-checkpoint",
    )

    assert result["model_path"] == "linear"
    assert result["probability_calibrated"] is False
