"""Preprocessing edge cases: Philippine phones, URLs, money, Taglish, Unicode."""

from __future__ import annotations

import pytest

from src.preprocess import (
    MAX_MESSAGE_LENGTH,
    PHONE_RE,
    URL_RE,
    clean_text,
    extract_features,
    extract_matches,
    normalize_taglish,
    prepare_message,
    prepare_messages,
    redact_message,
)


def test_philippine_indicators():
    text = "Claim ₱500 now at https://example.ph or call 09123456789"
    features = extract_features(text)
    assert features["has_url"] == 1
    assert features["has_phone"] == 1
    assert features["has_money"] == 1
    assert features["has_urgency"] == 1


def test_clean_text_normalizes_and_preserves_marker():
    assert "moneytoken" in clean_text("₱500,000!!!")
    assert clean_text("  Kamusta   ka? ") == "kamusta ka"


def test_masked_phone_numbers_are_detected():
    for text in (
        "Text your name and address to 0922xxxxxxx",
        "Claim using 0917******* today",
        "I-send sa +63917xxxxxxx",
        "Call 0917•••••••",
    ):
        assert extract_features(text)["has_phone"] == 1, text


def test_ph_mobile_and_landline_formats():
    for text in (
        "Call 09171234567",
        "+63 917 123 4567",
        "0917-123-4567",
        "639171234567",
        "Not you? Call (02) 8-631-8000.",
        "Landline: 02 8631 8000",
        "Landline: (032) 123-4567",
        "Landline: 032-123-4567",
    ):
        assert extract_features(text)["has_phone"] == 1, text


def test_phone_regex_rejects_short_codes_years_and_long_numbers():
    assert extract_features("Your OTP is 583920. Do not share.")["has_phone"] == 0
    assert extract_features("Happy new year 2026!")["has_phone"] == 0
    assert extract_features("Order reference 123456789012")["has_phone"] == 0


def test_money_variants():
    for text in (
        "₱500,000",
        "PHP 1,250.00",
        "Php 5,000",
        "500 pesos",
        "P15,000.00 refund",
        "₱1M from PCSO",
        "1.5M pesos",
        "PHP 5k salary",
    ):
        assert extract_features(text)["has_money"] == 1, text


def test_money_regex_ignores_plain_numbers():
    assert extract_features("Order 1234567890 shipped")["has_money"] == 0
    assert extract_features("Tip 50 for the rider")["has_money"] == 0


def test_urgency_terms_include_taglish_and_phrases():
    for word in ("now", "agad", "kaagad", "ngayon", "limited", "expires", "bilisan", "within 24 hours"):
        assert extract_features(f"Claim your prize {word}! ")["has_urgency"] == 1, word
    for text in ("Claim your prize tomorrow.", "Knowledge is power", "nowhere to be found"):
        assert extract_features(text)["has_urgency"] == 0, text


def test_legit_otp_has_no_phone_or_money():
    features = extract_features("Your BDO OTP is 583920. Do not share this code.")
    assert features["has_phone"] == 0
    assert features["has_money"] == 0


def test_bare_domains_and_malformed_urls():
    for text in (
        "Verify at bit.ly/fakebdo",
        "Track at jtexpress.ph/track",
        "Pay at phlpost-clearance.top before Nov 2",
        "Visit www.example.com",
        "Open example.com/path",
        "https://example.ph/x",
    ):
        assert extract_features(text)["has_url"] == 1, text
    for text in ("This is e.g. a sample", "The U.S. dollar", "Meet on Oct. 18", "http://", "www."):
        assert extract_features(text)["has_url"] == 0, text


def test_url_digits_do_not_trigger_phone_or_money():
    features = extract_features("Visit http://x.com/09171234567/500 now")
    assert features["has_url"] == 1
    assert features["has_phone"] == 0
    assert features["has_money"] == 0


def test_brand_terms_are_word_bounded():
    assert extract_features("BDO account locked")["has_brand"] == 1
    assert extract_features("GCash cash in")["has_brand"] == 1
    assert extract_features("J&T Express parcel")["has_brand"] == 1
    assert extract_features("grab a coffee")["has_brand"] == 0


