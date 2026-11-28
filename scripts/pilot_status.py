"""Report consented-pilot coverage readiness against the ratified minimums.

Reads one or more intake-ready consented CSVs (private operator files, such as
the 0600 intake CSVs produced by ``scripts/label_import.py``) and reports,
message-free, how far the pooled data is from the sealed-test coverage
minimums ratified in ``docs/templates/consented-evaluation-plan.json``:
per-language rows (``en``/``tl``/``tl-en``), per-category rows
(``otp``/``bank_alert``/``delivery``), the three highest-count spam categories
(``spam_top3``, computed from the data on every run), distinct campaign
groups, and distinct donors (``consent_record_id`` values).

Readiness here means COVERAGE ONLY: the report states how many more rows or
groups the ratified minimums require. It is never an accuracy,
release-readiness, or safety assessment and never evaluates model quality.
Minimums are read from the plan at runtime (``--plan`` can point at a
re-ratified copy) so a future re-ratification flows through without code
changes. Language codes present in the data but absent from the plan's
``minimum_coverage.language`` keys are reported as a vocabulary warning --
never canonicalized (vocabulary re-ratification is an owner decision), so the
gap the ratified vocabulary produces stays visible.

Message-free discipline: stdout, the JSON report, and errors carry counts,
category/language codes, and notice text only -- never message text, sender
data, ``consent_record_id`` values, or ``group`` values. Before anything is
printed or written, the payload is scanned against the pooled inputs' message,
consent, and group values and refused if any appear (mirroring the report
safety check in ``scripts/label_import.py``). The validator in
``src/consented_data.py`` is never run here; the tool only reuses its public
header canonicalization helper so intake headers are interpreted identically.

The data is expected to be already intake-ready (validator-clean); this tool
does not re-check consent, retention, or de-identification, and it never
prints row values -- only counts, code names, and id-shape statistics.

Exit codes: 0 when every ratified minimum is met, 1 when at least one is not
(the coverage readiness signal), 2 for tool errors (unreadable input, missing
columns, invalid plan, unsafe output path) and for unexpected internal errors,
which are reduced to their exception-type name so no traceback reaches stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.consented_data import normalize_intake_columns
from src.dataset_schema import LABEL_ALIASES
from src.privacy.storage import ensure_private_directory

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "docs" / "templates" / "consented-evaluation-plan.json"

# Columns this tool reads from intake-ready CSVs. Everything else in the
# intake shape (including the optional received_at/labeling_confidence) is
# tolerated and ignored; the message column is used only for the duplicate
# warning and is never reported.
STATUS_COLUMNS = ("label", "category", "language", "group", "consent_record_id")
MESSAGE_COLUMN = "message"

SPAM_TOP3_KEY = "spam_top3"
SPAM_TOP3_SLOTS = 3
UNKNOWN_CODE = "unknown"
UNRECOGNIZED_LABEL = "unrecognized"

# The intake flow and the ratified plan may disagree on language vocabulary
# (for example the donate/worksheet flow emits "fil" while the plan keys on
# "tl"). Codes present in the data but absent from the plan are reported as a
# warning -- never canonicalized; vocabulary re-ratification is an owner
# decision, so a permanent coverage gap must stay visible instead of being
# silently papered over.
VOCABULARY_NOTE = "vocabulary re-ratification is an owner decision"

STATUS_MET = "minimums_met"
STATUS_BELOW = "below_minimum"
STATUS_ERROR = "error"

NOTICE = (
    "Coverage readiness against the ratified consented-evaluation-plan minimums only. "
    "This report is not an accuracy, release-readiness, or safety assessment and does not "
    "evaluate model quality."
)
LIMITATIONS = (
    "Rows are pooled across the supplied intake CSVs and counted as-is, including duplicates.",
    "Coverage is counted from the declared label, language, category, group, and "
    "consent_record_id columns; consent, retention, and de-identification are not re-checked here.",
    "Exit code 1 is a coverage readiness signal only; it never measures model quality.",
)


@dataclass(frozen=True)
class CoverageMinimums:
    """Ratified minimums read from the consented evaluation plan at runtime."""

    language: dict[str, int]
    category: dict[str, int]
    campaign_groups: int | None


@dataclass(frozen=True)
class PooledIntake:
    """Privacy-safe pooled counts over the operator's intake CSVs.

    ``forbidden`` holds the private values (message text, consent ids, group
    ids) used only to refuse unsafe reports; it is never serialized.
    """

    file_count: int
    messages: int
    donors: int
    campaign_groups: int
    languages: dict[str, int]
    categories: dict[str, int]
    labels: dict[str, int]
    spam_categories: dict[str, int]
    duplicate_messages: int
    duplicate_detection_applied: bool
    forbidden: tuple[str, ...]


def _read_intake_csv(path: str | Path) -> pd.DataFrame:
    """Read one intake CSV with repo-standard parsing; parse errors are sanitized."""
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"Could not read intake CSV {Path(path)} ({type(exc).__name__}).") from None
    try:
        return normalize_intake_columns(frame)
    except ValueError:
        raise ValueError(f"Intake CSV {Path(path)} has duplicate columns after normalization.") from None


def _normalized_codes(series: pd.Series) -> pd.Series:
    """Casefold categorical codes; blank values count under the shared unknown code."""
    return series.astype(str).str.strip().str.casefold().replace("", UNKNOWN_CODE)


def _value_counts(series: pd.Series) -> dict[str, int]:
    counts = _normalized_codes(series).value_counts()
    return {str(code): int(count) for code, count in sorted(counts.items())}


def _duplicate_message_count(values: pd.Series) -> int:
    """Count repeat rows under the intake duplicate key (NFKC, case, whitespace).

    Mirrors the normalized-message-key idea used at intake; duplicates are
    counted as-is everywhere else and only reported as a warning count.
    """
    seen: set[str] = set()
    duplicates = 0
    for value in values.astype(str):
        key = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
        if not key:
            continue
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def pool_intake(paths: Sequence[str | Path]) -> PooledIntake:
    """Pool the operator-supplied intake CSVs into privacy-safe counts."""
    if not paths:
        raise ValueError("At least one intake CSV path is required.")
    frames: list[pd.DataFrame] = []
    has_message = False
    for path in paths:
        frame = _read_intake_csv(path)
        missing = [column for column in STATUS_COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"Intake CSV {Path(path)} is missing required status columns: {', '.join(missing)}.")
        has_message = has_message or MESSAGE_COLUMN in frame.columns
        frames.append(frame.reindex(columns=[*STATUS_COLUMNS, MESSAGE_COLUMN]))
    pooled = pd.concat(frames, ignore_index=True).fillna("")

    consent_values = pooled["consent_record_id"].astype(str).str.strip().str.casefold()
    donors = int(consent_values[consent_values != ""].nunique())
    group_values = pooled["group"].astype(str).str.strip().str.casefold()
    campaign_groups = int(group_values[group_values != ""].nunique())

    raw_labels = pooled["label"].astype(str).str.strip().str.casefold()
    normalized_labels = raw_labels.map(LABEL_ALIASES)
    labels = {
        "ham": int((normalized_labels == "ham").sum()),
        "spam": int((normalized_labels == "spam").sum()),
        UNRECOGNIZED_LABEL: int(normalized_labels.isna().sum()),
    }
    languages = _value_counts(pooled["language"])
    categories = _value_counts(pooled["category"])
    spam_categories = _value_counts(pooled["category"][normalized_labels == "spam"])

    duplicate_messages = _duplicate_message_count(pooled[MESSAGE_COLUMN]) if has_message else 0

    private_sources = [pooled["consent_record_id"].astype(str), pooled["group"].astype(str)]
    if has_message:
        private_sources.append(pooled[MESSAGE_COLUMN].astype(str))
    forbidden = tuple(sorted({value.strip() for series in private_sources for value in series if value.strip()}))

    return PooledIntake(
        file_count=len(paths),
        messages=int(len(pooled)),
        donors=donors,
        campaign_groups=campaign_groups,
        languages=languages,
        categories=categories,
        labels=labels,
        spam_categories=spam_categories,
        duplicate_messages=duplicate_messages,
        duplicate_detection_applied=has_message,
        forbidden=forbidden,
    )


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Invalid {field} minimum in the coverage plan: expected a non-negative integer.")
    return int(value)


def _minimum_dict(coverage: dict[str, Any], key: str) -> dict[str, int]:
    raw = coverage.get(key)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"The coverage plan's minimum_coverage.{key} must be an object.")
    return {
        str(code): _positive_int(minimum, f"minimum_coverage.{key}.{code}")
        for code, minimum in raw.items()
        if minimum is not None
    }


def load_minimums(path: str | Path = DEFAULT_PLAN) -> CoverageMinimums:
    """Read the ratified coverage minimums from the plan JSON at runtime."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read the coverage minimums plan {Path(path)} ({type(exc).__name__}).") from None
    if not isinstance(payload, dict):
        raise ValueError("The coverage minimums plan must be a JSON object.")
    coverage = payload.get("minimum_coverage")
    if coverage is None:
        raise ValueError("The coverage minimums plan is missing the minimum_coverage object.")
    if not isinstance(coverage, dict):
        raise ValueError("The coverage plan's minimum_coverage must be an object.")
    raw_groups = payload.get("minimum_campaign_groups")
    campaign_groups = None if raw_groups is None else _positive_int(raw_groups, "minimum_campaign_groups")
    return CoverageMinimums(
        language=_minimum_dict(coverage, "language"),
        category=_minimum_dict(coverage, "category"),
        campaign_groups=campaign_groups,
    )


