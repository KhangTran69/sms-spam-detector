"""Feature construction for SMS classification."""
from __future__ import annotations

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler

FEATURE_COLUMNS = ["has_url", "has_phone", "has_money", "has_urgency", "has_brand", "message_length", "capital_ratio"]


def make_feature_transformer() -> ColumnTransformer:
    """Combine unigram/bigram TF-IDF with scaled indicator features."""
    return ColumnTransformer(
        [
            ("text", TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=100_000, sublinear_tf=True), "cleaned_text"),
            # MultinomialNB requires non-negative inputs, so scale indicators into [0, 1].
            ("numeric", MinMaxScaler(), FEATURE_COLUMNS),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def messages_to_frame(messages: list[str]) -> pd.DataFrame:
    """Prepare raw messages into the stable feature schema."""
    from src.preprocess import prepare_message
    return pd.DataFrame([prepare_message(message) for message in messages], columns=["cleaned_text", *FEATURE_COLUMNS])


def make_model(classifier) -> Pipeline:
    return Pipeline([("features", make_feature_transformer()), ("classifier", classifier)])
