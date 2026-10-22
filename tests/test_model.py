"""Model training, artifact/persistence, threshold, and inference contract tests."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import joblib
import pytest
from sklearn.naive_bayes import MultinomialNB

from src.features import make_model, messages_to_frame
from src.predict import (
    ARTIFACT_SCHEMA_VERSION,
    ModelArtifactError,
    ModelBundle,
    analyze_batch,
    analyze_message,
    analyze_messages,
    load_model,
    model_info,
    predict_message,
)
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
    "You are selected! Send your account details to 09176667777 to receive ₱20,000.",
    "Final notice: claim your unclaimed prize of PHP 75,000 today!",
    "Lucky texter! Win a free iPhone. Register at bit.ly/prize-now agad.",
    "You won ₱500,000 from PCSO. Text your name to 09178889999 now.",
    "Free load giveaway! First 100 texters get PHP 1,000. Text JOIN now.",
    "Your parcel is held. Pay ₱150 customs fee at bit.ly/parcel-fee today.",
    "Account suspended. Verify at bdo-secure.xyz/login immediately.",
    "Investment opportunity: 20% monthly return guaranteed. Message 09179990000 now.",
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
    "Your BDO OTP is 294831. Do not share with anyone.",
    "GCash: You received ₱1,500 from ANA LIM. Balance: ₱6,200.00.",
    "Meralco: Your bill of ₱1,890.50 is due Nov 5. Pay via app.",
    "J&T Express: Parcel JT5522878 out for delivery. Track at jtexpress.ph/track",
    "LBC: Your parcel is at the branch. Claim within 5 days.",
    "Uwi ka na agad, ulan na dito sa amin. Ingat!",
    "Salamat sa regalo mo! See you Sunday sa reunion.",
    "BPI: OTP 558201. Never share this code with anyone.",
]


def make_tiny_dataset(path: Path) -> Path:
    import csv

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["label", "message", "category", "language", "group"])
        for index, message in enumerate(SPAM):
            writer.writerow(["spam", message, "prize_scam", "taglish", f"spam-family-{index}"])
        for index, message in enumerate(HAM):
            writer.writerow(["ham", message, "personal", "taglish", f"ham-family-{index}"])
    return path


@pytest.fixture(scope="module")
def trained_artifact(tmp_path_factory):
    data_path = make_tiny_dataset(tmp_path_factory.mktemp("data") / "tiny.csv")
    model_path = tmp_path_factory.mktemp("models") / "tiny_model.pkl"
    artifact = train(
        data_path=data_path,
        model_path=model_path,
        supplement_path=None,
        holdout_path=None,
        val_size=0.2,
        test_size=0.2,
        random_state=7,
        target_precision=0.5,
        min_recall=0.0,
        write_metadata=False,
        verbose=False,
    )
    return artifact, model_path


def test_artifact_contains_required_metadata(trained_artifact):
    artifact, _ = trained_artifact
    assert artifact["artifact_schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert 0.0 < artifact["threshold"] < 1.0
    assert artifact["label_map"] == {"ham": "ham", "spam": "spam"}
    assert artifact["classes"] == ["ham", "spam"]
    assert artifact["training_config"]["random_state"] == 7
    assert artifact["text_feature_mode"] == "combined"
    assert artifact["training_config"]["text_features"] == "combined"
    assert artifact["probability_calibrated"] is True
    assert artifact["model_selection"]["selected"] in {
        row["candidate"] for row in artifact["model_selection"]["candidates"]
    }
    decision = artifact["threshold_selection"]["decision"]
    assert decision["policy"] == "cv-robust"
    assert artifact["threshold"] == decision["threshold"]
    assert artifact["data_sources"][0]["sha256"]
    assert "model_version" in artifact
    assert "metrics" in artifact
    assert "split" in artifact
    assert artifact["split"]["group_leakage"] == 0
    assert artifact["threshold_selection"]["target_precision"] == 0.5
    assert "data_note" in artifact and "synthetic" in artifact["data_note"].lower()


def test_load_model_returns_bundle_with_matching_threshold(trained_artifact):
    artifact, model_path = trained_artifact
    bundle = load_model(model_path)
    assert isinstance(bundle, ModelBundle)
    assert bundle.threshold == pytest.approx(artifact["threshold"])
    assert bundle.classes == ["ham", "spam"]
    assert bundle.version == artifact["model_version"]
    assert bundle.bands["likely_scam"] == pytest.approx(bundle.threshold)
    assert bundle.bands["suspicious"] < bundle.bands["likely_scam"]
    assert bundle.legacy is False


def test_model_info_is_json_safe_and_contains_provenance(trained_artifact):
    _, model_path = trained_artifact
    info = model_info(model_path=model_path)
    json.dumps(info)
    assert info["model_version"]
    assert info["decision_threshold"] > 0
    assert info["training_data"]
    assert info["synthetic_training_data"] is None
    assert "synthetic" in info["data_note"].lower()


def test_predict_message_contract(trained_artifact):
    _, model_path = trained_artifact
    result = predict_message("Claim your free prize now!", model_path=model_path)
    assert set(result) == {"prediction", "probability", "flags"}
    assert result["prediction"] in {"spam", "ham"}
    assert 0.0 <= result["probability"] <= 1.0
    assert set(result["flags"]) <= {"has_url", "has_phone", "has_money", "has_urgency"}


def test_analyze_message_contract_and_threshold_consistency(trained_artifact):
    _, model_path = trained_artifact
    bundle = load_model(model_path)
    result = analyze_message("Congratulations! Claim your free ₱100,000 now", model_path=model_path)
    assert set(result) == {
        "message",
        "prediction",
        "spam_probability",
        "probability_calibrated",
        "probability",
        "decision_threshold",
        "suspicious_threshold",
        "margin",
        "confidence",
        "risk_band",
        "flags",
        "matches",
        "brands",
        "model_version",
    }
    assert result["decision_threshold"] == pytest.approx(bundle.threshold)
    assert result["suspicious_threshold"] == pytest.approx(bundle.suspicious_threshold)
    assert result["probability_calibrated"] is True
    assert result["prediction"] == ("spam" if result["spam_probability"] >= bundle.threshold else "ham")
    assert result["margin"] == pytest.approx(abs(result["spam_probability"] - bundle.threshold))
    assert result["confidence"] in {"low", "medium", "high"}
    assert result["risk_band"] in {"likely_scam", "suspicious", "looks_safe"}
    expected_probability = (
        result["spam_probability"] if result["prediction"] == "spam" else 1 - result["spam_probability"]
    )
    assert result["probability"] == pytest.approx(expected_probability)


def test_batch_analysis_matches_single_analysis(trained_artifact):
    _, model_path = trained_artifact
    messages = ["Claim your free prize now!", "Thanks, see you at lunch tomorrow", "GCash: You received ₱1,500"]
    batch = analyze_batch(messages, model_path=model_path)
    singles = [analyze_message(message, model_path=model_path) for message in messages]
    assert [item["message"] for item in batch] == messages
    assert [item["prediction"] for item in batch] == [item["prediction"] for item in singles]
    assert [item["spam_probability"] for item in batch] == pytest.approx([item["spam_probability"] for item in singles])


def test_threshold_changes_decision_consistently():
    model = make_model(MultinomialNB())
    model.fit(messages_to_frame(SPAM + HAM), ["spam"] * len(SPAM) + ["ham"] * len(HAM))
    low = ModelBundle(pipeline=model, threshold=0.1)
    high = ModelBundle(pipeline=model, threshold=0.99)
    message = "Claim your free prize now!"
    low_result = analyze_message(message, model=low)
    high_result = analyze_message(message, model=high)
    assert low_result["decision_threshold"] == pytest.approx(0.1)
    assert high_result["decision_threshold"] == pytest.approx(0.99)
    assert low_result["prediction"] == ("spam" if low_result["spam_probability"] >= 0.1 else "ham")
    assert high_result["prediction"] == ("spam" if high_result["spam_probability"] >= 0.99 else "ham")


def test_legacy_bare_pipeline_artifact_is_supported_with_warning(tmp_path):
    model = make_model(MultinomialNB())
    model.fit(messages_to_frame(SPAM + HAM), ["spam"] * len(SPAM) + ["ham"] * len(HAM))
    path = tmp_path / "legacy.pkl"
    joblib.dump(model, path)
    bundle = load_model(path)
    assert bundle.legacy is True
    assert bundle.threshold == pytest.approx(0.5)
    assert any("Legacy artifact" in warning for warning in bundle.model_info()["warnings"])


def test_missing_model_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="python -m src.train"):
        load_model(tmp_path / "missing.pkl")


def test_corrupt_artifact_fails_safely(tmp_path):
    path = tmp_path / "corrupt.pkl"
    path.write_text("this is not a joblib artifact", encoding="utf-8")
    with pytest.raises(ModelArtifactError, match="Could not read|corrupt"):
        load_model(path)


def test_model_hash_verification_accepts_matching_digest(trained_artifact, monkeypatch):
    _, model_path = trained_artifact
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    monkeypatch.setenv("SMSD_MODEL_SHA256", digest)
    assert load_model(model_path).path == model_path


def test_hash_verified_bytes_are_the_bytes_given_to_joblib(trained_artifact, monkeypatch):
    _, model_path = trained_artifact
    import joblib

    original_load = joblib.load
    received: list[bytes] = []

    def capture(source):
        payload = source.read()
        received.append(payload)
        return original_load(io.BytesIO(payload))

    monkeypatch.setattr(joblib, "load", capture)
    monkeypatch.setenv("SMSD_MODEL_SHA256", hashlib.sha256(model_path.read_bytes()).hexdigest())
    assert load_model(model_path).path == model_path
    assert received == [model_path.read_bytes()]


def test_identified_artifact_hash_matches_the_exact_bytes_deserialized(trained_artifact, tmp_path, monkeypatch):
    _, trained_path = trained_artifact
    model_path = tmp_path / "replace-after-read.pkl"
    original_bytes = trained_path.read_bytes()
    model_path.write_bytes(original_bytes)
    original_load = joblib.load

    def replace_file_after_read(source):
        payload = source.read()
        model_path.write_bytes(b"replacement artifact")
        return original_load(io.BytesIO(payload))

    monkeypatch.setattr(joblib, "load", replace_file_after_read)
    bundle = load_model(model_path, identify_artifact=True)

    assert bundle.artifact_sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert hashlib.sha256(model_path.read_bytes()).hexdigest() != bundle.artifact_sha256


def test_compatible_word_only_feature_version_loads_with_warning(tmp_path):
    data_path = make_tiny_dataset(tmp_path / "tiny.csv")
    artifact = train(
        data_path=data_path,
        model_path=tmp_path / "word.pkl",
        supplement_path=None,
        holdout_path=None,
        val_size=0.2,
        test_size=0.2,
        random_state=7,
        target_precision=0.5,
        min_recall=0.0,
        text_features="word",
        write_metadata=False,
        verbose=False,
    )
    payload = dict(artifact)
    payload["feature_version"] = "2.1.0"
    path = tmp_path / "compatible-word.pkl"
    joblib.dump(payload, path)
    bundle = load_model(path)
    assert bundle.version == artifact["model_version"]
    assert any("compatible 2.1.0 word-only" in warning for warning in bundle.metadata["warnings"])


def test_model_hash_verification_rejects_mismatch(trained_artifact, monkeypatch):
    _, model_path = trained_artifact
    monkeypatch.setenv("SMSD_MODEL_SHA256", "0" * 64)
    with pytest.raises(ModelArtifactError, match="SHA-256 mismatch"):
        load_model(model_path)


def test_model_hash_verification_rejects_malformed_digest(trained_artifact, monkeypatch):
    _, model_path = trained_artifact
    monkeypatch.setenv("SMSD_MODEL_SHA256", "not-a-digest")
    with pytest.raises(ModelArtifactError, match="64-character hexadecimal"):
        load_model(model_path)


def test_newer_schema_fails_with_actionable_error(trained_artifact, tmp_path):
    artifact, _ = trained_artifact
    payload = dict(artifact)
    payload["artifact_schema_version"] = ARTIFACT_SCHEMA_VERSION + 1
    path = tmp_path / "newer.pkl"
    joblib.dump(payload, path)
    with pytest.raises(ModelArtifactError, match="newer than this code"):
        load_model(path)


def test_feature_version_mismatch_fails(trained_artifact, tmp_path):
    artifact, _ = trained_artifact
    payload = dict(artifact)
    payload["feature_version"] = "0.0.1"
    path = tmp_path / "old_features.pkl"
    joblib.dump(payload, path)
    with pytest.raises(ModelArtifactError, match="feature_version"):
        load_model(path)


def test_invalid_threshold_fails(trained_artifact, tmp_path):
    artifact, _ = trained_artifact
    payload = dict(artifact)
    payload["threshold"] = 1.5
    path = tmp_path / "bad_threshold.pkl"
    joblib.dump(payload, path)
    with pytest.raises(ModelArtifactError, match="threshold"):
        load_model(path)


def test_unsupported_object_fails_safely(tmp_path):
    path = tmp_path / "unsupported.pkl"
    joblib.dump({"hello": "world"}, path)
    with pytest.raises(ModelArtifactError, match="artifact_schema_version"):
        load_model(path)


def test_input_validation(trained_artifact):
    _, model_path = trained_artifact
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="blank"):
            analyze_message(bad, model_path=model_path)
    with pytest.raises(ValueError, match="maximum"):
        analyze_message("a" * 10_001, model_path=model_path)
    with pytest.raises(ValueError, match="iterable of strings"):
        analyze_messages(12345, model_path=model_path)
    with pytest.raises(ValueError, match="must be a string"):
        analyze_message(["not", "a", "string"], model_path=model_path)


def test_smsd_model_path_env_override(monkeypatch, trained_artifact):
    _, model_path = trained_artifact
    monkeypatch.setenv("SMSD_MODEL_PATH", str(model_path))
    bundle = load_model()
    assert bundle.threshold > 0


def test_training_is_reproducible(trained_artifact, tmp_path):
    artifact, _ = trained_artifact
    data_path = make_tiny_dataset(tmp_path / "reproducible_data.csv")
    second_path = tmp_path / "second.pkl"
    second = train(
        data_path=data_path,
        model_path=second_path,
        supplement_path=None,
        holdout_path=None,
        val_size=0.2,
        test_size=0.2,
        random_state=7,
        target_precision=0.5,
        min_recall=0.0,
        write_metadata=False,
        verbose=False,
    )
    assert second["threshold"] == pytest.approx(artifact["threshold"])
    assert second["split"] == artifact["split"]
    assert second["metrics"]["test_at_threshold"] == artifact["metrics"]["test_at_threshold"]


def test_artifact_metadata_does_not_retain_private_source_paths(tmp_path):
    import json

    private_dir = tmp_path / "participant-khang-private"
    private_dir.mkdir()
    data_path = make_tiny_dataset(private_dir / "khang_sms_messages.csv")
    artifact = train(
        data_path=data_path,
        model_path=tmp_path / "candidate.pkl",
        supplement_path=None,
        holdout_path=None,
        val_size=0.2,
        test_size=0.2,
        random_state=7,
        target_precision=0.5,
        min_recall=0.0,
        write_metadata=False,
        verbose=False,
    )
    metadata = {key: value for key, value in artifact.items() if key != "model"}
    serialized = json.dumps(metadata)

    assert "participant-khang-private" not in serialized
    assert "khang_sms_messages.csv" not in serialized
    assert artifact["data_sources"][0]["path"].startswith("base:")
    assert artifact["dataset"]["files"][0]["path"].startswith("base:")


@pytest.mark.parametrize("kind, expected", [("synthetic", True), ("unknown", None)])
def test_training_provenance_comes_from_declared_rows(tmp_path, kind, expected):
    import pandas as pd

    data_path = make_tiny_dataset(tmp_path / "declared.csv")
    frame = pd.read_csv(data_path)
    frame["data_kind"] = kind
    frame.to_csv(data_path, index=False)
    artifact = train(
        data_path=data_path,
        model_path=tmp_path / "model.pkl",
        supplement_path=None,
        holdout_path=None,
        val_size=0.2,
        test_size=0.2,
        random_state=7,
        target_precision=0.5,
        min_recall=0,
        verbose=False,
        write_metadata=False,
    )
    assert artifact["synthetic_training_data"] is expected
    assert set(artifact["training_data_kind_counts"]) == {kind}
    assert artifact["metrics"]["test_by_category"]
