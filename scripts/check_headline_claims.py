"""Guard public-facing headings against unsupported performance assertions.

Only Markdown headings and HTML titles/H1 elements are inspected. Findings
include file/line locations but never echo the matched headline text.
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = (
    ROOT / "README.md",
    ROOT / "docs" / "MODEL_CARD.md",
    ROOT / "api" / "web" / "index.html",
)
MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
CLAIM_PATTERNS = (
    re.compile(r"\b\d+(?:\.\d+)?\s?%\s*(?:accurate|accuracy|precision|recall|f1)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:proven|guaranteed|validated|certified)\b[^.!?]{0,50}"
        r"\b(?:accuracy|accurate|safe|fraud probability|scam probability)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:real[- ]world|philippine|filipino)\s+(?:accuracy|performance)\b", re.IGNORECASE),
    re.compile(r"\b(?:fraud|scam)\s+probability\b", re.IGNORECASE),
    re.compile(r"\b(?:accurate|reliable)\s+(?:philippine|filipino|real[- ]world)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:(?:highly|very|demonstrably|exceptionally)\s+)?(?:accurate|reliable)\s+"
        r"(?:sms|spam|scam|smishing|phishing)\s+(?:detector|filter|classifier)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:high|excellent|strong|exceptional)\s+(?:accuracy|precision|recall|performance)\b", re.IGNORECASE),
)
EXPLICIT_DISCLAIMER_PATTERNS = (
    re.compile(
        r"\bno\s+(?:(?:verified|proven|validated|established|measured|supported)\s+)?"
        r"(?:real[- ]world|philippine|filipino)\s+(?:accuracy|performance)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bno\s+(?:credible\s+)?(?:evidence|data|estimate)\s+(?:of|for)\s+"
        r"(?:real[- ]world|philippine|filipino)\s+(?:accuracy|performance)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:real[- ]world|philippine|filipino)\s+(?:accuracy|performance)\s+"
        r"(?:is|remains)\s+(?:not\s+(?:established|proven|validated|known|available)|"
        r"unproven|unvalidated|unknown|unavailable)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:real[- ]world|philippine|filipino)\s+(?:accuracy|performance)\s+"
        r"has\s+not\s+been\s+(?:established|proven|validated|measured)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:no|not|never)\s+(?:(?:a|an)\s+)?"
        r"(?:(?:highly|very|demonstrably|exceptionally)\s+)?"
        r"(?:accurate|reliable)\s+(?:sms|spam|scam|smishing|phishing)\s+"
        r"(?:detector|filter|classifier)\b",
        re.IGNORECASE,
    ),
)


class _HtmlHeadlines(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headlines: list[tuple[int, str]] = []
        self._active_tag: str | None = None
        self._active_line = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"title", "h1"} and self._active_tag is None:
            self._active_tag = tag
            self._active_line = self.getpos()[0]
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._active_tag is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._active_tag:
            self.headlines.append((self._active_line, " ".join(" ".join(self._parts).split())))
            self._active_tag = None
            self._parts = []


def _headlines(path: Path, text: str) -> list[tuple[int, str]]:
    if path.suffix.casefold() == ".md":
        headlines: list[tuple[int, str]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = MARKDOWN_HEADING_RE.match(line)
            if match:
                headlines.append((line_number, match.group(1).strip()))
        return headlines
    parser = _HtmlHeadlines()
    parser.feed(text)
    return parser.headlines


def _unsupported_claim(headline: str) -> bool:
    for pattern in CLAIM_PATTERNS:
        for match in pattern.finditer(headline):
            if not any(
                disclaimer.start() <= match.start() and disclaimer.end() >= match.end()
                for disclaimer_pattern in EXPLICIT_DISCLAIMER_PATTERNS
                for disclaimer in disclaimer_pattern.finditer(headline)
            ):
                return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", type=Path, help="Markdown or HTML files; defaults to public project headlines"
    )
    args = parser.parse_args(argv)
    paths = args.paths or list(DEFAULT_FILES)
    findings = 0
    for path in paths:
        if path.suffix.casefold() not in {".md", ".html"}:
            print(f"error: unsupported headline file type: {path}", file=sys.stderr)
            return 2
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot read headline file ({type(exc).__name__}): {path}", file=sys.stderr)
            return 2
        for line_number, headline in _headlines(path, text):
            if _unsupported_claim(headline):
                findings += 1
                print(f"unsupported performance claim: {path}:{line_number}", file=sys.stderr)
    if findings:
        return 1
    print(f"Headline evidence check passed ({len(paths)} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
