from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main

NOTICE_VERSION = "2026-11-01-v4"
VALID_PAYLOAD = {
    "message": "Synthetic donation fixture: please review this message",
    "label_hint": "spam",
    "language": "tl",
    "consent": True,
    "authorized_to_share": True,
    "model_research_consent": False,
    "notice_version": NOTICE_VERSION,
}


@contextmanager
def donation_client(
    tmp_path: Path,
    *,
    enabled: bool = True,
    rate_limit: int = 5,
    operator_contact: str = "local@example.test",
    client_host: str = "127.0.0.1",
    environment: str = "development",
):
    state = {
        "enabled": api_main.DONATIONS_ENABLED,
        "path": api_main.DONATION_DB_PATH,
        "limit": api_main.DONATION_RATE_LIMIT_PER_MINUTE,
        "notice": api_main.DONATION_NOTICE_VERSION,
        "contact": api_main.DONATIONS_OPERATOR_CONTACT,
        "environment": api_main.SMSD_ENV,
    }
    api_main.DONATIONS_ENABLED = enabled
    api_main.DONATION_DB_PATH = tmp_path / "donations.sqlite3"
    api_main.DONATION_RATE_LIMIT_PER_MINUTE = rate_limit
    api_main.DONATIONS_OPERATOR_CONTACT = operator_contact
    api_main.SMSD_ENV = environment
    api_main._reset_rate_limits()
    try:
        with TestClient(api_main.app, client=(client_host, 12345)) as client:
            yield client
    finally:
        api_main.DONATIONS_ENABLED = state["enabled"]
        api_main.DONATION_DB_PATH = state["path"]
        api_main.DONATION_RATE_LIMIT_PER_MINUTE = state["limit"]
        api_main.DONATION_NOTICE_VERSION = state["notice"]
        api_main.DONATIONS_OPERATOR_CONTACT = state["contact"]
        api_main.SMSD_ENV = state["environment"]
        api_main._reset_rate_limits()


def test_donation_routes_are_disabled_by_default_and_form_not_served(tmp_path):
    with donation_client(tmp_path, enabled=False) as client:
        assert client.get("/donate").status_code == 404
        assert client.post("/donate", json=VALID_PAYLOAD).status_code == 404

    assert not (tmp_path / "donations.sqlite3").exists()


def test_operator_contact_is_required_before_collection_can_be_enabled(tmp_path):
    with donation_client(tmp_path, enabled=True, operator_contact="") as client:
        assert client.get("/donate").status_code == 404
        assert client.post("/donate", json=VALID_PAYLOAD).status_code == 404

    assert not (tmp_path / "donations.sqlite3").exists()


def test_donation_intake_is_local_only_and_disabled_in_production(tmp_path):
    with donation_client(tmp_path / "remote", client_host="203.0.113.20") as client:
        assert client.get("/donate").status_code == 404
        assert client.post("/donate", json=VALID_PAYLOAD).status_code == 404
    with donation_client(tmp_path / "production", environment="production") as client:
        assert client.get("/donate").status_code == 404
        assert client.post("/donate", json=VALID_PAYLOAD).status_code == 404

    assert not list(tmp_path.rglob("donations.sqlite3"))


def test_enabled_form_and_notice_escape_the_operator_contact(tmp_path):
    contact = '</strong><script>alert("x")</script>'
    with donation_client(tmp_path, operator_contact=contact) as client:
        form = client.get("/donate")
        notice = client.get("/privacy-notice")

    escaped = "&lt;/strong&gt;&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"
    assert form.status_code == notice.status_code == 200
    assert form.headers["cache-control"] == "no-store"
    assert notice.headers["cache-control"] == "no-cache"
    assert int(form.headers["content-length"]) == len(form.content)
    assert int(notice.headers["content-length"]) == len(notice.content)
    assert escaped in form.text
    assert '<script>alert("x")</script>' not in form.text
    assert escaped in notice.text


@pytest.mark.parametrize(
    "payload",
    [
        {key: value for key, value in VALID_PAYLOAD.items() if key != "consent"},
        {**VALID_PAYLOAD, "consent": False},
    ],
)
def test_missing_or_false_consent_is_rejected_without_storage(tmp_path, payload):
    with donation_client(tmp_path) as client:
        response = client.post("/donate", json=payload)

    assert response.status_code in {400, 422}
    assert not (tmp_path / "donations.sqlite3").exists()


@pytest.mark.parametrize(
    "payload",
    [
        {key: value for key, value in VALID_PAYLOAD.items() if key != "authorized_to_share"},
        {**VALID_PAYLOAD, "authorized_to_share": False},
    ],
)
def test_missing_or_false_authorization_is_rejected_without_storage(tmp_path, payload):
    with donation_client(tmp_path) as client:
        response = client.post("/donate", json=payload)

    assert response.status_code in {400, 422}
    assert not (tmp_path / "donations.sqlite3").exists()


