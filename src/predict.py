"""Load a trained model artifact and classify SMS messages.

The artifact is a joblib-serialized mapping (schema v2) containing the fitted
scikit-learn pipeline plus the decision threshold, label mapping, data-source
hashes, training configuration, and version metadata. Legacy bare-pipeline
artifacts are accepted with an explicit warning and a default 0.5 threshold so
an old deployment cannot crash silently.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import sklearn
from sklearn.pipeline import Pipeline

from src.features import FEATURE_COLUMNS, FEATURE_VERSION, messages_to_frame, pipeline_feature_signature
from src.metrics import jsonable
from src.preprocess import MAX_MESSAGE_LENGTH, extract_features, extract_matches

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "spam_detector_v1.pkl"
ARTIFACT_SCHEMA_VERSION = 2
MIN_ARTIFACT_SCHEMA_VERSION = 1
LEGACY_THRESHOLD = 0.5
DEFAULT_CONFIDENCE_MARGIN = 0.10
HIGH_CONFIDENCE_MARGIN = 0.25
FLAG_NAMES = ("has_url", "has_phone", "has_money", "has_urgency")

DEFAULT_DATA_NOTE = (
    "Training provenance is unavailable for this artifact. Results on synthetic Philippine data "
    "are not proof of real-world accuracy. Treat scores as an aid and verify messages through official channels."
)


class ModelArtifactError(RuntimeError):
    """The model file exists but is unreadable, incompatible, or malformed."""


def default_model_path() -> Path:
    """Artifact path, overridable with ``SMSD_MODEL_PATH`` for container deploys.

    In a source checkout this is ``models/spam_detector_v1.pkl`` in the repo. When
    the package is installed (no ``models/`` directory beside it) it falls back
    to ``./models/spam_detector_v1.pkl`` in the current working directory.
    """
    override = os.environ.get("SMSD_MODEL_PATH")
    if override:
        return Path(override)
    if DEFAULT_MODEL.parent.is_dir():
        return DEFAULT_MODEL
    return Path.cwd() / "models" / DEFAULT_MODEL.name


def _format_path(path: Path) -> str:
    return str(path)


@dataclass
class ModelBundle:
    """A fitted pipeline plus the metadata needed to use it safely."""

    pipeline: Any
    threshold: float = LEGACY_THRESHOLD
    suspicious_threshold: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None
    legacy: bool = False

    def __post_init__(self) -> None:
        if not hasattr(self.pipeline, "predict_proba"):
            raise ModelArtifactError("Model artifact does not expose predict_proba; retrain with python -m src.train.")
        classes = list(getattr(self.pipeline, "classes_", []))
        if not {"ham", "spam"}.issubset(set(classes)):
            raise ModelArtifactError(
                f"Model artifact classes are {classes!r}; it must know both 'ham' and 'spam'. Retrain the model."
            )
        try:
            self.threshold = float(self.threshold)
        except (TypeError, ValueError) as exc:
            raise ModelArtifactError(f"Invalid decision threshold stored in artifact: {self.threshold!r}") from exc
        if not 0.0 < self.threshold < 1.0:
            raise ModelArtifactError(f"Decision threshold must be within (0, 1); found {self.threshold!r}.")
        if self.suspicious_threshold is None:
            self.suspicious_threshold = round(max(0.05, self.threshold / 2.0), 4)
        else:
            self.suspicious_threshold = float(self.suspicious_threshold)
            if not 0.0 <= self.suspicious_threshold < self.threshold:
                raise ModelArtifactError(
                    "suspicious_threshold must be >= 0 and below decision_threshold; "
                    f"found {self.suspicious_threshold!r} vs {self.threshold!r}."
                )
        if not isinstance(self.metadata, dict):
            self.metadata = {}

    @property
    def classes(self) -> list[str]:
        return [str(value) for value in getattr(self.pipeline, "classes_", [])]

    @property
    def version(self) -> str:
        value = self.metadata.get("model_version")
        if value:
            return str(value)
        if self.path is not None:
            return self.path.stem
        return "unknown"

    @property
    def bands(self) -> dict[str, float]:
        return {
            "likely_scam": float(self.threshold),
            "suspicious": float(self.suspicious_threshold or 0.0),
            "looks_safe": 0.0,
        }

    @property
    def data_note(self) -> str:
        return str(self.metadata.get("data_note") or DEFAULT_DATA_NOTE)

    def model_info(self) -> dict[str, Any]:
        """JSON-safe artifact metadata for ``GET /model-info`` and docs."""
        warnings = [str(item) for item in self.metadata.get("warnings", [])]
        info = {
            "model_version": self.version,
            "artifact_schema_version": int(
                self.metadata.get("artifact_schema_version", 1 if self.legacy else ARTIFACT_SCHEMA_VERSION)
            ),
            "feature_version": str(self.metadata.get("feature_version", "unknown")),
            "classes": self.classes,
            "decision_threshold": float(self.threshold),
            "suspicious_threshold": float(self.suspicious_threshold or 0.0),
            "bands": self.bands,
            "trained_at": self.metadata.get("created_at") or self.metadata.get("trained_at"),
            "training_data": self.metadata.get("data_sources", []),
            "synthetic_training_data": self.metadata.get("synthetic_training_data"),
            "training_data_kind_counts": self.metadata.get("training_data_kind_counts", {}),
            "probability_calibrated": bool(self.metadata.get("probability_calibrated", False)),
            "data_note": self.data_note,
            "metrics": self.metadata.get("metrics", {}),
            "legacy_artifact": bool(self.legacy),
            "warnings": warnings,
        }
        return jsonable(info)


def _validate_pipeline(pipeline: Any, path: Path) -> None:
    if not isinstance(pipeline, Pipeline):
        raise ModelArtifactError(
            f"Artifact {_format_path(path)} does not contain a scikit-learn Pipeline. Retrain with python -m src.train."
        )
    try:
        signature = pipeline_feature_signature(pipeline)
    except ValueError as exc:
        raise ModelArtifactError(f"Artifact {_format_path(path)} is missing required pipeline steps: {exc}") from exc
    if signature["text_column"] != "cleaned_text":
        raise ModelArtifactError(
            f"Artifact {_format_path(path)} expects text column {signature['text_column']!r}; "
            "this code expects 'cleaned_text'. Retrain the model with the current code."
        )
    if list(signature["numeric_columns"]) != FEATURE_COLUMNS:
        raise ModelArtifactError(
            f"Artifact {_format_path(path)} expects indicator columns {signature['numeric_columns']!r}; "
            f"this code produces {FEATURE_COLUMNS!r}. Retrain the model with the current code."
        )


def _validate_feature_version(feature_version: Any, signature: dict[str, Any], path: Path) -> str | None:
    """Allow the unchanged word-only contract from feature version 2.1.0.

    Version 2.2.0 added selectable char/combined vectorizers; preprocessing and
    word-vectorizer semantics did not change. Accept that prior word-only
    contract only when the fitted pipeline confirms the exact settings.
    """
    if feature_version is None or str(feature_version) == FEATURE_VERSION:
        return None
    expected_word_params = {
        "analyzer": "word",
        "ngram_range": (1, 2),
        "min_df": 1,
        "max_features": 100_000,
        "sublinear_tf": True,
        "lowercase": True,
    }
    if (
        str(feature_version) == "2.1.0"
        and signature.get("text_mode") == "word"
        and signature.get("vectorizer_params") == expected_word_params
    ):
        return (
            "Loaded compatible 2.1.0 word-only features under 2.2.0; preprocessing and word vectorizer settings match."
        )
    raise ModelArtifactError(
        f"Artifact {_format_path(path)} feature_version {feature_version!r} is not compatible with "
        f"this code ({FEATURE_VERSION!r}); retrain the model with the current preprocessing."
    )


def load_model(path: str | Path | None = None) -> ModelBundle:
    """Load and validate an artifact; raises FileNotFoundError or ModelArtifactError."""
    artifact_path = Path(path) if path is not None else default_model_path()
    if not artifact_path.exists():
        raise FileNotFoundError(
            f"Model artifact not found at {artifact_path}. Train it first with: "
            "python -m src.train (or set SMSD_MODEL_PATH to an existing bundle)."
        )
    if artifact_path.is_dir():
        raise ModelArtifactError(f"Model path {artifact_path} is a directory; pass the .pkl bundle file.")
    expected_sha256 = os.environ.get("SMSD_MODEL_SHA256", "").strip().lower()
    model_bytes: bytes | None = None
    if expected_sha256:
        if len(expected_sha256) != 64 or any(character not in "0123456789abcdef" for character in expected_sha256):
            raise ModelArtifactError("SMSD_MODEL_SHA256 must be a 64-character hexadecimal SHA-256 digest.")
        try:
            model_bytes = artifact_path.read_bytes()
        except OSError as exc:
            raise ModelArtifactError(
                f"Could not verify model artifact {artifact_path} ({type(exc).__name__})."
            ) from exc
        if hashlib.sha256(model_bytes).hexdigest() != expected_sha256:
            raise ModelArtifactError(f"Model artifact SHA-256 mismatch for {artifact_path}.")
    try:
        # Deserialize the exact immutable byte sequence whose digest was
        # checked; hashing the path and reopening it would leave a TOCTOU gap.
        artifact = joblib.load(io.BytesIO(model_bytes)) if model_bytes is not None else joblib.load(artifact_path)
    except Exception as exc:  # joblib/pickle can raise many exception types
        raise ModelArtifactError(
            f"Could not read model artifact {artifact_path} ({type(exc).__name__}: {exc}). "
            "The file may be corrupt or incompatible; retrain with python -m src.train."
        ) from exc

    if isinstance(artifact, dict):
        schema_version = artifact.get("artifact_schema_version", artifact.get("schema_version"))
        if schema_version is None:
            raise ModelArtifactError(
                f"Artifact {artifact_path} is a mapping without artifact_schema_version. Retrain with the current code."
            )
        try:
            schema_version = int(schema_version)
        except (TypeError, ValueError) as exc:
            raise ModelArtifactError(f"Invalid artifact_schema_version in {artifact_path}: {schema_version!r}") from exc
        if schema_version < MIN_ARTIFACT_SCHEMA_VERSION:
            raise ModelArtifactError(f"Artifact schema {schema_version} is too old; retrain with python -m src.train.")
        if schema_version > ARTIFACT_SCHEMA_VERSION:
            raise ModelArtifactError(
                f"Artifact schema {schema_version} is newer than this code supports ({ARTIFACT_SCHEMA_VERSION}). "
                "Upgrade the application or retrain the artifact."
            )
        pipeline = artifact.get("model") if "model" in artifact else artifact.get("pipeline")
        if pipeline is None:
            raise ModelArtifactError(f"Artifact {artifact_path} has no model/pipeline entry. Retrain the model.")
        metadata = {key: value for key, value in artifact.items() if key not in {"model", "pipeline"}}
        feature_version = metadata.get("feature_version")
        threshold = artifact.get("threshold", artifact.get("decision_threshold", LEGACY_THRESHOLD))
        if threshold is None:
            threshold = LEGACY_THRESHOLD
        suspicious = artifact.get("suspicious_threshold")
        warnings = metadata.setdefault("warnings", [])
        if isinstance(warnings, list):
            artifact_sklearn = metadata.get("sklearn_version")
            if artifact_sklearn and str(artifact_sklearn) != sklearn.__version__:
                warnings.append(
                    f"Artifact was trained with scikit-learn {artifact_sklearn}; running {sklearn.__version__}. "
                    "Verify predictions after any dependency upgrade."
                )
        _validate_pipeline(pipeline, artifact_path)
        signature = pipeline_feature_signature(pipeline)
        compatibility_warning = _validate_feature_version(feature_version, signature, artifact_path)
        if compatibility_warning:
            warnings = metadata.setdefault("warnings", [])
            if isinstance(warnings, list):
                warnings.append(compatibility_warning)
        return ModelBundle(
            pipeline=pipeline,
            threshold=float(threshold),
            suspicious_threshold=suspicious,
            metadata=metadata,
            path=artifact_path,
            legacy=False,
        )

    if hasattr(artifact, "predict_proba"):
        # Backward compatibility: a bare pipeline has no threshold/metadata.
        _validate_pipeline(artifact, artifact_path)
        return ModelBundle(
            pipeline=artifact,
            threshold=LEGACY_THRESHOLD,
            suspicious_threshold=round(LEGACY_THRESHOLD / 2.0, 4),
            metadata={
                "artifact_schema_version": 1,
                "model_version": artifact_path.stem,
                "data_sources": [],
                "synthetic_training_data": None,
                "warnings": [
                    "Legacy artifact without threshold/metadata; using a 0.5 threshold. "
                    "Retrain with python -m src.train to record data provenance and a tuned threshold."
                ],
            },
            path=artifact_path,
            legacy=True,
        )

    raise ModelArtifactError(
        f"Artifact {artifact_path} contains an unsupported object ({type(artifact).__name__}). "
        "Retrain with python -m src.train."
    )


def _coerce_bundle(model: Any, model_path: str | Path | None = None) -> ModelBundle:
    if isinstance(model, ModelBundle):
        return model
    if model is None:
        return load_model(model_path)
    if hasattr(model, "predict_proba"):
        # Test helpers and legacy callers may pass a bare fitted pipeline.
        _validate_pipeline(model, Path(model_path) if model_path is not None else Path("<in-memory>"))
        return ModelBundle(
            pipeline=model,
            threshold=LEGACY_THRESHOLD,
            metadata={"model_version": "in-memory", "warnings": ["In-memory pipeline; no artifact metadata."]},
            legacy=True,
        )
    raise ModelArtifactError(f"Unsupported model object: {type(model).__name__}")


def _validate_messages(messages: Iterable[str], *, allow_empty: bool = False) -> list[str]:
    if isinstance(messages, (str, bytes)):
        raise ValueError("messages must be a list of strings, not a single string")
    try:
        result = list(messages)
    except TypeError as exc:
        raise ValueError("messages must be an iterable of strings") from exc
    if not result and not allow_empty:
        raise ValueError("At least one message is required")
    for position, message in enumerate(result):
        if not isinstance(message, str):
            raise ValueError(f"Message {position} must be a string; received {type(message).__name__}")
        if not message.strip():
            raise ValueError(f"Message {position} is blank; messages must contain visible text")
        if len(message) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message {position} is {len(message)} characters; the maximum is {MAX_MESSAGE_LENGTH}")
    return result


def spam_probabilities(bundle: ModelBundle, messages: Iterable[str]) -> list[float]:
    """P(spam) for each message using exactly one vectorized predict_proba call."""
    messages = _validate_messages(messages, allow_empty=True)
    if not messages:
        return []
    frame = messages_to_frame(messages)
    probabilities = bundle.pipeline.predict_proba(frame)
    classes = list(bundle.pipeline.classes_)
    spam_index = classes.index("spam")
    return [float(row[spam_index]) for row in probabilities]


def decision_probability(bundle: ModelBundle, message: str) -> float:
    return spam_probabilities(bundle, [message])[0]


def risk_band(spam_probability: float, bundle: ModelBundle) -> str:
    if spam_probability >= bundle.threshold:
        return "likely_scam"
    if spam_probability >= (bundle.suspicious_threshold or 0.0):
        return "suspicious"
    return "looks_safe"


def confidence_label(spam_probability: float, bundle: ModelBundle) -> str:
    """Confidence in the *decision*, based on distance from the threshold.

    This is deliberately not presented as calibrated probability: with a tuned
    threshold, a 0.75 spam probability is still a confident 'ham' when the
    threshold is 0.80. The margin makes that explicit.
    """
    margin = abs(spam_probability - bundle.threshold)
    if margin >= HIGH_CONFIDENCE_MARGIN:
        return "high"
    if margin >= DEFAULT_CONFIDENCE_MARGIN:
        return "medium"
    return "low"


def _score_message(message: str, spam_probability: float, bundle: ModelBundle) -> dict[str, Any]:
    prediction = "spam" if spam_probability >= bundle.threshold else "ham"
    indicators = extract_features(message)
    flags = [name for name in FLAG_NAMES if indicators[name]]
    matches = extract_matches(message)
    brands: list[str] = []
    for match in matches:
        if match["type"] == "brand":
            brand = match["text"].lower()
            if brand not in brands:
                brands.append(brand)
    return {
        "message": message,
        "prediction": prediction,
        "spam_probability": float(spam_probability),
        "probability_calibrated": bool(bundle.metadata.get("probability_calibrated", False)),
        "probability": float(spam_probability if prediction == "spam" else 1.0 - spam_probability),
        "decision_threshold": float(bundle.threshold),
        "margin": float(abs(spam_probability - bundle.threshold)),
        "confidence": confidence_label(spam_probability, bundle),
        "risk_band": risk_band(spam_probability, bundle),
        "flags": flags,
        "matches": matches,
        "brands": brands,
        "model_version": bundle.version,
    }


def analyze_messages(
    messages: Iterable[str],
    model: Any = None,
    model_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Analyze several messages; one vectorized prediction call for the batch."""
    bundle = _coerce_bundle(model, model_path)
    validated = _validate_messages(messages)
    probabilities = spam_probabilities(bundle, validated)
    return [_score_message(message, probability, bundle) for message, probability in zip(validated, probabilities)]


