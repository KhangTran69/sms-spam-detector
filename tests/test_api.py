"""API behavior tests for api.main.

The tests use in-memory scikit-learn pipelines wrapped in the real
``src.predict.ModelBundle``; no ``models/`` artifact and no training run is
needed. ``api.main.get_model`` / ``api.main._model`` stay injectable, which is
how each test swaps in a deterministic or real model.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sklearn.base import BaseEstimator, ClassifierMixin

import api.main as api_main
from src.features import make_model, messages_to_frame
from src.predict import ModelBundle, load_model

MESSAGES = [
    "Claim ₱1,000,000 now! Call 09171234567",
    "BDO: account locked, verify http://bit.ly/fake",
    "Thanks, see you at lunch tomorrow",
    "Your OTP is 123456. Do not share.",
]
LABELS = ["spam", "spam", "ham", "ham"]

DATA_NOTE = "Trained on synthetic Philippine template data; this is not proof of real-world accuracy."
MODEL_VERSION = "test-bundle-1.0"
DECISION_THRESHOLD = 0.80
SUSPICIOUS_THRESHOLD = 0.40


class FixedClassifier(ClassifierMixin, BaseEstimator):
    """Deterministic classifier so API tests never depend on learned weights."""

    def __init__(self, spam_probability: float = 0.93):
        self.spam_probability = spam_probability

    def fit(self, X, y=None):
        self.classes_ = np.array(["ham", "spam"])
        self.n_features_in_ = X.shape[1]
        return self

    def predict_proba(self, X):
        probability = float(self.spam_probability)
        return np.tile(np.array([1.0 - probability, probability]), (len(X), 1))


def fixed_pipeline(spam_probability: float = 0.93):
    pipeline = make_model(FixedClassifier(spam_probability))
    pipeline.fit(messages_to_frame(MESSAGES), LABELS)
    return pipeline


def make_bundle(
    pipeline=None,
    *,
    threshold: float = DECISION_THRESHOLD,
    suspicious_threshold: float = SUSPICIOUS_THRESHOLD,
    version: str = MODEL_VERSION,
) -> ModelBundle:
    return ModelBundle(
        pipeline=pipeline if pipeline is not None else fixed_pipeline(),
        threshold=threshold,
        suspicious_threshold=suspicious_threshold,
        metadata={
            "artifact_schema_version": 2,
            "model_version": version,
            "feature_version": "2.0.0",
            "trained_at": "2026-10-19T00:00:00+00:00",
            "data_sources": [{"path": "data/raw/ph_supplement.csv", "sha256": "test"}],
            "synthetic_training_data": True,
            "data_note": DATA_NOTE,
            "metrics": {"spam_precision": 1.0, "spam_recall": 0.5},
            "warnings": [],
        },
        path=Path("tests/fixtures/test-bundle.pkl"),
        legacy=False,
    )


@contextmanager
def patched_client(get_model_impl, model=None, *, raise_server_exceptions: bool = True):
    """Run the app with an injected model provider, restoring globals afterwards."""
    original_get_model = api_main.get_model
    original_model = api_main._model
    api_main.get_model = get_model_impl
    api_main._model = model
    try:
        with TestClient(api_main.app, raise_server_exceptions=raise_server_exceptions) as client:
            yield client
    finally:
        api_main.get_model = original_get_model
        api_main._model = original_model


@pytest.fixture()
def bundle() -> ModelBundle:
    return make_bundle()


@pytest.fixture()
def client(bundle):
    with patched_client(lambda: bundle, bundle) as test_client:
        yield test_client


@pytest.fixture()
def missing_model_client():
    def missing_model():
        raise FileNotFoundError(
            "Model artifact not found at models/spam_detector_v1.pkl. Train it first with: python -m src.train"
        )

    with patched_client(missing_model, None) as test_client:
        yield test_client


@pytest.fixture()
def corrupt_model_client(tmp_path):
    corrupt_path = tmp_path / "corrupt.pkl"
    corrupt_path.write_bytes(b"this is definitely not a joblib artifact")
    with patched_client(lambda: load_model(corrupt_path), None) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# /health and /ready
# ---------------------------------------------------------------------------
def test_health_reports_loaded_model(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "model_loaded", "model_version"}
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["model_version"] == MODEL_VERSION


def test_health_never_503_when_model_missing(missing_model_client):
    response = missing_model_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is False
    assert body["model_version"] is None


def test_ready_loads_model(client):
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "model_loaded", "model_version"}
    assert body["status"] == "ready"
    assert body["model_loaded"] is True
    assert body["model_version"] == MODEL_VERSION


def test_production_rejects_legacy_artifact_unless_explicitly_allowed(monkeypatch):
    legacy = ModelBundle(pipeline=fixed_pipeline(), legacy=True, metadata={"model_version": "legacy-test"})
    monkeypatch.setattr(api_main, "SMSD_ENV", "production")
    monkeypatch.setattr(api_main, "ALLOW_LEGACY_MODEL", False)
    monkeypatch.setattr(api_main, "_model", None)
    monkeypatch.setattr(api_main, "load_model", lambda: legacy)
    with TestClient(api_main.app) as test_client:
        response = test_client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"
    assert "versioned model bundle" in response.json()["error"]["message"]


def test_explicit_legacy_override_allows_production_readiness(monkeypatch):
    legacy = ModelBundle(pipeline=fixed_pipeline(), legacy=True, metadata={"model_version": "legacy-test"})
    monkeypatch.setattr(api_main, "SMSD_ENV", "production")
    monkeypatch.setattr(api_main, "ALLOW_LEGACY_MODEL", True)
    monkeypatch.setattr(api_main, "_model", None)
    monkeypatch.setattr(api_main, "load_model", lambda: legacy)
    with TestClient(api_main.app) as test_client:
        response = test_client.get("/ready")
    assert response.status_code == 200


def test_ready_503_when_model_missing(missing_model_client):
    response = missing_model_client.get("/ready")
    assert response.status_code == 503
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == "model_unavailable"
    assert "src.train" in error["message"]


def test_corrupt_artifact_returns_503_everywhere(corrupt_model_client):
    for method, path in (
        ("get", "/ready"),
        ("get", "/model-info"),
        ("post", "/predict"),
        ("post", "/analyze"),
        ("post", "/analyze/batch"),
    ):
        kwargs = {"json": {"message": "hello"}} if path in {"/predict", "/analyze"} else {}
        if path == "/analyze/batch":
            kwargs = {"json": {"messages": ["hello"]}}
        response = getattr(corrupt_model_client, method)(path, **kwargs)
        assert response.status_code == 503, (path, response.text)
        error = response.json()["error"]
        assert error["code"] == "model_unavailable"
        assert "src.train" in error["message"]


def test_missing_model_returns_503_for_prediction_endpoints(missing_model_client):
    responses = [
        missing_model_client.post("/predict", json={"message": "hello"}),
        missing_model_client.post("/analyze", json={"message": "hello"}),
        missing_model_client.post("/analyze/batch", json={"messages": ["hello"]}),
        missing_model_client.get("/model-info"),
    ]
    for response in responses:
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "model_unavailable"


def test_feedback_is_disabled_by_default(client, monkeypatch):
    monkeypatch.setattr(api_main, "FEEDBACK_ENABLED", False)
    response = client.post(
        "/feedback",
        json={
            "model_version": MODEL_VERSION,
            "predicted_label": "spam",
            "expected_label": "ham",
            "category": "otp",
        },
    )
    assert response.status_code == 404
    assert "disabled" in response.json()["error"]["message"]


def test_feedback_persists_only_explicit_non_message_metadata(client, tmp_path, monkeypatch):
    report_path = tmp_path / "feedback" / "reports.jsonl"
    monkeypatch.setattr(api_main, "FEEDBACK_ENABLED", True)
    monkeypatch.setattr(api_main, "FEEDBACK_PATH", report_path)
    response = client.post(
        "/feedback",
        json={
            "model_version": MODEL_VERSION,
            "predicted_label": "spam",
            "expected_label": "ham",
            "category": "otp",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "received"
    stored = json.loads(report_path.read_text(encoding="utf-8"))
    assert stored["model_version"] == MODEL_VERSION
    assert stored["server_model_version"] == MODEL_VERSION
    assert stored["predicted_label"] == "spam"
    assert stored["expected_label"] == "ham"
    assert stored["category"] == "otp"
    assert not ({"message", "text", "sms", "body"} & set(stored))


def test_feedback_rejects_message_content_and_correct_predictions(client, tmp_path, monkeypatch):
    monkeypatch.setattr(api_main, "FEEDBACK_ENABLED", True)
    monkeypatch.setattr(api_main, "FEEDBACK_PATH", tmp_path / "feedback.jsonl")
    with_text = client.post(
        "/feedback",
        json={
            "model_version": MODEL_VERSION,
            "predicted_label": "spam",
            "expected_label": "ham",
            "category": "otp",
            "message": "private SMS must not be submitted",
        },
    )
    same_label = client.post(
        "/feedback",
        json={
            "model_version": MODEL_VERSION,
            "predicted_label": "spam",
            "expected_label": "spam",
        },
    )
    assert with_text.status_code == 422
    assert "private SMS" not in with_text.text
    assert same_label.status_code == 422
    assert not (tmp_path / "feedback.jsonl").exists()


# ---------------------------------------------------------------------------
# Model lifecycle
# ---------------------------------------------------------------------------
def test_get_model_is_lazy_and_reused(monkeypatch, bundle):
    calls: list[int] = []

    def fake_load():
        calls.append(1)
        return bundle

    monkeypatch.setattr(api_main, "load_model", fake_load)
    monkeypatch.setattr(api_main, "_model", None)
    assert api_main.get_model() is bundle
    assert api_main.get_model() is bundle
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# /predict
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "spam_probability,threshold,prediction,class_probability",
    [
        (0.93, 0.80, "spam", 0.93),
        (0.20, 0.80, "ham", 0.80),
        (0.75, 0.80, "ham", 0.25),
    ],
)
def test_predict_uses_bundle_threshold(spam_probability, threshold, prediction, class_probability):
    test_bundle = make_bundle(fixed_pipeline(spam_probability), threshold=threshold)
    with patched_client(lambda: test_bundle, test_bundle) as client:
        response = client.post("/predict", json={"message": "Claim ₱1,000,000 now! Call 09171234567"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "prediction",
        "probability",
        "probability_calibrated",
        "flags",
        "decision_threshold",
        "model_version",
    }
    assert body["prediction"] == prediction
    assert body["probability"] == pytest.approx(class_probability)
    assert body["probability_calibrated"] is False
    assert body["decision_threshold"] == pytest.approx(threshold)
    assert body["model_version"] == MODEL_VERSION
    assert isinstance(body["flags"], list)


def test_predict_flags_only_known_indicators(client):
    body = client.post("/predict", json={"message": "Claim ₱1,000,000 now! Call 09171234567"}).json()
    assert {"has_phone", "has_money", "has_urgency"} <= set(body["flags"])


# ---------------------------------------------------------------------------
# /analyze
# ---------------------------------------------------------------------------
ANALYZE_KEYS = {
    "message",
    "prediction",
    "spam_probability",
    "probability_calibrated",
    "probability",
    "decision_threshold",
    "margin",
    "confidence",
    "risk_band",
    "flags",
    "matches",
    "brands",
    "model_version",
}


def test_analyze_returns_full_contract_payload(client):
    message = "BDO: account locked! Verify http://bit.ly/fake or call 09171234567"
    body = client.post("/analyze", json={"message": message}).json()
    assert set(body) == ANALYZE_KEYS
    assert body["message"] == message
    assert body["prediction"] == "spam"
    assert body["spam_probability"] == pytest.approx(0.93)
    assert body["probability_calibrated"] is False
    assert body["probability"] == pytest.approx(0.93)
    assert body["decision_threshold"] == pytest.approx(DECISION_THRESHOLD)
    assert body["margin"] == pytest.approx(abs(0.93 - DECISION_THRESHOLD))
    assert body["confidence"] == "medium"
    assert body["risk_band"] == "likely_scam"
    assert body["model_version"] == MODEL_VERSION
    assert {"has_url", "has_phone"} <= set(body["flags"])
    assert "bdo" in body["brands"]


def test_analyze_match_offsets_slice_the_message(client):
    message = "Verify at http://bit.ly/fake agad"
    body = client.post("/analyze", json={"message": message}).json()
    assert body["matches"], "expected highlighted signal spans"
    for match in body["matches"]:
        assert set(match) == {"type", "text", "start", "end"}
        assert 0 <= match["start"] < match["end"] <= len(message)
        assert message[match["start"] : match["end"]] == match["text"]


@pytest.mark.parametrize(
    "spam_probability,threshold,expected_band,expected_confidence",
    [
        (0.95, 0.80, "likely_scam", "medium"),
        (0.75, 0.80, "suspicious", "low"),
        (0.10, 0.80, "looks_safe", "high"),
        (0.99, 0.50, "likely_scam", "high"),
    ],
)
def test_analyze_risk_band_and_confidence(spam_probability, threshold, expected_band, expected_confidence):
    test_bundle = make_bundle(fixed_pipeline(spam_probability), threshold=threshold)
    with patched_client(lambda: test_bundle, test_bundle) as client:
        body = client.post("/analyze", json={"message": "hello there"}).json()
    assert body["risk_band"] == expected_band
    assert body["confidence"] == expected_confidence
    assert body["margin"] == pytest.approx(abs(spam_probability - threshold))


def test_analyze_with_real_sklearn_pipeline():
    from sklearn.naive_bayes import MultinomialNB

    pipeline = make_model(MultinomialNB())
    pipeline.fit(messages_to_frame(MESSAGES), LABELS)
    test_bundle = make_bundle(pipeline, threshold=0.70, suspicious_threshold=0.30)
    with patched_client(lambda: test_bundle, test_bundle) as client:
        response = client.post("/analyze", json={"message": "Your OTP is 123456. Do not share."})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["prediction"] in {"ham", "spam"}
    assert 0.0 <= body["spam_probability"] <= 1.0
    assert body["decision_threshold"] == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# Validation + stable error schema (no message echo)
# ---------------------------------------------------------------------------
def assert_error_schema(response, status_code: int, code: str):
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert error["details"] is None or isinstance(error["details"], list)


@pytest.mark.parametrize("message", ["", "   ", "\n\t ", "a" * 10001])
def test_analyze_rejects_invalid_messages(client, message):
    response = client.post("/analyze", json={"message": message})
    assert_error_schema(response, 422, "validation_error")


def test_predict_rejects_missing_field(client):
    response = client.post("/predict", json={})
    assert_error_schema(response, 422, "validation_error")
    assert ["body", "message"] in [detail["loc"] for detail in response.json()["error"]["details"]]


def test_predict_rejects_non_string_message(client):
    assert_error_schema(client.post("/predict", json={"message": 123}), 422, "validation_error")


def test_validation_errors_never_echo_message_contents(client):
    secret = "TOPSECRET-CUSTOMER-TEXT"
    responses = [
        client.post("/predict", json={"message": secret + "a" * 10001}),
        client.post("/analyze", json={"message": "   "}),
        client.post("/analyze/batch", json={"messages": [secret + "a" * 10001]}),
        client.post("/analyze/batch", json={"messages": ["hello", "   "]}),
        client.post(
            "/predict",
            content=('{"message": "' + secret).encode(),
            headers={"Content-Type": "application/json"},
        ),
    ]
    for response in responses:
        assert response.status_code == 422, response.text
        assert "TOPSECRET" not in response.text
        assert_error_schema(response, 422, "validation_error")


def test_max_allowed_message_length_accepted(client):
    response = client.post("/analyze", json={"message": "a" * 10000})
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# /analyze/batch
# ---------------------------------------------------------------------------
def test_batch_returns_aligned_results(client):
    messages = [
        "Claim ₱1,000,000 prize now! Call 09171234567",
        "Thanks, see you at lunch tomorrow",
    ]
    response = client.post("/analyze/batch", json={"messages": messages})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"count", "results", "model_version", "decision_threshold"}
    assert body["count"] == 2
    assert body["decision_threshold"] == pytest.approx(DECISION_THRESHOLD)
    assert body["model_version"] == MODEL_VERSION
    assert [item["message"] for item in body["results"]] == messages
    for item in body["results"]:
        assert set(item) == ANALYZE_KEYS


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": []},
        {"messages": ["hello"] * 51},
        {"messages": ["hello", "   "]},
        {"messages": ["a" * 10001]},
        {"messages": ["a" * 10000] * 21},  # 210,000 characters > 200,000
    ],
)
def test_batch_rejects_invalid_payloads(client, payload):
    response = client.post("/analyze/batch", json=payload)
    assert_error_schema(response, 422, "validation_error")


def test_batch_total_character_boundary_accepted(client):
    messages = ["a" * 10000] * 20  # exactly 200,000 characters
    response = client.post("/analyze/batch", json={"messages": messages})
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 20


# ---------------------------------------------------------------------------
# /model-info
# ---------------------------------------------------------------------------
MODEL_INFO_KEYS = {
    "model_version",
    "artifact_schema_version",
    "classes",
    "decision_threshold",
    "suspicious_threshold",
    "bands",
    "trained_at",
    "training_data",
    "synthetic_training_data",
    "probability_calibrated",
    "data_note",
    "feedback_enabled",
    "metrics",
    "legacy_artifact",
    "warnings",
}


def test_model_info_exposes_thresholds_and_provenance(client):
    response = client.get("/model-info")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) >= MODEL_INFO_KEYS
    assert body["model_version"] == MODEL_VERSION
    assert body["decision_threshold"] == pytest.approx(DECISION_THRESHOLD)
    assert body["suspicious_threshold"] == pytest.approx(SUSPICIOUS_THRESHOLD)
    assert body["probability_calibrated"] is False
    assert body["feedback_enabled"] is False
    assert body["bands"] == {
        "likely_scam": pytest.approx(DECISION_THRESHOLD),
        "suspicious": pytest.approx(SUSPICIOUS_THRESHOLD),
        "looks_safe": pytest.approx(0.0),
    }
    assert body["classes"] == ["ham", "spam"]
    assert body["synthetic_training_data"] is True
    assert body["data_note"] == DATA_NOTE
    assert body["legacy_artifact"] is False
    json.dumps(body)  # must be JSON-safe


# ---------------------------------------------------------------------------
# Error schema for generic HTTP errors, oversize bodies, internal errors
# ---------------------------------------------------------------------------
def test_unknown_route_uses_error_schema(client):
    response = client.get("/does-not-exist")
    assert_error_schema(response, 404, "not_found")


def test_method_not_allowed_uses_error_schema(client):
    response = client.get("/predict")
    assert_error_schema(response, 405, "method_not_allowed")


def test_oversized_request_body_returns_413(client):
    body = b'{"message": "' + b"a" * 1_000_001 + b'"}'
    response = client.post("/predict", content=body, headers={"Content-Type": "application/json"})
    assert_error_schema(response, 413, "payload_too_large")
    assert "aaaa" not in response.text


def test_unhandled_exception_returns_generic_500():
    def explode():
        raise RuntimeError("boom with internal detail")

    with patched_client(explode, None, raise_server_exceptions=False) as client:
        response = client.get("/model-info")
    assert_error_schema(response, 500, "internal_error")
    assert "boom" not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text


def test_security_headers_on_success_and_error(client):
    for response in (
        client.get("/health"),
        client.post("/predict", json={}),
        client.get("/does-not-exist"),
    ):
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"


# ---------------------------------------------------------------------------
# CORS defaults
# ---------------------------------------------------------------------------
def test_cors_defaults_are_not_wildcard():
    assert "*" not in api_main.CORS_ORIGINS
    assert "http://127.0.0.1:8000" in api_main.CORS_ORIGINS
    assert "http://localhost:8000" in api_main.CORS_ORIGINS

    cors_middleware = [
        middleware
        for middleware in api_main.app.user_middleware
        if "CORSMiddleware" in str(getattr(middleware, "cls", ""))
    ]
    assert cors_middleware, "CORS middleware must be installed"
    options = getattr(cors_middleware[0], "kwargs", {})
    assert "*" not in options.get("allow_origins", [])
    assert options.get("allow_credentials") is False
    assert set(options.get("allow_methods", [])) == {"GET", "POST"}
    assert "Content-Type" in options.get("allow_headers", [])


def test_cors_env_parsing(monkeypatch):
    assert api_main.cors_origins("http://a.test, http://b.test/") == ["http://a.test", "http://b.test"]
    assert api_main.cors_origins("*") == list(api_main.DEFAULT_CORS_ORIGINS)
    assert api_main.cors_origins("") == list(api_main.DEFAULT_CORS_ORIGINS)
    assert api_main.cors_origins("*,http://c.test") == ["http://c.test"]
    monkeypatch.setenv("SMSD_CORS_ORIGINS", "http://example.test")
    assert api_main.cors_origins() == ["http://example.test"]


def test_cors_preflight_allows_local_origin(client):
    response = client.options(
        "/analyze",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8000"


# ---------------------------------------------------------------------------
# Bundled web UI is served
# ---------------------------------------------------------------------------
def test_index_and_static_files_are_served(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert "PH SMS Scam Detector" in index.text

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
