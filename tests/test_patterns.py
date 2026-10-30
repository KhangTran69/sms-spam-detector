"""Unit tests for centralized pattern definitions in src.patterns."""

from __future__ import annotations

import re

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
    MONEY_RE,
    PHONE_RE,
    URGENCY_RE,
    URGENCY_TERMS,
    URL_RE,
)


def test_patterns_are_compiled_regexes():
    assert isinstance(URL_RE, re.Pattern)
    assert isinstance(PHONE_RE, re.Pattern)
    assert isinstance(MONEY_RE, re.Pattern)
    assert isinstance(URGENCY_RE, re.Pattern)
    assert isinstance(BRAND_RE, re.Pattern)
    assert isinstance(INVISIBLE_CHARS_RE, re.Pattern)


def test_pattern_terms_and_mappings_non_empty():
    assert len(BRAND_TERMS) > 20
    assert len(URGENCY_TERMS) > 10
    assert len(FEATURE_KEYS) == 7
    assert len(HOMOGLYPH_TABLE) > 30
    assert len(LEETSPEAK_MAP) > 5
    assert len(FILIPINO_STOPWORDS) > 30
    assert len(ENGLISH_STOPWORDS) > 30
    assert len(MATCH_PATTERNS) == 4
