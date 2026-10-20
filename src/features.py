"""Feature construction for SMS classification."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import MinMaxScaler

# Bump when clean_text/extract_features semantics change; stored in the model
# artifact so an old artifact can be rejected or flagged rather than silently
# mis-fed.
FEATURE_VERSION = "2.2.0"
TEXT_FEATURE_MODES = ("word", "char", "combined")

FEATURE_COLUMNS = [
    "has_url",
    "has_phone",
    "has_money",
    "has_urgency",
    "has_brand",
    "message_length",
    "capital_ratio",
]


def _text_vectorizer(mode: str) -> TfidfVectorizer | FeatureUnion:
    if mode == "word":
        return TfidfVectorizer(
            ngram_range=(1, 2), min_df=1, max_features=100_000, sublinear_tf=True, lowercase=True, dtype=np.float32
        )
    if mode == "char":
        return TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=1,
            max_features=100_000,
            sublinear_tf=True,
            lowercase=True,
            dtype=np.float32,
        )
    if mode == "combined":
        return FeatureUnion(
            [
                ("word", _text_vectorizer("word")),
                ("char", _text_vectorizer("char")),
            ]
        )
    raise ValueError(f"text feature mode must be one of {TEXT_FEATURE_MODES}, got {mode!r}")


def make_feature_transformer(text_features: str = "word") -> ColumnTransformer:
    """Combine the selected TF-IDF representation with scaled indicator features.

    ``min_df=1`` and a fixed ``max_features`` capacity keep training
    deterministic; unseen tokens at inference are ignored by the fitted
    vocabulary, as expected.
    """
    return ColumnTransformer(
        [
            (
                "text",
                _text_vectorizer(text_features),
                "cleaned_text",
            ),
            # MultinomialNB requires non-negative inputs, so scale indicators into [0, 1].
            ("numeric", MinMaxScaler(), FEATURE_COLUMNS),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def messages_to_frame(messages: Iterable[str]) -> pd.DataFrame:
    """Prepare raw messages into the stable feature schema.

    Training, the CLI, and the API all call this function, which is what keeps
    normalization consistent between them.
    """
    from src.preprocess import prepare_messages

    prepared = prepare_messages(messages)
    frame = pd.DataFrame(prepared, columns=["cleaned_text", *FEATURE_COLUMNS])
    frame[FEATURE_COLUMNS] = frame[FEATURE_COLUMNS].astype(np.float32)
    return frame


def make_model(classifier: Any, *, text_features: str = "word") -> Pipeline:
    """Build the fitted pipeline used by both the baseline and primary model."""
    return Pipeline([("features", make_feature_transformer(text_features)), ("classifier", classifier)])


def pipeline_feature_signature(pipeline: Pipeline) -> dict[str, Any]:
    """Describe the input schema expected by a fitted pipeline.

    Used when loading an artifact so an incompatible feature schema fails with
    an actionable message instead of a confusing scikit-learn error.
    """
    try:
        transformer = pipeline.named_steps["features"]
    except (AttributeError, KeyError) as exc:
        raise ValueError("pipeline is missing the 'features' step") from exc
    text_column = None
    numeric_columns: list[str] = []
    for name, _, columns in transformer.transformers:
        if name == "text":
            text_column = columns
        elif name == "numeric":
            numeric_columns = list(columns)
    text_transformer = (
        transformer.named_transformers_.get("text") if hasattr(transformer, "named_transformers_") else None
    )
    if text_transformer is None:
        text_transformer = next((item for name, item, _ in transformer.transformers if name == "text"), None)
    if isinstance(text_transformer, FeatureUnion):
        text_mode = "combined"
        vectorizer_params = None
    elif isinstance(text_transformer, TfidfVectorizer):
        text_mode = "word" if text_transformer.analyzer == "word" else "char"
        vectorizer_params = text_transformer.get_params(deep=False)
        # Runtime object metadata can include callables/types; retain only
        # settings needed to validate the stable word feature contract.
        vectorizer_params = {
            key: vectorizer_params[key]
            for key in ("analyzer", "ngram_range", "min_df", "max_features", "sublinear_tf", "lowercase")
        }
    else:
        text_mode = "unknown"
        vectorizer_params = None
    return {
        "feature_version": FEATURE_VERSION,
        "text_column": text_column,
        "numeric_columns": numeric_columns,
        "text_mode": text_mode,
        "vectorizer_params": vectorizer_params,
    }
