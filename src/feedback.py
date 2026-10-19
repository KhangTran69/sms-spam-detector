"""Privacy-preserving inspection of anonymous correction reports.

Reports contain only selected labels and metadata. This module deliberately
refuses records with free-text fields and only emits aggregate counts; it never
exports report IDs or timestamps into the summary.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_REPORTS = Path(__file__).resolve().parents[1] / "data" / "feedback" / "reports.jsonl"
VALID_LABELS = {"ham", "spam"}
FEEDBACK_CATEGORIES = {"otp", "bank_alert", "delivery", "personal", "prize_scam", "phishing", "other"}
FORBIDDEN_TEXT_KEYS = {"message", "text", "sms", "body", "content", "phone", "sender"}
ALLOWED_KEYS = {
    "report_id",
    "created_at",
    "model_version",
    "server_model_version",
    "predicted_label",
    "expected_label",
    "category",
}


class FeedbackDataError(ValueError):
    """Invalid or privacy-unsafe report queue."""


def load_reports(path: str | Path = DEFAULT_REPORTS) -> list[dict[str, Any]]:
    report_path = Path(path)
    if not report_path.exists():
        return []
    if report_path.is_dir():
        raise FeedbackDataError(f"Feedback path is a directory: {report_path}")
    reports: list[dict[str, Any]] = []
    for line_number, line in enumerate(report_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            report = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FeedbackDataError(f"Invalid JSON on feedback line {line_number}.") from exc
        if not isinstance(report, dict):
            raise FeedbackDataError(f"Feedback line {line_number} must be a JSON object.")
        keys = set(report)
        unsafe = sorted(keys & FORBIDDEN_TEXT_KEYS)
        unknown = sorted(keys - ALLOWED_KEYS)
        if unsafe or unknown:
            raise FeedbackDataError(
                f"Feedback line {line_number} contains unsupported fields "
                f"(free-text={unsafe}, unknown={unknown}); do not print or export this record."
            )
        if report.get("predicted_label") not in VALID_LABELS or report.get("expected_label") not in VALID_LABELS:
            raise FeedbackDataError(f"Feedback line {line_number} has an invalid label.")
        if report["predicted_label"] == report["expected_label"]:
            raise FeedbackDataError(f"Feedback line {line_number} is not a correction (labels match).")
        if report.get("category") not in FEEDBACK_CATEGORIES:
            raise FeedbackDataError(f"Feedback line {line_number} has an invalid category.")
        reports.append(report)
    return reports


def summarize_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Return aggregate counts only; omit report identifiers and timestamps."""
    by_issue = Counter(f"{report['predicted_label']}->{report['expected_label']}" for report in reports)
    by_category = Counter(str(report["category"]) for report in reports)
    by_model = Counter(str(report["server_model_version"] or "unknown") for report in reports)
    return {
        "report_count": len(reports),
        "label_corrections": dict(sorted(by_issue.items())),
        "categories": dict(sorted(by_category.items())),
        "server_model_versions": dict(sorted(by_model.items())),
        "message_text_included": False,
        "training_labels_verified": False,
        "next_step": "Review aggregate patterns; verify any separately consented and redacted sample before labeling or retraining.",
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize privacy-preserving SMS detector feedback.")
    parser.add_argument("--path", default=str(DEFAULT_REPORTS), help="JSONL feedback queue path.")
    parser.add_argument("--output", default=None, help="Optional aggregate JSON output path.")
    args = parser.parse_args(argv)
    try:
        summary = summarize_reports(load_reports(args.path))
    except FeedbackDataError as exc:
        parser.error(str(exc))
    rendered = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"Aggregate summary saved to {output}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
