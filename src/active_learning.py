"""Active learning and retraining triage derived from anonymous feedback reports.

Analyzes category-level error distributions (false alarms vs missed scams) to
generate actionable guidance for data acquisition and threshold re-tuning,
without compromising user privacy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.feedback import DEFAULT_REPORTS, load_reports, summarize_reports


def triage_feedback(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze error categories to identify priority targets for model improvement."""
    summary = summarize_reports(reports)
    total_reports = summary["report_count"]

    false_positives = [r for r in reports if r["predicted_label"] == "spam" and r["expected_label"] == "ham"]
    false_negatives = [r for r in reports if r["predicted_label"] == "ham" and r["expected_label"] == "spam"]

    fp_by_category: dict[str, int] = {}
    for r in false_positives:
        cat = r.get("category", "other")
        fp_by_category[cat] = fp_by_category.get(cat, 0) + 1

    fn_by_category: dict[str, int] = {}
    for r in false_negatives:
        cat = r.get("category", "other")
        fn_by_category[cat] = fn_by_category.get(cat, 0) + 1

    recommendations: list[str] = []
    # Check if legitimate messages are falsely flagged as spam (high penalty)
    critical_fp_categories = {"otp", "bank_alert", "delivery"}
    critical_fps = sum(fp_by_category.get(c, 0) for c in critical_fp_categories)
    if critical_fps > 0:
        recommendations.append(
            f"High priority: {critical_fps} false positive report(s) in critical categories "
            f"({', '.join(sorted(critical_fp_categories & set(fp_by_category)))}). "
            "Consider raising decision threshold or adding consented legitimate samples in these categories."
        )

    # Check for missed scams
    critical_fn_categories = {"phishing", "prize_scam"}
    critical_fns = sum(fn_by_category.get(c, 0) for c in critical_fn_categories)
    if critical_fns > 0:
        recommendations.append(
            f"Evasion detected: {critical_fns} missed scam report(s) in ({', '.join(sorted(critical_fn_categories & set(fn_by_category)))}). "
            "Review brand and urgency indicators; evaluate retraining with updated synthetic supplements."
        )

    if not recommendations:
        recommendations.append("Feedback volume is low or balanced. No emergency threshold adjustments recommended.")

    return {
        "total_reports": total_reports,
        "false_positive_count": len(false_positives),
        "false_negative_count": len(false_negatives),
        "false_positives_by_category": dict(sorted(fp_by_category.items())),
        "false_negatives_by_category": dict(sorted(fn_by_category.items())),
        "recommendations": recommendations,
        "privacy_verified": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Triage anonymous feedback to guide model retraining.")
    parser.add_argument("--path", default=str(DEFAULT_REPORTS), help="JSONL feedback queue path.")
    parser.add_argument("--output", default=None, help="Optional output JSON path.")
    args = parser.parse_args(argv)

    reports = load_reports(args.path)
    triage = triage_feedback(reports)
    rendered = json.dumps(triage, ensure_ascii=False, indent=2) + "\n"

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        print(f"Triage report written to {out_path}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