def test_stale_notice_version_is_rejected(tmp_path):
    with donation_client(tmp_path) as client:
        response = client.post("/donate", json={**VALID_PAYLOAD, "notice_version": "older-notice"})

    assert response.status_code == 409
    assert not (tmp_path / "donations.sqlite3").exists()


def test_contact_fields_are_rejected_and_unknown_withdrawals_do_not_enumerate(tmp_path):
    with donation_client(tmp_path) as client:
        contact_field = client.post("/donate", json={**VALID_PAYLOAD, "phone_number": "09170000000"})
        unknown = client.request("DELETE", "/donate", json={"record_id": "a" * 32})
        malformed = client.request("DELETE", "/donate", json={"record_id": "not-a-record-id"})
        legacy_path = client.delete("/donate/" + "a" * 32)

    assert contact_field.status_code == 422
    assert contact_field.headers["cache-control"] == "no-store"
    assert VALID_PAYLOAD["message"] not in contact_field.text
    assert unknown.status_code == malformed.status_code == 200
    assert unknown.json() == malformed.json() == {"status": "withdrawn"}
    assert legacy_path.status_code == 404, "withdrawal capabilities must not be accepted in URL paths"


def test_pii_rejection_returns_flagged_spans_without_logging_or_storing_text(tmp_path, caplog):
    private_text = "Your OTP is 493821. Call 09171234567"
    with donation_client(tmp_path) as client:
        response = client.post("/donate", json={**VALID_PAYLOAD, "message": private_text})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "pii_detected"
    assert {span["category"] for span in response.json()["error"]["details"]} >= {"otp", "phone"}
    assert private_text not in caplog.text
    assert not (tmp_path / "donations.sqlite3").exists()


def test_content_type_is_checked_and_validation_does_not_echo_text(tmp_path):
    with donation_client(tmp_path) as client:
        response = client.post(
            "/donate",
            content=json.dumps(VALID_PAYLOAD),
            headers={"content-type": "text/plain"},
        )

    assert response.status_code == 415
    assert VALID_PAYLOAD["message"] not in response.text
    assert not (tmp_path / "donations.sqlite3").exists()


def test_acceptance_and_withdrawal_are_explicit_non_cached_and_idempotent(tmp_path):
    with donation_client(tmp_path) as client:
        accepted = client.post("/donate", json=VALID_PAYLOAD)
        assert accepted.status_code == 201
        assert accepted.headers["cache-control"] == "no-store"
        record_id = accepted.json()["record_id"]
        with closing(sqlite3.connect(tmp_path / "donations.sqlite3")) as connection, connection:
            assert connection.execute("SELECT message FROM donations").fetchone()[0] == VALID_PAYLOAD["message"]
            assert connection.execute(
                "SELECT review_consent, model_research_consent, authorized_to_share FROM donations"
            ).fetchone() == (1, 0, 1)

        first = client.request("DELETE", "/donate", json={"record_id": record_id})
        second = client.request("DELETE", "/donate", json={"record_id": record_id})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"status": "withdrawn"}
    with closing(sqlite3.connect(tmp_path / "donations.sqlite3")) as connection, connection:
        assert connection.execute("SELECT message FROM donations").fetchone()[0] == ""


def test_donation_request_logs_redact_client_address_and_withdrawal_token(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="api.main")
    with donation_client(tmp_path) as client:
        accepted = client.post("/donate", json=VALID_PAYLOAD)
        withdrawal_id = accepted.json()["record_id"]
        client.request("DELETE", "/donate", json={"record_id": withdrawal_id})

    assert withdrawal_id not in caplog.text
    assert "127.0.0.1" not in caplog.text
    assert '"path": "/donate"' in caplog.text


def test_donation_rate_limit_uses_existing_middleware(tmp_path):
    with donation_client(tmp_path, rate_limit=1) as client:
        first = client.post("/donate", json=VALID_PAYLOAD)
        second = client.post("/donate", json=VALID_PAYLOAD)

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert int(second.headers["Retry-After"]) > 0


def test_v1_donation_alias_uses_the_same_rate_limit(tmp_path):
    with donation_client(tmp_path, rate_limit=1) as client:
        first = client.post("/v1/donate", json=VALID_PAYLOAD)
        second = client.post("/v1/donate", json=VALID_PAYLOAD)

    assert first.status_code == 201
    assert second.status_code == 429


def test_model_research_consent_is_a_separate_optional_choice(tmp_path):
    with donation_client(tmp_path) as client:
        accepted = client.post("/donate", json={**VALID_PAYLOAD, "model_research_consent": True})

    assert accepted.status_code == 201
    with closing(sqlite3.connect(tmp_path / "donations.sqlite3")) as connection, connection:
        assert connection.execute("SELECT review_consent, model_research_consent FROM donations").fetchone() == (
            1,
            1,
        )
