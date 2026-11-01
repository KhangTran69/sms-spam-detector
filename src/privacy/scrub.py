"""Conservative PII span detection for local consented-message intake."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.patterns import URL_RE, URL_TRAILING

PH_MOBILE_RE = re.compile(r"(?<![\w])(?:\+?63[\s().-]*9\d{2}|09\d{2})[\s().-]*\d{3}[\s().-]*\d{4}(?!\w)")
LONG_NUMERIC_RE = re.compile(r"(?<![\w])\d(?:[\d -]{8,}\d)(?![\w])")
SHORT_NUMERIC_RE = re.compile(r"(?<!\d)\d{4,8}(?!\d)")
EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SHORT_LINK_RE = re.compile(
    r"(?i)(?<![\w@])(?:bit\.ly|t\.co|tinyurl\.com|goo\.gl|is\.gd|ow\.ly|cutt\.ly|shorturl\.at)"
    r"(?:/[^\s<>\"'`]*)?"
)
OTP_CONTEXT_RE = re.compile(r"(?i)\b(?:otp|one[- ]time(?:\s+password)?|verification(?:\s+code)?|security\s+code|pin)\b")
GOVERNMENT_ID_RE = re.compile(
    r"(?i)\b(?:tin|sss|umid|philhealth(?:\s+pin)?|pag-?ibig|gsis|passport)\b"
    r"(?:\s*(?:pin|id|no\.?|number|#))?\s*[:#-]?\s*(?P<value>\d(?:[\d -]{5,22}\d))(?!\w)"
)
ACCOUNT_NUMBER_RE = re.compile(
    r"(?i)\b(?:bank\s+account|account(?:\s+(?:number|no\.?))?|acct(?:\s*(?:no\.?|#))?|"
    r"gcash\s+account|maya\s+account)\b\s*[:#-]?\s*(?P<value>\d(?:[\d -]{5,22}\d))(?!\w)"
)
PLACEHOLDER_NUMBERS = frozenset({"00000000000", "000000000000", "11111111111", "111111111111"})
PLACEHOLDER_CONTEXT_RE = re.compile(r"(?i)\b(?:example|placeholder|sample)\b")

_PRIORITY = {
    "url": 0,
    "email": 1,
    "phone": 2,
    "government_id": 3,
    "account_number": 4,
    "otp": 5,
    "numeric_id": 6,
}


@dataclass(frozen=True)
class Span:
    """A detected PII span using Python string offsets and its exact value."""

    start: int
    end: int
    category: str
    value: str


def _add_match(candidates: list[tuple[int, int, str]], start: int, end: int, category: str) -> None:
    if end > start:
        candidates.append((start, end, category))


def _add_urls(text: str, candidates: list[tuple[int, int, str]]) -> None:
    for match in URL_RE.finditer(text):
        end = match.end()
        while end > match.start() and text[end - 1] in URL_TRAILING:
            end -= 1
        _add_match(candidates, match.start(), end, "url")
    for match in SHORT_LINK_RE.finditer(text):
        end = match.end()
        while end > match.start() and text[end - 1] in URL_TRAILING:
            end -= 1
        _add_match(candidates, match.start(), end, "url")


def _candidate_spans(text: str, *, strict: bool) -> list[Span]:
    candidates: list[tuple[int, int, str]] = []

    _add_urls(text, candidates)
    for match in EMAIL_RE.finditer(text):
        _add_match(candidates, match.start(), match.end(), "email")
    for match in PH_MOBILE_RE.finditer(text):
        _add_match(candidates, match.start(), match.end(), "phone")
    for pattern, category in ((GOVERNMENT_ID_RE, "government_id"), (ACCOUNT_NUMBER_RE, "account_number")):
        for match in pattern.finditer(text):
            start, end = match.span("value")
            _add_match(candidates, start, end, category)

    for match in SHORT_NUMERIC_RE.finditer(text):
        start, end = match.span()
        context = text[max(0, start - 28) : min(len(text), end + 28)]
        if OTP_CONTEXT_RE.search(context):
            _add_match(candidates, start, end, "otp")

    if strict:
        for match in LONG_NUMERIC_RE.finditer(text):
            value = match.group()
            digit_count = sum(character.isdigit() for character in value)
            if digit_count not in {11, 12}:
                continue
            start, end = match.span()
            context = text[max(0, start - 28) : min(len(text), end + 28)]
            digits = "".join(character for character in value if character.isdigit())
            if digits in PLACEHOLDER_NUMBERS and PLACEHOLDER_CONTEXT_RE.search(context):
                continue
            _add_match(candidates, start, end, "numeric_id")

    # Prefer the most specific, longest span. Nested detections collapse to
    # the containing span; partial overlaps are coalesced to avoid leaving a
    # fragment of an identifier exposed after redaction.
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0]), _PRIORITY[item[2]]))
    selected: list[Span] = []
    selected_priority: list[int] = []
    for start, end, category in candidates:
        if selected and start < selected[-1].end:
            current = selected[-1]
            if end <= current.end:
                continue
            merged_end = max(end, current.end)
            merged_category = current.category if selected_priority[-1] <= _PRIORITY[category] else category
            selected[-1] = Span(current.start, merged_end, merged_category, text[current.start : merged_end])
            selected_priority[-1] = min(selected_priority[-1], _PRIORITY[category])
            continue
        selected.append(Span(start, end, category, text[start:end]))
        selected_priority.append(_PRIORITY[category])
    return selected


def detect_pii(text: str, *, strict: bool = True) -> list[Span]:
    """Return detected PII spans; strict mode also flags unlabelled long numbers."""
    if not isinstance(text, str) or not text:
        return []
    return _candidate_spans(text, strict=strict)


def redact(text: str, *, replacement: str = "[REDACTED]", strict: bool = True) -> str:
    """Redact detected spans, leaving URLs intact so they remain reviewable signals."""
    result = text
    spans = detect_pii(text, strict=strict)
    for span in reversed(spans):
        if span.category == "url":
            continue
        result = result[: span.start] + replacement + result[span.end :]
    return result
