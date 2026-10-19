"""Train/persist/load round-trip on a small synthetic dataset (no repo data needed)."""
import pytest

from src.predict import load_model, predict_message
from src.train import train

SPAM = [
    "Congratulations! You won a free prize. Claim now! Call 09171234567",
    "Free entry to win ₱100,000 cash. Text CLAIM to 09175551234 now!",
    "Winner! Claim your free prize money now, limited offer!",
    "You have won a brand new phone. Claim your free prize now!",
    "₱50,000 cash prize waiting. Text WIN to 09175551234 agad!",
    "Claim your free ₱1M prize now! Winner winner!",
    "Free gift for you! Claim your prize now, limited slots only.",
    "Congrats winner! Claim free cash prize now. Call 09171234567",
]
HAM = [
    "Thanks, see you at lunch tomorrow",
    "Ok po, salamat. See you at the meeting",
    "Don't forget the meeting at 3pm",
    "Salamat sa tulong mo kahapon",
    "See you Sunday, bring the report",
    "Ok lang ako, salamat po sa tanong",
    "Lunch at the usual place tomorrow?",
    "Meeting moved to Friday, salamat",
]


@pytest.fixture(scope="module")
def trained_model_path(tmp_path_factory):
    data_path = tmp_path_factory.mktemp("data") / "tiny.csv"
    lines = ["label,message"]
    lines += [f'spam,"{m}"' for m in SPAM]
    lines += [f'ham,"{m}"' for m in HAM]
    data_path.write_text("\n".join(lines), encoding="utf-8")
    model_path = tmp_path_factory.mktemp("models") / "tiny_model.pkl"
    train(data_path=data_path, model_path=model_path, supplement_path=None)
    return model_path


def test_train_saves_model(trained_model_path):
    assert trained_model_path.exists()


def test_load_model_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_model(tmp_path / "missing.pkl")


def test_predict_message_contract(trained_model_path):
    result = predict_message("Claim your free prize now!", model_path=trained_model_path)
    assert set(result) == {"prediction", "probability", "flags"}
    assert result["prediction"] in {"spam", "ham"}
    assert 0.0 <= result["probability"] <= 1.0
    assert set(result["flags"]) <= {"has_url", "has_phone", "has_money", "has_urgency"}


def test_obvious_spam_and_ham(trained_model_path):
    spam = predict_message("Congrats! Claim your free prize of ₱100,000 now", model_path=trained_model_path)
    ham = predict_message("Salamat! See you at the meeting tomorrow", model_path=trained_model_path)
    assert spam["prediction"] == "spam"
    assert ham["prediction"] == "ham"
