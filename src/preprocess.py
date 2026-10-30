"""Text normalization and lightweight Philippine SMS indicator extraction.

The module deliberately stays rule-based and interpretable: regexes locate
signals, while the trained classifier decides how much each signal matters.
No single signal (a link, an amount, or an urgency word) is treated as proof of
a scam here.

Everything that training, the CLI, and the API send to the model goes through
:func:`prepare_message`, so cleaning/normalization is identical everywhere.
"""

from __future__ import annotations

import html
import os
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from src.patterns import (
    BRAND_RE,
    BRAND_TERMS,
    ENGLISH_STOPWORDS,
    FEATURE_KEYS,
    FILIPINO_STOPWORDS,
    HOMOGLYPH_TABLE,
    INVISIBLE_CHARS_RE,
    LEETSPEAK_MAP,
    MATCH_PATTERNS,
    MONEY_NUM,
    MONEY_RE,
    PHONE_RE,
    URGENCY_RE,
    URGENCY_TERMS,
    URL_RE,
    URL_TLD_RE,
    URL_TLDS,
    URL_TRAILING,
)

# Hard limit shared by the API/CLI. Defaults to 10,000 characters; configurable via SMSD_MAX_MESSAGE_LENGTH.
MAX_MESSAGE_LENGTH = int(os.environ.get("SMSD_MAX_MESSAGE_LENGTH", "10000"))

# Backwards-compatible aliases
_URL_TLDS = URL_TLDS
_URL_TLD_RE = URL_TLD_RE
_URL_TRAILING = URL_TRAILING
_MONEY_NUM = MONEY_NUM
_URGENCY_RE = URGENCY_RE
_URGENCY_TERMS = URGENCY_TERMS
_BRAND_TERMS = BRAND_TERMS
_MATCH_PATTERNS = MATCH_PATTERNS
_FEATURE_KEYS = FEATURE_KEYS
_INVISIBLE_CHARS_RE = INVISIBLE_CHARS_RE
_HOMOGLYPH_TABLE = HOMOGLYPH_TABLE
_LEETSPEAK_MAP = LEETSPEAK_MAP
_FILIPINO_STOPWORDS = FILIPINO_STOPWORDS
_ENGLISH_STOPWORDS = ENGLISH_STOPWORDS


def normalize_taglish(text: str) -> str:
    """Normalize Unicode and common spelling variants without translating text.

    - NFKC composes full-width characters and currency glyph variants.
    - Zero-width, directional, and invisible formatting characters are removed.
    - Cyrillic and Greek homoglyphs used to bypass keyword filters are mapped to Latin.
    - Common scam/spam leetspeak terms (e.g. fr33, cl1ck, w1n) are normalized.
    - HTML entities are unescaped for messages pasted from web pages.
    - Repeated letters are squeezed from 3+ to 2 so "napakaaa" and "napakaa"
      tokenize the same, while keeping genuine Filipino words/diacritics.
    """
    text = unicodedata.normalize("NFKC", str(text))
    text = html.unescape(text)
    text = text.replace("\u00a0", " ")
    text = _INVISIBLE_CHARS_RE.sub("", text)
    text = text.translate(_HOMOGLYPH_TABLE)
    for pattern, replacement in _LEETSPEAK_MAP:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
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


def _without_urls(text: str) -> str:
    """Mask URLs before scanning for phones/amounts (a URL's digits are not a
    contact number or a peso amount)."""
    return URL_RE.sub(" ", text)


def extract_features(message: str) -> dict[str, float]:
    """Extract interpretable binary and numeric message indicators."""
    message = str(message)
    normalized = normalize_taglish(message)
    normalized_lowered = normalized.lower()
    letters = [char for char in message if char.isalpha()]
    text_without_urls = _without_urls(message)
    return {
        "has_url": float(bool(URL_RE.search(message) or URL_RE.search(normalized))),
        "has_phone": float(bool(PHONE_RE.search(text_without_urls))),
        "has_money": float(bool(MONEY_RE.search(text_without_urls))),
        "has_urgency": float(bool(_URGENCY_RE.search(normalized_lowered))),
        "has_brand": float(bool(BRAND_RE.search(message) or BRAND_RE.search(normalized))),
        "message_length": float(len(message)),
        "capital_ratio": float(sum(char.isupper() for char in letters) / len(letters)) if letters else 0.0,
    }


def _trim_end(message: str, start: int, end: int) -> int:
    """Drop trailing punctuation/whitespace from a URL match span."""
    while end > start and message[end - 1] in _URL_TRAILING:
        end -= 1
    return end


def extract_matches(message: str) -> list[dict]:
    """Locate signal spans (url/phone/money/urgency/brand) for UI highlighting.

    Offsets are character offsets into the *original* message so clients can
    highlight without re-parsing. Overlapping matches are resolved by start
    position, then length, then the priority order above, so a phone number
    inside a URL is reported once as part of the URL only.
    """
    message = str(message)
    candidates: list[dict] = []
    for priority, (kind, pattern) in enumerate(_MATCH_PATTERNS):
        for match in pattern.finditer(message):
            start, end = match.start(), match.end()
            if kind == "url":
                end = _trim_end(message, start, end)
                if end <= start:
                    continue
            candidates.append(
                {"type": kind, "text": message[start:end], "start": start, "end": end, "_priority": priority}
            )
    for match in _URGENCY_RE.finditer(message):
        candidates.append(
            {
                "type": "urgency",
                "text": match.group(0),
                "start": match.start(),
                "end": match.end(),
                "_priority": len(_MATCH_PATTERNS),
            }
        )
    candidates.sort(
        key=lambda candidate: (candidate["start"], -(candidate["end"] - candidate["start"]), candidate["_priority"])
    )
    matches: list[dict] = []
    last_end = 0
    for candidate in candidates:
        if candidate["start"] >= last_end:
            matches.append({key: candidate[key] for key in ("type", "text", "start", "end")})
            last_end = candidate["end"]
    return matches


def prepare_message(message: str) -> dict[str, Any]:
    """Create the one-row mapping schema used by training and inference."""
    return {"cleaned_text": clean_text(message), **extract_features(message)}


def prepare_messages(messages: Iterable[str]) -> list[dict[str, Any]]:
    """Prepare several messages at once (same schema as :func:`prepare_message`)."""
    return [prepare_message(message) for message in messages]


def redact_message(message: str, *, max_length: int = 80) -> str:
    """Return a privacy-safe preview for logs/docs (no full message text).

    Used by evaluation output and diagnostics so real-world messages are not
    copied into logs or committed evaluation artifacts.
    """
    text = normalize_taglish(message)
    text = URL_RE.sub("[URL]", text)
    text = MONEY_RE.sub("[AMOUNT]", text)
    text = PHONE_RE.sub("[PHONE]", text)
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


def detect_language(text: str) -> str:
    """Classify text into 'english', 'filipino', 'taglish', or 'unknown' using lexical markers."""
    words = re.findall(r"\b[a-zA-ZñÑ]+\b", str(text).lower())
    if not words:
        return "unknown"
    fil_hits = sum(1 for w in words if w in _FILIPINO_STOPWORDS)
    eng_hits = sum(1 for w in words if w in _ENGLISH_STOPWORDS)
    if fil_hits == 0 and eng_hits == 0:
        return "english"
    if fil_hits > 0 and eng_hits > 0:
        return "taglish"
    if fil_hits > 0:
        return "filipino"
    return "english"
