from src.preprocess import clean_text, extract_features, normalize_taglish


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
    ):
        assert extract_features(text)["has_phone"] == 1, text


def test_ph_mobile_and_landline_formats():
    for text in (
        "Call 09171234567",
        "+63 917 123 4567",
        "0917-123-4567",
        "Not you? Call (02) 8-631-8000.",
    ):
        assert extract_features(text)["has_phone"] == 1, text


def test_money_variants():
    for text in ("₱500,000", "PHP 1,250.00", "500 pesos", "P15,000.00 refund", "₱1M from PCSO"):
        assert extract_features(text)["has_money"] == 1, text


def test_urgency_terms_include_taglish():
    for word in ("now", "agad", "limited", "expires"):
        assert extract_features(f"Claim your prize {word}! ")["has_urgency"] == 1, word
    assert extract_features("Claim your prize tomorrow.")["has_urgency"] == 0


def test_legit_otp_has_no_phone_or_money():
    features = extract_features("Your BDO OTP is 583920. Do not share this code.")
    assert features["has_phone"] == 0
    assert features["has_money"] == 0


def test_length_and_capital_ratio():
    features = extract_features("HELLO WORLD")
    assert features["message_length"] == len("HELLO WORLD")
    assert features["capital_ratio"] == 1.0
    assert extract_features("hello world")["capital_ratio"] == 0.0
    assert extract_features("12345!!")["capital_ratio"] == 0.0


def test_normalize_taglish_squeezes_elongation():
    assert normalize_taglish("napakaaa ganda") == "napakaa ganda"
    assert normalize_taglish("salamat po") == "salamat po"


def test_clean_text_replaces_all_marker_types():
    cleaned = clean_text("BDO locked! Verify http://bit.ly/x or call 09171234567 re: ₱500")
    assert "urltoken" in cleaned and "phonetoken" in cleaned and "moneytoken" in cleaned
    assert "http" not in cleaned and "0917" not in cleaned
