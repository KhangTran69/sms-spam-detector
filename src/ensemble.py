"""Optional local transformer routing for uncertain linear-model scores.

This module intentionally imports no transformer framework at module import
time. The default application and training paths therefore stay lightweight.
"""

from __future__ import annotations

import hmac
import importlib
import json
import math
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from src.artifact_integrity import ArtifactIntegrityError, directory_sha256

DEFAULT_CONFIDENCE_BAND = 0.10


class TransformerModelError(RuntimeError):
    """A configured local transformer cannot be loaded or used safely."""


Scorer = Callable[[list[str]], list[float]]
ModelLoader = Callable[[Path], Scorer]


def _validated_scores(scores: Sequence[float], *, expected: int) -> list[float]:
    if len(scores) != expected:
        raise TransformerModelError("The transformer returned an unexpected number of spam scores.")
    result: list[float] = []
    for value in scores:
        try:
            score = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise TransformerModelError("The transformer must return finite spam scores between 0 and 1.") from exc
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise TransformerModelError("The transformer must return finite spam scores between 0 and 1.")
        result.append(score)
    return result


class ConfidenceBandRouter:
    """Route only scores inside a threshold-centered band to a local model."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        confidence_band: float = DEFAULT_CONFIDENCE_BAND,
        model_loader: ModelLoader | None = None,
        decision_threshold: float | None = None,
    ) -> None:
        try:
            band = float(confidence_band)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence_band must be a finite value in [0, 0.5].") from exc
        if not math.isfinite(band) or not 0.0 <= band <= 0.5:
            raise ValueError("confidence_band must be a finite value in [0, 0.5].")
        self.model_path = Path(model_path)
        self.confidence_band = band
        self._model_loader = model_loader or load_local_transformer_scorer
        self._scorer: Scorer | None = None
        self._decision_threshold = (
            _validate_decision_threshold(decision_threshold) if decision_threshold is not None else None
        )
        self._lock = threading.Lock()

    @property
    def decision_threshold(self) -> float | None:
        if self._decision_threshold is not None:
            return self._decision_threshold
        if self._scorer is None:
            return None
        value = getattr(self._scorer, "decision_threshold", None)
        self._decision_threshold = _validate_decision_threshold(value) if value is not None else None
        return self._decision_threshold

    @property
    def model_version(self) -> str | None:
        if self._scorer is None:
            return None
        value = getattr(self._scorer, "model_version", None)
        return str(value) if value else None

    def _get_scorer(self) -> Scorer:
        if self._scorer is None:
            with self._lock:
                if self._scorer is None:
                    self._scorer = self._model_loader(self.model_path)
        return self._scorer

    def route(
        self,
        messages: Sequence[str],
        spam_probabilities: Sequence[float],
        *,
        threshold: float,
    ) -> tuple[list[float], set[int]]:
        if len(messages) != len(spam_probabilities):
            raise ValueError("messages and spam_probabilities must have the same length.")
        try:
            cutoff = float(threshold)
        except (TypeError, ValueError) as exc:
            raise ValueError("threshold must be finite and within (0, 1).") from exc
        if not math.isfinite(cutoff) or not 0.0 < cutoff < 1.0:
            raise ValueError("threshold must be finite and within (0, 1).")
        linear_scores = _validated_scores(spam_probabilities, expected=len(messages))
        routed = {index for index, score in enumerate(linear_scores) if abs(score - cutoff) < self.confidence_band}
        if not routed:
            return linear_scores, set()

        indices = sorted(routed)
        transformer_scores = _validated_scores(
            self._get_scorer()([messages[index] for index in indices]), expected=len(indices)
        )
        result = list(linear_scores)
        for index, score in zip(indices, transformer_scores):
            result[index] = score
        return result, routed


def load_local_transformer_scorer(model_path: Path) -> Scorer:
    """Load a CPU classifier from an existing directory without network access."""
    if not model_path.exists() or not model_path.is_dir():
        raise TransformerModelError("Transformer model path must point to an existing local model directory.")

    metadata_path = model_path / "smsd-provenance.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransformerModelError(
            "Transformer model needs a readable smsd-provenance.json with a validation-selected decision threshold."
        ) from exc
    if not isinstance(metadata, dict):
        raise TransformerModelError("Transformer provenance must contain a decision-threshold object.")
    if metadata.get("threshold_selection_split") != "validation":
        raise TransformerModelError("Transformer decision threshold must be selected on validation data only.")
    if metadata.get("split_method") not in {"stratified_group_kfold", "chronological_group_holdout"}:
        raise TransformerModelError("Transformer provenance must identify a group-aware split.")
    if metadata.get("split_group_leakage") != 0:
        raise TransformerModelError("Transformer provenance reports group leakage and cannot be served.")
    try:
        decision_threshold = _validate_decision_threshold(metadata.get("decision_threshold"))
    except TransformerModelError as exc:
        raise TransformerModelError(
            "Transformer provenance needs a validation-selected decision threshold in (0, 1)."
        ) from exc
    expected_model_hash = metadata.get("model_content_sha256")
    if (
        not isinstance(expected_model_hash, str)
        or len(expected_model_hash) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in expected_model_hash)
    ):
        raise TransformerModelError("Transformer provenance needs the model-content SHA-256.")
    try:
        actual_model_hash = directory_sha256(model_path, excluded_paths=("smsd-provenance.json",))
    except (ArtifactIntegrityError, OSError) as exc:
        raise TransformerModelError("The local transformer checkpoint could not be verified.") from exc
    if not hmac.compare_digest(expected_model_hash.lower(), actual_model_hash):
        raise TransformerModelError("Transformer model-content hash mismatch; refusing to load the checkpoint.")

    try:
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
    except ImportError as exc:
        raise TransformerModelError(
            "Transformer support is not installed. Install the optional 'transform' extra."
        ) from exc

    try:
        tokenizer = transformers.AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, use_fast=True)
        model = transformers.AutoModelForSequenceClassification.from_pretrained(
            str(model_path), local_files_only=True, use_safetensors=True
        )
        if getattr(model.config, "model_type", None) != "xlm-roberta":
            raise TransformerModelError("The configured local checkpoint must use the XLM-RoBERTa model family.")
        id_to_label = getattr(model.config, "id2label", {}) or {}
        declared_label_to_id = getattr(model.config, "label2id", {}) or {}
        num_labels = int(getattr(model.config, "num_labels", len(id_to_label)))
        if not isinstance(id_to_label, Mapping) or not isinstance(declared_label_to_id, Mapping):
            raise TransformerModelError("Transformer model must declare exactly two labels: ham and spam.")
        try:
            normalized_id_to_label = {int(index): str(label).strip().casefold() for index, label in id_to_label.items()}
            label_to_id = {str(label).strip().casefold(): int(index) for label, index in declared_label_to_id.items()}
        except (TypeError, ValueError, OverflowError) as exc:
            raise TransformerModelError("Transformer model label mappings are invalid.") from exc
        if (
            num_labels != 2
            or set(normalized_id_to_label) != {0, 1}
            or set(normalized_id_to_label.values()) != {"ham", "spam"}
            or set(label_to_id) != {"ham", "spam"}
            or any(index < 0 or index >= num_labels for index in label_to_id.values())
        ):
            raise TransformerModelError("Transformer model must declare exactly two labels: ham and spam.")
        expected_label_to_id = {label: index for index, label in normalized_id_to_label.items()}
        if label_to_id != expected_label_to_id:
            raise TransformerModelError("Transformer model label mappings must agree on ham and spam indices.")
        model.eval()
        model.to("cpu")
    except TransformerModelError:
        raise
    except Exception as exc:
        raise TransformerModelError(
            f"The local transformer could not be loaded ({type(exc).__name__}). Check the model directory and weights."
        ) from exc

    spam_index = label_to_id["spam"]

    class LocalScorer:
        def __init__(self, selected_threshold: float) -> None:
            self.decision_threshold = selected_threshold
            self.model_version = f"transformer-{actual_model_hash[:12]}"

        def __call__(self, messages: list[str]) -> list[float]:
            try:
                encoded = tokenizer(
                    messages,
                    truncation=True,
                    max_length=256,
                    padding=True,
                    return_tensors="pt",
                )
                with torch.inference_mode():
                    logits = model(**encoded).logits
                    probabilities = torch.softmax(logits, dim=-1)[:, spam_index]
                return [float(value) for value in probabilities.tolist()]
            except Exception as exc:
                raise TransformerModelError(f"The local transformer analysis failed ({type(exc).__name__}).") from exc

    return LocalScorer(decision_threshold)


def _validate_decision_threshold(value: Any) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TransformerModelError("Transformer decision threshold must be finite and within (0, 1).") from exc
    if not math.isfinite(threshold) or not 0.0 < threshold < 1.0:
        raise TransformerModelError("Transformer decision threshold must be finite and within (0, 1).")
    return threshold
