"""Feature-schema and pipeline consistency tests."""
from __future__ import annotations

import numpy as np
from sklearn.naive_bayes import MultinomialNB

from src.features import (
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    make_feature_transformer,
    make_model,
    messages_to_frame,
    pipeline_feature_signature,
)

MESSAGES = [
    "Claim ₱1,000,000 now! Call 09171234567",
    "BDO: account locked, verify bit.ly/fake",
    "Thanks, see you at lunch tomorrow",
    "Your OTP is 123456. Do not share.",
]


def test_messages_to_frame_schema():
    frame = messages_to_frame(MESSAGES)
    assert list(frame.columns) == ["cleaned_text", *FEATURE_COLUMNS]
    assert len(frame) == len(MESSAGES)
    assert frame["has_url"].tolist() == [0.0, 1.0, 0.0, 0.0]
    assert frame["has_phone"].tolist() == [1.0, 0.0, 0.0, 0.0]
    assert frame["has_money"].tolist() == [1.0, 0.0, 0.0, 0.0]


def test_feature_frame_is_deterministic():
    first = messages_to_frame(MESSAGES)
    second = messages_to_frame(MESSAGES)
    assert first.equals(second)


def test_empty_messages_frame_has_stable_columns():
    frame = messages_to_frame([])
    assert list(frame.columns) == ["cleaned_text", *FEATURE_COLUMNS]
    assert len(frame) == 0


def test_transformer_output_is_non_negative_for_nb():
    frame = messages_to_frame(MESSAGES)
    transformer = make_feature_transformer()
    transformed = transformer.fit_transform(frame)
    assert transformed.shape[0] == len(MESSAGES)
    assert transformed.shape[1] > len(FEATURE_COLUMNS)
    assert np.all(transformed >= 0), "MultinomialNB requires non-negative features"


def test_make_model_end_to_end_and_signature():
    labels = ["spam", "spam", "ham", "ham"]
    model = make_model(MultinomialNB())
    model.fit(messages_to_frame(MESSAGES), labels)
    assert set(model.predict(messages_to_frame(MESSAGES))) <= {"ham", "spam"}
    assert set(model.classes_) == {"ham", "spam"}
    signature = pipeline_feature_signature(model)
    assert signature["text_column"] == "cleaned_text"
    assert signature["numeric_columns"] == FEATURE_COLUMNS
    assert signature["feature_version"] == FEATURE_VERSION


def test_unseen_tokens_are_ignored_at_inference():
    labels = ["spam", "spam", "ham", "ham"]
    model = make_model(MultinomialNB())
    model.fit(messages_to_frame(MESSAGES), labels)
    prediction = model.predict(messages_to_frame(["completely unseen words zzz"]))
    assert prediction[0] in {"ham", "spam"}