def test_length_and_capital_ratio():
    features = extract_features("HELLO WORLD")
    assert features["message_length"] == len("HELLO WORLD")
    assert features["capital_ratio"] == 1.0
    assert extract_features("hello world")["capital_ratio"] == 0.0
    assert extract_features("12345!!")["capital_ratio"] == 0.0


def test_normalize_taglish_squeezes_elongation():
    assert normalize_taglish("napakaaa ganda") == "napakaa ganda"
    assert normalize_taglish("salamat po") == "salamat po"


def test_normalize_handles_unicode_fullwidth_html_and_control_chars():
    assert normalize_taglish("ＨＥＬＬＯ") == "HELLO"
    assert normalize_taglish("BDO &amp; GCash") == "BDO & GCash"
    assert "\u200b" not in normalize_taglish("safe\u200btext")
    assert "\x00" not in normalize_taglish("safe\x00text")
    assert "ñ" in normalize_taglish("mañana")


def test_clean_text_replaces_all_marker_types():
    cleaned = clean_text("BDO locked! Verify http://bit.ly/x or call 09171234567 re: ₱500")
    assert "urltoken" in cleaned and "phonetoken" in cleaned and "moneytoken" in cleaned
    assert "http" not in cleaned and "0917" not in cleaned


def test_extract_matches_offsets_slice_original():
    message = "Verify at http://bit.ly/fake now, call 09171234567 agad"
    matches = extract_matches(message)
    assert {"url", "urgency", "phone"} <= {match["type"] for match in matches}
    for match in matches:
        assert message[match["start"] : match["end"]] == match["text"]


def test_extract_matches_trims_url_trailing_punctuation():
    message = "Visit http://example.com."
    url = next(match for match in extract_matches(message) if match["type"] == "url")
    assert url["text"] == "http://example.com"


def test_extract_matches_url_swallows_embedded_phone():
    message = "Go to http://example.com/09171234567"
    matches = extract_matches(message)
    assert [match["type"] for match in matches] == ["url"]


def test_extract_matches_money_and_unicode_offsets():
    message = "Win ₱500,000 now!"
    matches = extract_matches(message)
    money = next(match for match in matches if match["type"] == "money")
    assert message[money["start"] : money["end"]] == "₱500,000"
    urgency = next(match for match in matches if match["type"] == "urgency")
    assert urgency["text"] == "now"


def test_extract_matches_brands_are_lowercased_text_but_offsets_exact():
    matches = extract_matches("BDO and GCash alert")
    brand_texts = [match["text"] for match in matches if match["type"] == "brand"]
    assert brand_texts == ["BDO", "GCash"]


def test_prepare_messages_schema_and_consistency():
    messages = ["Claim ₱500 now", "Salamat po"]
    rows = prepare_messages(messages)
    assert len(rows) == 2
    assert set(rows[0]) == set(prepare_message(messages[0]))
    assert rows[0]["cleaned_text"].count("moneytoken") == 1


def test_redact_message_removes_sensitive_content():
    redacted = redact_message("Call 09171234567 or visit http://bit.ly/x about ₱500,000")
    assert "09171234567" not in redacted
    assert "bit.ly" not in redacted
    assert "500,000" not in redacted
    assert "[PHONE]" in redacted and "[URL]" in redacted and "[AMOUNT]" in redacted


def test_max_message_length_constant_is_sane():
    assert MAX_MESSAGE_LENGTH >= 1000


def test_phone_regex_does_not_match_month_or_year():
    assert not PHONE_RE.search("Valid until Nov 18.")
    assert not PHONE_RE.search("Reference 20261019")


@pytest.mark.parametrize("url", ["hxxps://example.com/login", "bit[.]ly/prize", "bit(.)ly/track"])
def test_obfuscated_urls_are_signals_with_original_offsets(url):
    message = f"😀 Check {url}."
    matches = [match for match in extract_matches(message) if match["type"] == "url"]
    assert len(matches) == 1
    assert matches[0]["text"] == url
    assert message[matches[0]["start"] : matches[0]["end"]] == url
    assert extract_features(message)["has_url"] == 1
    assert "urltoken" in clean_text(message)


def test_bare_domain_does_not_match_partial_suffix():
    assert not URL_RE.search("example.company")
    assert not URL_RE.search("example.com-extra")