def _coverage_entry(count: int, minimum: int | None) -> dict[str, Any]:
    if minimum is None:
        return {"count": count, "minimum": None, "met": None, "needed": 0}
    return {"count": count, "minimum": minimum, "met": count >= minimum, "needed": max(0, minimum - count)}


def ranked_spam_categories(pooled: PooledIntake) -> list[dict[str, Any]]:
    """The highest-count spam categories by row count, computed from the data."""
    ranked = sorted(pooled.spam_categories.items(), key=lambda item: (-item[1], item[0]))
    return [{"category": code, "count": count} for code, count in ranked[:SPAM_TOP3_SLOTS]]


def build_report(pooled: PooledIntake, minimums: CoverageMinimums) -> dict[str, Any]:
    """Build the message-free coverage report; gaps drive the readiness exit code."""
    spam_top = ranked_spam_categories(pooled)
    spam_total = sum(item["count"] for item in spam_top)
    spam_minimum = minimums.category.get(SPAM_TOP3_KEY)

    language_coverage = {
        code: _coverage_entry(pooled.languages.get(code, 0), minimum) for code, minimum in minimums.language.items()
    }
    category_coverage = {
        code: _coverage_entry(pooled.categories.get(code, 0), minimum)
        for code, minimum in minimums.category.items()
        if code != SPAM_TOP3_KEY
    }
    spam_entry = {"categories": spam_top, **_coverage_entry(spam_total, spam_minimum)}
    groups_entry = _coverage_entry(pooled.campaign_groups, minimums.campaign_groups)

    gaps: list[dict[str, Any]] = []
    for dimension, entries in (("language", language_coverage), ("category", category_coverage)):
        for code, entry in entries.items():
            if entry["met"] is False:
                gaps.append(
                    {
                        "dimension": dimension,
                        "code": code,
                        "count": entry["count"],
                        "minimum": entry["minimum"],
                        "needed": entry["needed"],
                    }
                )
    if spam_entry["met"] is False:
        gaps.append(
            {
                "dimension": "category",
                "code": SPAM_TOP3_KEY,
                "count": spam_total,
                "minimum": spam_minimum,
                "needed": spam_entry["needed"],
            }
        )
    if groups_entry["met"] is False:
        gaps.append(
            {
                "dimension": "campaign_groups",
                "code": "campaign_groups",
                "count": pooled.campaign_groups,
                "minimum": minimums.campaign_groups,
                "needed": groups_entry["needed"],
            }
        )

    return {
        "report_kind": "pilot_coverage_status",
        "status": STATUS_BELOW if gaps else STATUS_MET,
        "notice": NOTICE,
        "inputs": {
            "file_count": pooled.file_count,
            "duplicate_detection_applied": pooled.duplicate_detection_applied,
        },
        "totals": {
            "messages": pooled.messages,
            "donors": pooled.donors,
            "campaign_groups": pooled.campaign_groups,
        },
        "labels": dict(pooled.labels),
        "counts": {
            "languages": dict(sorted(pooled.languages.items())),
            "categories": dict(sorted(pooled.categories.items())),
        },
        "coverage": {
            "language": language_coverage,
            "category": category_coverage,
            SPAM_TOP3_KEY: spam_entry,
            "campaign_groups": groups_entry,
        },
        "gaps": gaps,
        "warnings": {
            "duplicate_messages": pooled.duplicate_messages,
            "unrecognized_label_rows": pooled.labels[UNRECOGNIZED_LABEL],
            "languages_outside_plan": {
                "codes": sorted(code for code in pooled.languages if code not in minimums.language),
                "plan_keys": list(minimums.language),
                "note": VOCABULARY_NOTE,
            },
        },
        "limitations": list(LIMITATIONS),
    }


