"""Feature construction for SMS classification."""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler

# Bump when clean_text/extract_features semantics change; stored in the model
# artifact so an old artifact can be rejected or flagged rather than silently
# mis-fed.
FEATURE_VERSION = "2.0.0"

FEATURE_COLUMNS = [
    "has_url",
    "has_phone",
    "has_money",
    "has_urgency",
    "has_brand",
    "message_length",
    "capital_ratio",
]


def make_feature_transformer() -> ColumnTransformer:
    """Combine unigram/bigram TF-IDF with scaled indicator features.

    ``min_df=1`` and a fixed ``max_features`` capacity keep training
    deterministic; unseen tokens at inference are ignored by the fitted
    vocabulary, as expected.
    """
    return ColumnTransformer(
        [
            (
                "text",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=1,
                    max_features=100_000,
                    sublinear_tf=True,
                    lowercase=True,
                ),
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
    return pd.DataFrame(prepared, columns=["cleaned_text", *FEATURE_COLUMNS])


def make_model(classifier: Any) -> Pipeline:
    """Build the fitted pipeline used by both the baseline and primary model."""
    return Pipeline([("features", make_feature_transformer()), ("classifier", classifier)])


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
    return {
        "feature_version": FEATURE_VERSION,
        "text_column": text_column,
        "numeric_columns": numeric_columns,
    }
