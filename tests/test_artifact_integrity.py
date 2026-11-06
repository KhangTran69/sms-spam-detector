from __future__ import annotations

import hashlib
import json

import pytest

from src.artifact_integrity import ArtifactIntegrityError, main, verify_artifact_sidecar


def test_sidecar_hash_verifies_exact_artifact_bytes(tmp_path):
    model_path = tmp_path / "model.pkl"
    model_bytes = b"synthetic fixture artifact"
    model_path.write_bytes(model_bytes)
    model_path.with_suffix(".metadata.json").write_text(
        json.dumps({"artifact_sha256": hashlib.sha256(model_bytes).hexdigest()}), encoding="utf-8"
    )

    digest, warning = verify_artifact_sidecar(model_path, model_bytes)

    assert digest == hashlib.sha256(model_bytes).hexdigest()
    assert warning is None


def test_sidecar_hash_mismatch_fails_closed(tmp_path):
    model_path = tmp_path / "model.pkl"
    model_path.write_bytes(b"synthetic fixture artifact")
    model_path.with_suffix(".metadata.json").write_text(json.dumps({"artifact_sha256": "0" * 64}))

    with pytest.raises(ArtifactIntegrityError, match="sidecar SHA-256 mismatch"):
        verify_artifact_sidecar(model_path, model_path.read_bytes())


def test_missing_legacy_hash_warns_unless_required(tmp_path):
    model_path = tmp_path / "legacy.pkl"
    model_path.write_bytes(b"synthetic fixture artifact")
    model_path.with_suffix(".metadata.json").write_text(json.dumps({"model_version": "legacy"}))

    digest, warning = verify_artifact_sidecar(model_path, model_path.read_bytes())
    assert digest == hashlib.sha256(model_path.read_bytes()).hexdigest()
    assert warning and "legacy bundle" in warning

    with pytest.raises(ArtifactIntegrityError, match="does not contain artifact_sha256"):
        verify_artifact_sidecar(model_path, model_path.read_bytes(), require_hash=True)


def test_invalid_sidecar_json_fails_closed(tmp_path):
    model_path = tmp_path / "model.pkl"
    model_bytes = b"synthetic fixture artifact"
    model_path.write_bytes(model_bytes)
    model_path.with_suffix(".metadata.json").write_text("{invalid", encoding="utf-8")

    with pytest.raises(ArtifactIntegrityError, match="not valid JSON"):
        verify_artifact_sidecar(model_path, model_bytes)


def test_non_utf8_sidecar_fails_closed(tmp_path):
    model_path = tmp_path / "model.pkl"
    model_bytes = b"synthetic fixture artifact"
    model_path.write_bytes(model_bytes)
    model_path.with_suffix(".metadata.json").write_bytes(b"\xff\xfe")

    with pytest.raises(ArtifactIntegrityError, match="UTF-8"):
        verify_artifact_sidecar(model_path, model_bytes)


def test_release_cli_requires_matching_hash_without_loading_pickle(tmp_path, capsys):
    model_path = tmp_path / "model.pkl"
    model_bytes = b"synthetic fixture artifact"
    model_path.write_bytes(model_bytes)
    model_path.with_suffix(".metadata.json").write_text(
        json.dumps({"artifact_sha256": hashlib.sha256(model_bytes).hexdigest()}), encoding="utf-8"
    )

    assert main([str(model_path)]) == 0
    assert "Verified model artifact SHA-256" in capsys.readouterr().out