def _coverage_phrase(entry: dict[str, Any]) -> str:
    if entry["minimum"] is None or entry["met"] is None:
        return str(entry["count"])
    if entry["met"]:
        return f"{entry['count']}/{entry['minimum']} met"
    return f"{entry['count']}/{entry['minimum']} needed {entry['needed']}"


def _section_line(label: str, entries: dict[str, dict[str, Any]]) -> str:
    if not entries:
        return f"{label}: (none ratified)"
    return f"{label}: " + " | ".join(f"{code} {_coverage_phrase(entry)}" for code, entry in entries.items())


def format_summary(report: dict[str, Any]) -> str:
    """Human-readable, message-free stdout summary (counts and codes only)."""
    coverage = report["coverage"]
    totals = report["totals"]
    groups_line = f"Campaign groups: {totals['campaign_groups']}"
    if coverage["campaign_groups"]["minimum"] is not None:
        groups_line += f" (minimum {coverage['campaign_groups']['minimum']})"
    spam = coverage[SPAM_TOP3_KEY]
    spam_names = ", ".join(f"{item['category']} {item['count']}" for item in spam["categories"])
    warnings = report["warnings"]
    lines = [
        f"Pilot coverage status: {report['status']} (coverage readiness only)",
        f"Messages: {totals['messages']} | Donors: {totals['donors']} | {groups_line}",
        _section_line("Language coverage", coverage["language"]),
        _section_line("Category coverage", coverage["category"]),
        f"{SPAM_TOP3_KEY}: {_coverage_phrase(spam)}" + (f" ({spam_names})" if spam_names else ""),
        f"Gaps: {len(report['gaps'])}",
    ]
    for gap in report["gaps"]:
        lines.append(
            f"  {gap['dimension']} {gap['code']}: have {gap['count']}, minimum {gap['minimum']}, "
            f"still needed {gap['needed']}"
        )
    vocabulary = warnings["languages_outside_plan"]
    if vocabulary["codes"]:
        plan_keys = ", ".join(vocabulary["plan_keys"]) or "none ratified"
        lines.append(
            f"Language vocabulary warning: {', '.join(vocabulary['codes'])} "
            f"(plan keys: {plan_keys}) — {vocabulary['note']}."
        )
    lines.append(
        f"Warnings: duplicate_messages {warnings['duplicate_messages']} | "
        f"unrecognized_label_rows {warnings['unrecognized_label_rows']} | "
        f"languages_outside_plan {len(vocabulary['codes'])}"
    )
    lines.append(f"Notice: {NOTICE}")
    return "\n".join(lines)


