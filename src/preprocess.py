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

# Hard limit shared by the API/CLI. Defaults to 10,000 characters; configurable via SMSD_MAX_MESSAGE_LENGTH.
MAX_MESSAGE_LENGTH = int(os.environ.get("SMSD_MAX_MESSAGE_LENGTH", "10000"))

# Bare domains are common in Philippine SMS ("bit.ly/x", "jtexpress.ph/track").
# Only well-known TLDs are matched so abbreviations such as "e.g." and "U.S."
# do not become links.
_URL_TLDS = (
    "com",
    "net",
    "org",
    "ph",
    "info",
    "xyz",
    "online",
    "site",
    "top",
    "link",
    "ly",
    "gl",
    "me",
    "co",
    "io",
    "app",
    "shop",
    "click",
    "icu",
    "buzz",
    "rest",
    "dev",
    "live",
    "cloud",
    "store",
    "tech",
    "pro",
    "vip",
    "cc",
    "ws",
)
_URL_TLD_RE = "(?:" + "|".join(_URL_TLDS) + ")"

URL_RE = re.compile(
    r"(?i)(?<![\w@])(?:"
    r"h(?:tt|xx)ps?://[^\s<>\"'`]+"
    r"|www\.[^\s<>\"'`]+"
    r"|(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.|\[\.\]|\(\.\)))+"
    + _URL_TLD_RE
    + r"(?![\w-]|\.[a-z])(?:/[^\s<>\"'`]*)?"
    r")"
)

# Trailing sentence punctuation is not part of a link. The broad URL_RE above
# intentionally keeps matching simple; this helper trims display/extraction
# spans (clean_text only needs to replace the whole match with a marker).
_URL_TRAILING = ".,;:!?)]}>'\"`"

PHONE_RE = re.compile(
    r"(?i)(?<!\w)(?:"
    # Mobile: 0917 123 4567 / 0917-123-4567 / +63 917 123 4567 / 639171234567
    r"(?:\+?63|0)[\s.-]?9\d{2}[\s.-]?\d{3}[\s.-]?\d{4}"
    # Masked mobile: 0922xxxxxxx / 0917******* / +63917xxxxxxx
    r"|(?:\+?63|0)[\s.-]?\d{3}[\s.-]?[x*•·#]{3,}"
    # Landline with area code in parentheses: (02) 8-631-8000, (032) 123-4567.
    # Subscriber numbers are 7 digits (provincial) or 8 (Metro Manila).
    r"|\(\s*0\d{1,2}\s*\)[\s.-]?(?:\d[\s.-]?\d{3}[\s.-]?\d{4}|\d{4}[\s.-]?\d{4}|\d{3}[\s.-]?\d{4})"
    # Landline without parentheses: 02 8631 8000, 032-123-4567, 02 86318000
    r"|(?<!\w)0[2-9]\d?[\s.-]?\d{3,4}[\s.-]?\d{4}(?!\w)"
    # Bare 10-11 digit contact number
    r"|(?<!\w)\d{10,11}(?!\w)"
    r")(?!\w)"
)

_MONEY_NUM = r"\d[\d,]*(?:\.\d+)?"
MONEY_RE = re.compile(
    r"(?i)(?:"
    r"₱\s?" + _MONEY_NUM + r"(?:\s?[kKmM](?![a-zA-Z]))?"
    r"|\bPHP\s?" + _MONEY_NUM + r"(?:\s?[kKmM](?![a-zA-Z]))?"
    r"|\b" + _MONEY_NUM + r"\s?(?:pesos?|php)\b"
    r"|\b[Pp]\s?" + _MONEY_NUM + r"(?!\w)"
    r"|\b" + _MONEY_NUM + r"\s?[kKmM]\s?(?:pesos?|php)\b"
    r")"
)

# Urgency is a weak signal: legitimate OTPs say "expires", bills say "due".
# Kept intentionally small so ordinary Tagalog words are not mislabelled.
URGENCY_TERMS: tuple[str, ...] = (
    "now",
    "agad",
    "kaagad",
    "ngayon",
    "limited",
    "expires",
    "expire",
    "today",
    "immediately",
    "urgent",
    "hurry",
    "last chance",
    "huling",
    "bilisan",
    "within 24 hours",
    "bago mag",
)
_URGENCY_RE = re.compile(r"(?i)\b(?:" + "|".join(re.escape(term) for term in URGENCY_TERMS) + r")\b")

