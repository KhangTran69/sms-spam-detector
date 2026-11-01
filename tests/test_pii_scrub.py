from __future__ import annotations

import pytest

from src.privacy.scrub import detect_pii, redact


@pytest.mark.parametrize(
    "message, expected",
    [
        ("Call 09171234567 now", "09171234567"),
        ("Call +63 917 123 4567 now", "+63 917 123 4567"),
        ("Call 0917-123-4567 now", "0917-123-4567"),
    ],
)
def test_detects_ph_mobile_formats(message, expected):
    spans = detect_pii(message)
    assert [(span.category, span.value) for span in spans] == [("phone", expected)]


@pytest.mark.parametrize("number", ["12345678901", "123456789012", "123-456-78901"])
def test_strict_mode_flags_long_numeric_runs(number):
    spans = detect_pii(f"Reference {number}")
    assert len(spans) == 1
    assert spans[0].category == "numeric_id"
    assert spans[0].value == number


def test_otp_code_is_personal_even_when_short():
    spans = detect_pii("Your OTP is 493821. Do not share it.")
    assert [(span.category, span.value) for span in spans] == [("otp", "493821")]


def test_detects_email_urls_and_short_links_but_redaction_preserves_urls():
    message = "Contact khang@example.ph or click https://bit.ly/claim-now."
    spans = detect_pii(message)

    assert [(span.category, span.value) for span in spans] == [
        ("email", "khang@example.ph"),
        ("url", "https://bit.ly/claim-now"),
    ]
    assert redact(message) == "Contact [REDACTED] or click https://bit.ly/claim-now."


def test_detects_government_id_and_account_number_context():
    message = "SSS No: 12-3456789-0; GCash account: 1234567890"
    spans = detect_pii(message)
    assert [(span.category, span.value) for span in spans] == [
        ("government_id", "12-3456789-0"),
        ("account_number", "1234567890"),
    ]


def test_overlapping_phone_and_numeric_matches_coalesce_to_one_phone_span():
    spans = detect_pii("09171234567")
    assert len(spans) == 1
    assert spans[0].category == "phone"
    assert spans[0].value == "09171234567"


def test_strictness_controls_unlabeled_long_numeric_runs():
    assert detect_pii("Order 12345678901", strict=False) == []
    assert detect_pii("Account no 12345678901", strict=False)[0].category == "account_number"


def test_span_offsets_and_non_pii_controls():
    message = "OTP: 493821; due 2026-11-01; pay ₱500"
    span = detect_pii(message)[0]
    assert message[span.start : span.end] == span.value == "493821"
    assert detect_pii("Meet me at 5pm; total is ₱500 on 2026-11-01") == []