def _assert_report_message_free(text: str, forbidden: tuple[str, ...]) -> None:
    """Refuse any report that carries message text, consent ids, or group values."""
    if any(value in text for value in forbidden):
        raise ValueError(
            "Refusing to emit a pilot status report containing message text, consent ids, or group values."
        )


def _validate_output_path(output: str | os.PathLike[str]) -> Path:
    """Mirror pilot_preflight/label_import: reject repo-tree paths, allow data/donations/."""
    destination = Path(output).expanduser().resolve()
    repository = ROOT.resolve()
    private_root = (repository / "data" / "donations").resolve()
    if repository in destination.parents and private_root not in destination.parents:
        raise ValueError("Status reports must be outside the repository or under ignored data/donations/ storage.")
    return destination


def write_report(report: dict[str, Any], output: str | os.PathLike[str], forbidden: tuple[str, ...]) -> Path:
    """Write the message-free JSON report outside the repository or under data/donations/."""
    destination = _validate_output_path(output)
    payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    _assert_report_message_free(payload, forbidden)
    ensure_private_directory(destination.parent)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(destination, 0o600)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "csv",
        type=Path,
        nargs="+",
        help="Intake-ready consented CSV(s), pooled for coverage counting; the files stay private.",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=DEFAULT_PLAN,
        help="Coverage minimums plan JSON (default: the ratified docs/templates copy).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report destination outside the repository or under ignored data/donations/ storage.",
    )
    args = parser.parse_args(argv)

    try:
        if args.output is not None:
            _validate_output_path(args.output)  # fail fast, before reading private files
        pooled = pool_intake(args.csv)
        minimums = load_minimums(args.plan)
        report = build_report(pooled, minimums)
        summary = format_summary(report)
        _assert_report_message_free(summary, pooled.forbidden)
        destination = write_report(report, args.output, pooled.forbidden) if args.output else None
    except (ValueError, OSError) as exc:
        payload = {"status": STATUS_ERROR, "detail": str(exc)}
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    except Exception as exc:
        # Reduce unexpected failures to the exception-type name only (same
        # pattern as the preflight checks) so no traceback or internal error
        # text can reach stderr.
        payload = {"status": STATUS_ERROR, "detail": f"unexpected_{type(exc).__name__}"}
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(summary)
    if destination is not None:
        print(f"Report written to {destination}")
    return 0 if report["status"] == STATUS_MET else 1


if __name__ == "__main__":
    sys.exit(main())