def analyze_message(message: str, model: Any = None, model_path: str | Path | None = None) -> dict[str, Any]:
    """Full analysis for the web UI: verdict, probability, signal spans, brands."""
    return analyze_messages([message], model=model, model_path=model_path)[0]


def analyze_batch(
    messages: Iterable[str], model: Any = None, model_path: str | Path | None = None
) -> list[dict[str, Any]]:
    return analyze_messages(messages, model=model, model_path=model_path)


def predict_message(message: str, model: Any = None, model_path: str | Path | None = None) -> dict[str, Any]:
    """Minimal backward-compatible contract: prediction, probability, flags."""
    analysis = analyze_message(message, model=model, model_path=model_path)
    return {key: analysis[key] for key in ("prediction", "probability", "flags")}


def model_info(model: Any = None, model_path: str | Path | None = None) -> dict[str, Any]:
    return _coerce_bundle(model, model_path).model_info()


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify one SMS message")
    parser.add_argument("message", help="SMS text to analyze")
    parser.add_argument(
        "--model",
        default=None,
        help="Path to the joblib artifact (default: SMSD_MODEL_PATH or models/spam_detector_v1.pkl)",
    )
    parser.add_argument("--minimal", action="store_true", help="Print only prediction/probability/flags")
    args = parser.parse_args(argv)
    try:
        result = (
            predict_message(args.message, model_path=args.model)
            if args.minimal
            else analyze_message(args.message, model_path=args.model)
        )
    except (FileNotFoundError, ModelArtifactError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(jsonable(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
