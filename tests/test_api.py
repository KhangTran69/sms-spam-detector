"""API behavior tests using a tiny in-memory model (no repo model artifact needed)."""
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from src.features import make_model, messages_to_frame
from sklearn.naive_bayes import MultinomialNB

MESSAGES = [
    "Claim ₱1,000,000 now! Call 09171234567",
    "BDO: account locked, verify http://bit.ly/fake",
    "Thanks, see you at lunch tomorrow",
    "Your OTP is 123456. Do not share.",
]
LABELS = ["spam", "spam", "ham", "ham"]


@pytest.fixture()
def client_with_model():
    model = make_model(MultinomialNB())
    model.fit(messages_to_frame(MESSAGES), LABELS)
    original = api_main.get_model
    api_main.get_model = lambda: model
    api_main._model = model
    try:
        with TestClient(api_main.app) as client:
            yield client
    finally:
        api_main.get_model = original
        api_main._model = None


@pytest.fixture()
def client_without_model():
    original = api_main.get_model
    api_main._model = None

    def missing():
        raise FileNotFoundError("Model not found at models/spam_detector_v1.pkl")

    api_main.get_model = missing
    try:
        with TestClient(api_main.app) as client:
            yield client
    finally:
        api_main.get_model = original
        api_main._model = None


def test_health(client_with_model):
    response = client_with_model.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_predict_valid_message(client_with_model):
    response = client_with_model.post("/predict", json={"message": "Claim ₱1,000,000 prize now! Call 09171234567"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"prediction", "probability", "flags"}
    assert body["prediction"] == "spam"
    assert 0.0 <= body["probability"] <= 1.0
    assert "has_phone" in body["flags"] and "has_money" in body["flags"]


def test_predict_ham_message(client_with_model):
    response = client_with_model.post("/predict", json={"message": "Thanks, see you at lunch"})
    assert response.status_code == 200
    assert response.json()["prediction"] == "ham"


def test_empty_message_rejected(client_with_model):
    response = client_with_model.post("/predict", json={"message": ""})
    assert response.status_code == 422


def test_oversized_message_rejected(client_with_model):
    response = client_with_model.post("/predict", json={"message": "a" * 10001})
    assert response.status_code == 422


def test_missing_field_rejected(client_with_model):
    response = client_with_model.post("/predict", json={})
    assert response.status_code == 422


def test_missing_model_returns_503(client_without_model):
    response = client_without_model.post("/predict", json={"message": "hello"})
    assert response.status_code == 503
    assert "Model not found" in response.json()["detail"]


# ---------- /analyze ----------

def test_analyze_returns_rich_payload(client_with_model):
    response = client_with_model.post(
        "/analyze", json={"message": "Claim ₱1,000,000 prize now! Call 09171234567 or visit http://bit.ly/x"}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "prediction", "spam_probability", "probability", "flags", "matches", "brands"}
    assert body["prediction"] == "spam"
    assert 0.0 <= body["spam_probability"] <= 1.0
    # probability stays the probability of the returned class
    assert body["probability"] == pytest.approx(1.0 - body["spam_probability"] if body["prediction"] == "ham"
                                                else body["spam_probability"])
    assert "has_url" in body["flags"] and "has_phone" in body["flags"] and "has_money" in body["flags"]


def test_analyze_exposes_matches_and_brands(client_with_model):
    response = client_with_model.post(
        "/analyze", json={"message": "BDO: account locked, verify http://bit.ly/fake now or call 09171234567"}
    )
    assert response.status_code == 200
    body = response.json()
    types = {match["type"] for match in body["matches"]}
    assert {"url", "brand", "urgency", "phone"} <= types
    for match in body["matches"]:
        assert set(match) == {"type", "text", "start", "end"}
        assert 0 <= match["start"] < match["end"] <= len(body["message"])
    assert "bdo" in body["brands"]


def test_analyze_match_offsets_slice_original(client_with_model):
    message = "Verify at http://bit.ly/fake agad"
    body = client_with_model.post("/analyze", json={"message": message}).json()
    url_matches = [m for m in body["matches"] if m["type"] == "url"]
    assert url_matches and url_matches[0]["text"] == message[url_matches[0]["start"]:url_matches[0]["end"]]


def test_analyze_brands_lowercase_unique(client_with_model):
    body = client_with_model.post("/analyze", json={"message": "GCASH padala from BDO and gcash again"}).json()
    assert body["brands"] == ["gcash", "bdo"]


def test_analyze_ham_message(client_with_model):
    body = client_with_model.post("/analyze", json={"message": "Thanks, see you at lunch tomorrow"}).json()
    assert body["prediction"] == "ham"
    assert body["matches"] == []
    assert body["brands"] == []


def test_analyze_blank_message_rejected(client_with_model):
    response = client_with_model.post("/analyze", json={"message": "   "})
    assert response.status_code == 422


def test_predict_blank_message_rejected(client_with_model):
    response = client_with_model.post("/predict", json={"message": "  \n\t "})
    assert response.status_code == 422


def test_analyze_missing_model_returns_503(client_without_model):
    response = client_without_model.post("/analyze", json={"message": "hello"})
    assert response.status_code == 503


# ---------- /analyze/batch ----------

def test_batch_returns_aligned_results(client_with_model):
    messages = ["Claim ₱1,000,000 prize now! Call 09171234567", "Thanks, see you at lunch tomorrow"]
    response = client_with_model.post("/analyze/batch", json={"messages": messages})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert len(body["results"]) == 2
    assert [r["prediction"] for r in body["results"]] == ["spam", "ham"]
    assert [r["message"] for r in body["results"]] == messages
    assert all(set(r) == {"message", "prediction", "spam_probability", "probability", "flags", "matches", "brands"}
               for r in body["results"])


def test_batch_single_message(client_with_model):
    response = client_with_model.post("/analyze/batch", json={"messages": ["Your OTP is 123456. Do not share."]})
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_batch_empty_list_rejected(client_with_model):
    response = client_with_model.post("/analyze/batch", json={"messages": []})
    assert response.status_code == 422


def test_batch_over_limit_rejected(client_with_model):
    response = client_with_model.post("/analyze/batch", json={"messages": ["hello"] * 51})
    assert response.status_code == 422


def test_batch_blank_item_rejected(client_with_model):
    response = client_with_model.post("/analyze/batch", json={"messages": ["hello", "   "]})
    assert response.status_code == 422


def test_batch_oversized_item_rejected(client_with_model):
    response = client_with_model.post("/analyze/batch", json={"messages": ["a" * 10001]})
    assert response.status_code == 422


def test_batch_missing_model_returns_503(client_without_model):
    response = client_without_model.post("/analyze/batch", json={"messages": ["hello"]})
    assert response.status_code == 503
