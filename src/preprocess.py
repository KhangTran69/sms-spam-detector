"""Text normalization and lightweight Philippine SMS indicator extraction."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
PHONE_RE = re.compile(
    # PH mobile: 0917 123 4567 / 0917-123-4567 / +63 917 123 4567
    r"(?<!\w)(?:\+?63|0)\s?\d{3}[\s-]?\d{3}[\s-]?\d{4}(?!\w)"
    # masked mobile: 0922xxxxxxx / 0917*******
    r"|(?<!\w)(?:\+?63|0)\s?\d{3}[\s-]?[xX*•]{3,}(?!\w)"
    # PH landline: (02) 8-631-8000
    r"|(?<!\w)\(\s*0\d\s*\)\s?\d{1,3}[\s-]?\d{3}[\s-]?\d{4}(?!\w)"
    # bare 10-11 digit strings (digit-only contact numbers)
    r"|(?<!\w)\d{10,11}(?!\w)",
    re.IGNORECASE,
)
MONEY_RE = re.compile(
    r"(?:₱\s?\d[\d,]*(?:\.\d+)?"
    r"|\bPHP\s?\d[\d,]*(?:\.\d+)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:pesos?|php)\b"
    r"|\b[Pp]\s?\d[\d,]*(?:\.\d+)?(?!\w))",
    re.IGNORECASE,
)
URGENCY_TERMS = ("now", "agad", "limited", "expires")

# Recognizable banks, e-wallets, services and agencies commonly impersonated in
# Philippine scam texts. Ambiguous words (grab, smart, sun, dito) are excluded on
# purpose so ordinary words never fire the brand signal.
BRAND_TERMS = (
    "bdo", "bpi", "metrobank", "unionbank", "rcbc", "pnb", "landbank",
    "gcash", "maya", "paymaya", "shopeepay", "shopee", "lazada", "foodpanda",
    "lbc", "j&t", "philpost", "meralco", "maynilad", "pldt", "globe",
    "pcso", "dswd", "sss", "philhealth", "lto", "pag-ibig", "gma",
    "netflix", "paypal", "facebook", "samsung", "iphone", "cebuana",
)
BRAND_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in sorted(BRAND_TERMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Priority for overlapping signals: a URL swallows the digits inside it, a phone
# number beats an overlapping money amount, and so on.
_MATCH_PATTERNS = (("url", URL_RE), ("phone", PHONE_RE), ("money", MONEY_RE), ("brand", BRAND_RE))


def normalize_taglish(text: str) -> str:
    """Normalize common spelling variants without translating Tagalog/Taglish."""
    text = unicodedata.normalize("NFKC", str(text))
    # Preserve meaningful Filipino words and diacritics; normalize common elongation
    # (e.g. "napakaaa" -> "napakaa") so TF-IDF sees consistent tokens.
    text = re.sub(r"([a-z])\1{2,}", r"\1\1", text, flags=re.IGNORECASE)
    return text


def clean_text(text: str) -> str:
    """Return a model-ready string while retaining URL/amount/phone tokens."""
    text = normalize_taglish(text)
    text = URL_RE.sub(" URLTOKEN ", text)
    text = MONEY_RE.sub(" MONEYTOKEN ", text)
    text = PHONE_RE.sub(" PHONETOKEN ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().lower()


def extract_features(message: str) -> dict[str, float]:
    """Extract interpretable binary and numeric message indicators."""
    message = str(message)
    letters = [c for c in message if c.isalpha()]
    lowered = message.lower()
    return {
        "has_url": float(bool(URL_RE.search(message))),
        "has_phone": float(bool(PHONE_RE.search(message))),
        "has_money": float(bool(MONEY_RE.search(message))),
        "has_urgency": float(any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in URGENCY_TERMS)),
        "has_brand": float(bool(BRAND_RE.search(message))),
        "message_length": float(len(message)),
        "capital_ratio": float(sum(c.isupper() for c in letters) / len(letters)) if letters else 0.0,
    }


def extract_matches(message: str) -> list[dict]:
    """Locate signal spans (url/phone/money/urgency/brand) for UI highlighting.

    Overlapping matches are resolved by start position, then length, then the
    priority order above, so a phone number inside a URL is reported once as
    part of the URL only.
    """
    message = str(message)
    candidates: list[dict] = []
    for priority, (kind, pattern) in enumerate(_MATCH_PATTERNS):
        for m in pattern.finditer(message):
            candidates.append(
                {"type": kind, "text": m.group(0), "start": m.start(), "end": m.end(), "_priority": priority}
            )
    for m in re.finditer(
        r"\b(?:" + "|".join(re.escape(word) for word in URGENCY_TERMS) + r")\b", message, flags=re.IGNORECASE
    ):
        candidates.append({"type": "urgency", "text": m.group(0), "start": m.start(), "end": m.end(), "_priority": 4})
    candidates.sort(key=lambda c: (c["start"], -(c["end"] - c["start"]), c["_priority"]))
    matches: list[dict] = []
    last_end = 0
    for candidate in candidates:
        if candidate["start"] >= last_end:
            matches.append({key: candidate[key] for key in ("type", "text", "start", "end")})
            last_end = candidate["end"]
    return matches


def prepare_message(message: str) -> dict[str, Any]:
    """Create the one-row DataFrame schema used by training and inference."""
    from src.features import FEATURE_COLUMNS
    return {"cleaned_text": clean_text(message), **extract_features(message)}
