"""Centralized regex patterns, vocabulary signals, and lexical markers.

Extracts regular expressions and token sets into a single module to eliminate
duplication, ensure single-compilation efficiency across modules, and facilitate
testing and UI synchronization.
"""

from __future__ import annotations

import re

# Bare domains are common in Philippine SMS ("bit.ly/x", "jtexpress.ph/track").
# Only well-known TLDs are matched so abbreviations such as "e.g." and "U.S."
# do not become links.
URL_TLDS: tuple[str, ...] = (
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
URL_TLD_RE = "(?:" + "|".join(URL_TLDS) + ")"

URL_RE = re.compile(
    r"(?i)(?<![\w@])(?:"
    r"h(?:tt|xx)ps?://[^\s<>\"'`]+"
    r"|www\.[^\s<>\"'`]+"
    r"|(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.|\[\.\]|\(\.\)))+"
    + URL_TLD_RE
    + r"(?![\w-]|\.[a-z])(?:/[^\s<>\"'`]*)?"
    r")"
)

# Trailing sentence punctuation is not part of a link.
URL_TRAILING = ".,;:!?)]}>'\"`"

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

MONEY_NUM = r"\d[\d,]*(?:\.\d+)?"
MONEY_RE = re.compile(
    r"(?i)(?:"
    r"₱\s?" + MONEY_NUM + r"(?:\s?[kKmM](?![a-zA-Z]))?"
    r"|\bPHP\s?" + MONEY_NUM + r"(?:\s?[kKmM](?![a-zA-Z]))?"
    r"|\b" + MONEY_NUM + r"\s?(?:pesos?|php)\b"
    r"|\b[Pp]\s?" + MONEY_NUM + r"(?!\w)"
    r"|\b" + MONEY_NUM + r"\s?[kKmM]\s?(?:pesos?|php)\b"
    r")"
)

# Urgency keywords: common Philippine and English urgent phrases.
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
URGENCY_RE = re.compile(r"(?i)\b(?:" + "|".join(re.escape(term) for term in URGENCY_TERMS) + r")\b")

# Recognizable banks, e-wallets, delivery services, and utilities.
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

# Priority for overlapping signals.
MATCH_PATTERNS = (("url", URL_RE), ("phone", PHONE_RE), ("money", MONEY_RE), ("brand", BRAND_RE))

FEATURE_KEYS = (
    "has_url",
    "has_phone",
    "has_money",
    "has_urgency",
    "has_brand",
    "message_length",
    "capital_ratio",
)

# Invisible, zero-width, and directional formatting characters.
INVISIBLE_CHARS_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\u3164\ufeff\ufe0f]")

# Cyrillic and Greek homoglyphs used to spoof Latin characters.
HOMOGLYPH_TABLE = str.maketrans(
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
LEETSPEAK_MAP = (
    (re.compile(r"(?i)\bfr[3e][3e]\b"), "free"),
    (re.compile(r"(?i)\bw[1i]n\b"), "win"),
    (re.compile(r"(?i)\bcl[1i]ck\b"), "click"),
    (re.compile(r"(?i)\bpr[1i]z[3e]\b"), "prize"),
    (re.compile(r"(?i)\bc[4a]sh\b"), "cash"),
    (re.compile(r"(?i)\bcl[4a][1i]m\b"), "claim"),
    (re.compile(r"(?i)\burg[3e]nt\b"), "urgent"),
)

FILIPINO_STOPWORDS = frozenset(
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

ENGLISH_STOPWORDS = frozenset(
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
