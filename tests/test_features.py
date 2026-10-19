import numpy as np

from src.features import FEATURE_COLUMNS, make_feature_transformer, make_model, messages_to_frame
from sklearn.naive_bayes import MultinomialNB

MESSAGES = [
    "Claim ₱1,000,000 now! Call 09171234567",
    "BDO: account locked, verify http://bit.ly/fake",
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


def test_transformer_output_is_non_negative_for_nb():
    frame = messages_to_frame(MESSAGES)
    transformer = make_feature_transformer()
    transformed = transformer.fit_transform(frame)
    assert transformed.shape[0] == len(MESSAGES)
    # 6 scaled indicator columns appended after the TF-IDF block.
    assert transformed.shape[1] > len(FEATURE_COLUMNS)
    assert np.all(transformed >= 0), "MultinomialNB requires non-negative features"


def test_make_model_end_to_end():
    labels = ["spam", "spam", "ham", "ham"]
    model = make_model(MultinomialNB())
    model.fit(messages_to_frame(MESSAGES), labels)
    assert set(model.predict(messages_to_frame(MESSAGES))) <= {"spam", "ham"}
    assert set(model.classes_) == {"spam", "ham"}
