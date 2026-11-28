from __future__ import annotations

import json

import pytest

from scripts.deployment_preflight import main, review

VALID = {
    "SMSD_ENV": "production",
    "SMSD_MODEL_SHA256": "a" * 64,
    "SMSD_METRICS_TOKEN": "fixture-private-token-" + "b" * 20,
    "SMSD_REDIS_URL": "redis://fixture:secret@localhost:6379/0",
    "SMSD_CORS_ORIGINS": "https://fixture.example.test",
}


def test_offline_public_configuration_review_never_claims_gateway_verification(monkeypatch, capsys):
    for name, value in VALID.items():
        monkeypatch.setenv(name, value)
    assert review(VALID, workers=2, gateway_confirmed=True) == []
    assert main(["--workers", "2", "--gateway-confirmed"]) == 0
    raw = capsys.readouterr().out
    assert json.loads(raw) == {
        "configuration_findings": [],
        "gateway_verified": False,
        "deployment_authorized": False,
    }
    assert "secret" not in raw and VALID["SMSD_METRICS_TOKEN"] not in raw


@pytest.mark.parametrize(
    ("name", "value", "finding"),
    [
        ("SMSD_ENV", "development", "production_mode_required"),
        ("SMSD_DONATIONS_ENABLED", "true", "donations_must_be_disabled"),
        ("SMSD_FEEDBACK_ENABLED", "true", "feedback_must_be_disabled"),
        ("SMSD_ALLOW_LEGACY_MODEL", "true", "legacy_model_override_forbidden"),
        ("SMSD_MODEL_SHA256", "invalid", "independent_model_digest_required"),
        ("SMSD_METRICS_TOKEN", "short", "operator_metrics_token_required"),
        ("SMSD_REDIS_URL", "http://localhost:6379", "shared_rate_limiter_required"),
        ("SMSD_REDIS_URL", "redis://localhost:invalid", "shared_rate_limiter_required"),
        ("SMSD_RATE_LIMIT_FAILURE_MODE", "open", "fail_closed_rate_limiting_required"),
        ("SMSD_MAX_IN_FLIGHT_WRITES", "-1", "invalid_smsd_max_in_flight_writes"),
        ("SMSD_RATE_LIMIT_PER_MINUTE", "bad", "invalid_smsd_rate_limit_per_minute"),
        ("SMSD_BODY_TIMEOUT_SECONDS", "nan", "invalid_body_deadline"),
        ("SMSD_CORS_ORIGINS", "*", "invalid_public_cors_origin"),
        ("SMSD_CORS_ORIGINS", "https://fixture.example.test/path", "invalid_public_cors_origin"),
    ],
)
def test_configuration_findings_are_specific_and_value_free(name, value, finding):
    assert review({**VALID, name: value}, workers=2, gateway_confirmed=True) == [finding]


def test_gateway_attestation_and_worker_count_are_required():
    assert review(VALID, workers=0, gateway_confirmed=False) == [
        "gateway_attestation_required",
        "invalid_worker_count",
    ]