# Recognizable banks, e-wallets, services and agencies commonly impersonated in
# Philippine scam texts. Ambiguous words (grab, smart, sun, dito) are excluded on
# purpose so ordinary words never fire the brand signal.
BRAND_TERMS: tuple[str, ...] = (
    "bdo",
    "bpi",
    "metrobank",
    "unionbank",
    "rcbc",
    "pnb",
    "landbank",
    "chinabank",
    "gcash",
    "maya",
    "paymaya",
    "shopeepay",
    "shopee",
    "lazada",
    "foodpanda",
    "lbc",
    "j&t",
    "philpost",
    "ninjavan",
    "flash express",
    "2go",
    "meralco",
    "maynilad",
    "manila water",
    "pldt",
    "globe",
    "pcso",
    "dswd",
    "sss",
    "philhealth",
    "lto",
    "pag-ibig",
    "gma",
    "netflix",
    "paypal",
    "facebook",
    "samsung",
    "iphone",
    "cebuana",
)
BRAND_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in sorted(BRAND_TERMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Priority for overlapping signals: a URL swallows the digits inside it, a phone
# number beats an overlapping money amount, and so on.
_MATCH_PATTERNS = (("url", URL_RE), ("phone", PHONE_RE), ("money", MONEY_RE), ("brand", BRAND_RE))

_FEATURE_KEYS = (
    "has_url",
    "has_phone",
    "has_money",
    "has_urgency",
    "has_brand",
    "message_length",
    "capital_ratio",
)

# Invisible, zero-width, and directional formatting characters frequently inserted to evade keyword filters.
_INVISIBLE_CHARS_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\u3164\ufeff\ufe0f]")

# Cyrillic and Greek homoglyphs used to spoof Latin characters (e.g. Cyrillic 'а' or 'о' in brand/scam names).
_HOMOGLYPH_TABLE = str.maketrans(
    {
        # Cyrillic lowercase lookalikes
        "а": "a",
        "с": "c",
        "е": "e",
        "о": "o",
        "р": "p",
        "х": "x",
        "у": "y",
        "і": "i",
        "ј": "j",
        "ԁ": "d",
        "ѕ": "s",
        "ѵ": "v",
        "ԝ": "w",
        # Cyrillic uppercase lookalikes
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "І": "I",
        "Ј": "J",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Ѕ": "S",
        "Т": "T",
        "Х": "X",
        "Ү": "Y",
        # Greek lowercase & uppercase lookalikes
        "α": "a",
        "ο": "o",
        "ν": "v",
        "ρ": "p",
        "τ": "t",
        "χ": "x",
        "Α": "A",
        "Β": "B",
        "Ε": "E",
        "Ζ": "Z",
        "Η": "H",
        "Ι": "I",
        "Κ": "K",
        "Μ": "M",
        "Ν": "N",
        "Ο": "O",
        "Ρ": "P",
        "Τ": "T",
        "Υ": "Y",
        "Χ": "X",
    }
)

# Targeted SMS leetspeak substitutions commonly used by spammers.
_LEETSPEAK_MAP = (
    (re.compile(r"(?i)\bfr[3e][3e]\b"), "free"),
    (re.compile(r"(?i)\bw[1i]n\b"), "win"),
    (re.compile(r"(?i)\bcl[1i]ck\b"), "click"),
    (re.compile(r"(?i)\bpr[1i]z[3e]\b"), "prize"),
    (re.compile(r"(?i)\bc[4a]sh\b"), "cash"),
    (re.compile(r"(?i)\bcl[4a][1i]m\b"), "claim"),
    (re.compile(r"(?i)\burg[3e]nt\b"), "urgent"),
)


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


_FILIPINO_STOPWORDS = frozenset(
    {
        "ang",
        "mga",
        "ng",
        "sa",
        "kay",
        "si",
        "ni",
        "ito",
        "iyan",
        "iyon",
        "dito",
        "doon",
        "po",
        "opo",
        "na",
        "ba",
        "pa",
        "din",
        "rin",
        "ako",
        "ikaw",
        "ka",
        "kami",
        "tayo",
        "kayo",
        "sila",
        "namin",
        "natin",
        "nila",
        "ko",
        "mo",
        "niya",
        "para",
        "dahil",
        "pero",
        "kung",
        "at",
        "may",
        "meron",
        "wala",
        "lahat",
        "bago",
        "pag",
        "sana",
        "pala",
        "naman",
        "lang",
        "lamang",
        "gusto",
        "salamat",
        "kamusta",
        "kumusta",
        "ingat",
        "uwi",
        "punta",
        "kain",
        "tulog",
        "bahay",
        "araw",
        "oras",
        "kahapon",
        "bukas",
        "ngayon",
        "agad",
        "kaagad",
        "bilisan",
        "huling",
        "panalo",
    }
)

_ENGLISH_STOPWORDS = frozenset(
    {
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "can",
        "could",
        "you",
        "your",
        "yours",
        "we",
        "our",
        "ours",
        "they",
        "their",
        "them",
        "he",
        "she",
        "it",
        "his",
        "her",
        "its",
        "this",
        "that",
        "these",
        "those",
        "from",
        "with",
        "about",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "of",
        "and",
        "or",
        "but",
        "if",
        "because",
        "as",
        "until",
        "while",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "any",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "please",
        "call",
        "text",
        "account",
        "click",
        "claim",
        "free",
        "winner",
        "prize",
        "code",
        "congratulations",
    }
)


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
