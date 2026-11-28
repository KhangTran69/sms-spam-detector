"""Pilot coverage status tests with synthetic fixtures only.

scripts/pilot_status.py must report, message-free, how far pooled intake CSVs
are from the ratified consented-evaluation-plan minimums: exit 1 with the gap
list while any minimum is unmet, exit 0 once every minimum is met, count
campaign groups and donors correctly, compute spam_top3 from the data, pool
multiple files, tolerate the optional intake columns' absence, fail cleanly on
unreadable input, and read the minimums from the plan JSON at runtime. Most of
all, message text and consent/group id values must never appear in stdout, the
JSON report, or errors.

Every message below is a tracked synthetic fixture (nothing real), and every
consent_record_id and group value is pseudonymous; those exact values are the
forbidden strings in the message-free assertions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from scripts.pilot_status import _validate_output_path, main

ROOT = Path(__file__).resolve().parents[1]

# Synthetic fixtures only: no digits, no domains, no senders, nothing real.
MSG_A = "Synthetic pilot fixture alpha: routine balance notice template for coverage counting only."
MSG_B = "Synthetic pilot fixture bravo: unsolicited prize claim template for coverage counting only."
MSG_C = "Synthetic pilot fixture charlie: delivery update template for coverage counting only."
MSG_D = "Synthetic pilot fixture delta: routine utility notice template for coverage counting only."
MSG_E = "Synthetic pilot fixture echo: unsolicited promotion template for coverage counting only."
CONSENT_A = "consent_a1b2c3d4e5f6"
CONSENT_B = "consent_b2c3d4e5f6a7"
GROUP_ONE = "grp_campaign_one"
GROUP_TWO = "grp_campaign_two"

FORBIDDEN_VALUES = (MSG_A, MSG_B, MSG_C, MSG_D, MSG_E, CONSENT_A, CONSENT_B, GROUP_ONE, GROUP_TWO)


def _row(
    *,
    label: str,
    message: str,
    language: str,
    category: str,
    group: str,
    consent: str,
    **extra: str,
) -> dict[str, str]:
    row = {
        "label": label,
        "message": message,
        "language": language,
        "category": category,
        "group": group,
        "consent_record_id": consent,
    }
    row.update(extra)
    return row


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, lineterminator="\n")
    return path


def _run_with_output(tmp_path: Path, argv: list[str]) -> tuple[int, dict[str, object], str, Path]:
    output = tmp_path / "pilot-status.json"
    exit_code = main([*argv, "--output", str(output)])
    file_text = output.read_text(encoding="utf-8") if output.exists() else ""
    report = json.loads(file_text) if file_text else {}
    return exit_code, report, file_text, output


def _gap_triples(report: dict[str, object]) -> set[tuple[str, str, int]]:
    return {(gap["dimension"], gap["code"], gap["needed"]) for gap in report["gaps"]}  # type: ignore[union-attr]


def _assert_message_free(*texts: str) -> None:
    for text in texts:
        for forbidden in FORBIDDEN_VALUES:
            assert forbidden not in text


BELOW_ROWS = [
    _row(label="spam", message=MSG_A, language="en", category="otp", group=GROUP_ONE, consent=CONSENT_A),
    _row(label="ham", message=MSG_B, language="en", category="otp", group=GROUP_ONE, consent=CONSENT_A),
    _row(label="spam", message=MSG_C, language="tl", category="prize", group=GROUP_TWO, consent=CONSENT_B),
]

EXPECTED_BELOW_GAPS = {
    ("language", "en", 98),
    ("language", "tl", 99),
    ("language", "tl-en", 100),
    ("category", "otp", 148),
    ("category", "bank_alert", 150),
    ("category", "delivery", 150),
    ("category", "spam_top3", 298),
    ("campaign_groups", "campaign_groups", 10),
}


def test_below_minimum_exits_1_and_lists_gaps_with_needed_counts(tmp_path):
    csv_path = _write_csv(tmp_path / "below" / "intake.csv", BELOW_ROWS)

    exit_code, report, file_text, output = _run_with_output(tmp_path, [str(csv_path)])

    assert exit_code == 1
    assert report["status"] == "below_minimum"
    assert report["totals"] == {"messages": 3, "donors": 2, "campaign_groups": 2}
    assert report["labels"] == {"ham": 1, "spam": 2, "unrecognized": 0}
    assert _gap_triples(report) == EXPECTED_BELOW_GAPS
    assert report["coverage"]["spam_top3"]["categories"] == [  # type: ignore[index]
        {"category": "otp", "count": 1},
        {"category": "prize", "count": 1},
    ]
    assert (output.stat().st_mode & 0o777) == 0o600, "the private report must be owner-readable only"
    _assert_message_free(file_text)


def test_below_minimum_stdout_is_a_human_readable_gap_summary(tmp_path, capsys):
    csv_path = _write_csv(tmp_path / "below" / "intake.csv", BELOW_ROWS)

    exit_code = main([str(csv_path)])

    assert exit_code == 1
    stdout = capsys.readouterr().out
    assert "below_minimum" in stdout
    assert "Messages: 3 | Donors: 2 | Campaign groups: 2 (minimum 12)" in stdout
    assert "Language coverage: en 2/100 needed 98 | tl 1/100 needed 99 | tl-en 0/100 needed 100" in stdout
    assert "Category coverage: otp 2/150 needed 148 | bank_alert 0/150 needed 150 | delivery 0/150 needed 150" in stdout
    assert "spam_top3: 2/300 needed 298 (otp 1, prize 1)" in stdout
    assert "Gaps: 8" in stdout
    assert "language tl-en: have 0, minimum 100, still needed 100" in stdout
    assert "category spam_top3: have 2, minimum 300, still needed 298" in stdout
    assert "campaign_groups campaign_groups: have 2, minimum 12, still needed 10" in stdout
    _assert_message_free(stdout)


def test_at_minimum_exits_0_with_all_minimums_met(tmp_path):
    rows = []
    languages = ("en", "tl", "tl-en")
    index = 0
    for category in ("otp", "bank_alert", "delivery"):
        for slot in range(150):
            rows.append(
                _row(
                    label="ham",
                    message=f"Synthetic fixture ham {category} slot {slot}",
                    language=languages[slot % 3],
                    category=category,
                    group=f"grp_campaign{index % 12:02d}",
                    consent=f"consent_donor{index % 12:02d}",
                )
            )
            index += 1
    for category in ("prize", "promo", "investment"):
        for slot in range(100):
            rows.append(
                _row(
                    label="spam",
                    message=f"Synthetic fixture spam {category} slot {slot}",
                    language=languages[slot % 3],
                    category=category,
                    group=f"grp_campaign{index % 12:02d}",
                    consent=f"consent_donor{index % 12:02d}",
                )
            )
            index += 1
    csv_path = _write_csv(tmp_path / "at-minimum" / "intake.csv", rows)

    exit_code, report, file_text, _output = _run_with_output(tmp_path, [str(csv_path)])

    assert exit_code == 0
    assert report["status"] == "minimums_met"
    assert report["gaps"] == []
    assert report["totals"] == {"messages": 750, "donors": 12, "campaign_groups": 12}
    for entry in report["coverage"]["language"].values():  # type: ignore[union-attr]
        assert entry["met"] is True
    for entry in report["coverage"]["category"].values():  # type: ignore[union-attr]
        assert entry["met"] is True
    spam_entry = report["coverage"]["spam_top3"]  # type: ignore[index]
    assert spam_entry["met"] is True
    assert spam_entry["count"] == 300
    assert {item["category"] for item in spam_entry["categories"]} == {"prize", "promo", "investment"}
    assert report["coverage"]["campaign_groups"]["met"] is True  # type: ignore[index]
    _assert_message_free(file_text)
    for sample in (rows[0], rows[450], rows[-1]):
        assert sample["message"] not in file_text
        assert sample["consent_record_id"] not in file_text
        assert sample["group"] not in file_text


def test_outputs_never_carry_message_text_or_consent_or_group_ids(tmp_path, capsys):
    csv_path = _write_csv(tmp_path / "private" / "intake.csv", BELOW_ROWS)

    exit_code, _report, file_text, _output = _run_with_output(tmp_path, [str(csv_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    _assert_message_free(captured.out, captured.err, file_text)


def test_campaign_group_and_donor_counting_excludes_blanks_and_folds_case(tmp_path):
    rows = [
        _row(label="ham", message=MSG_A, language="en", category="otp", group=GROUP_ONE, consent=CONSENT_A),
        _row(label="ham", message=MSG_B, language="en", category="otp", group=GROUP_ONE, consent=CONSENT_A),
        _row(
            label="ham", message=MSG_C, language="tl", category="delivery", group="GRP_CAMPAIGN_ONE", consent=CONSENT_A
        ),
        _row(label="ham", message=MSG_D, language="tl-en", category="bank_alert", group=GROUP_TWO, consent=CONSENT_A),
        _row(label="spam", message=MSG_E, language="en", category="prize", group="", consent=""),
    ]
    csv_path = _write_csv(tmp_path / "groups" / "intake.csv", rows)

    _exit_code, report, _file_text, _output = _run_with_output(tmp_path, [str(csv_path)])

    assert report["totals"]["campaign_groups"] == 2, "case-variant ids are one campaign; blanks are not a campaign"
    assert report["totals"]["donors"] == 1
    assert report["totals"]["messages"] == 5


def test_missing_file_is_a_clean_error(tmp_path, capsys):
    missing = tmp_path / "nowhere" / "intake.csv"

    exit_code = main([str(missing)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert '"status": "error"' in captured.err
    assert "Could not read intake CSV" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    _assert_message_free(captured.err)


def test_missing_plan_is_a_clean_error(tmp_path, capsys):
    csv_path = _write_csv(tmp_path / "below" / "intake.csv", BELOW_ROWS)

    exit_code = main([str(csv_path), "--plan", str(tmp_path / "nope.json")])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert '"status": "error"' in captured.err
    assert "coverage minimums plan" in captured.err
    assert captured.out == ""


def test_plan_missing_minimum_coverage_is_a_clean_error(tmp_path, capsys):
    csv_path = _write_csv(tmp_path / "below" / "intake.csv", BELOW_ROWS)
    incomplete = tmp_path / "incomplete-plan.json"
    incomplete.write_text(json.dumps({"schema_version": 2, "minimum_campaign_groups": 2}), encoding="utf-8")

    exit_code = main([str(csv_path), "--plan", str(incomplete)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert '"status": "error"' in captured.err
    assert "missing the minimum_coverage object" in captured.err
    assert captured.out == ""
    _assert_message_free(captured.err)


def test_missing_message_column_skips_duplicate_detection(tmp_path):
    rows = [{key: value for key, value in row.items() if key != "message"} for row in BELOW_ROWS]
    csv_path = _write_csv(tmp_path / "no-message" / "intake.csv", rows)

    _exit_code, report, _file_text, _output = _run_with_output(tmp_path, [str(csv_path)])

    assert report["inputs"] == {"file_count": 1, "duplicate_detection_applied": False}
    assert report["warnings"] == {"duplicate_messages": 0, "unrecognized_label_rows": 0}
    assert report["totals"] == {"messages": 3, "donors": 2, "campaign_groups": 2}


def test_multiple_csvs_are_pooled_with_optional_columns_tolerated(tmp_path):
    first = _write_csv(tmp_path / "batch-one" / "intake.csv", BELOW_ROWS)
    second_rows = [
        _row(
            label="ham",
            message=MSG_D,
            language="tl-en",
            category="delivery",
            group=GROUP_TWO,
            consent=CONSENT_A,
            received_at="2026-11-20",
            labeling_confidence="0.9",
        ),
        _row(label="spam", message=MSG_E, language="en", category="promo", group=GROUP_TWO, consent=CONSENT_B),
    ]
    second = _write_csv(tmp_path / "batch-two" / "intake.csv", second_rows)

    _exit_code, report, _file_text, _output = _run_with_output(tmp_path, [str(first), str(second)])

    assert report["inputs"] == {"file_count": 2, "duplicate_detection_applied": True}
    assert report["totals"]["messages"] == 5
    assert report["totals"]["donors"] == 2
    assert report["counts"]["languages"] == {"en": 3, "tl": 1, "tl-en": 1}
    assert report["counts"]["categories"] == {"delivery": 1, "otp": 2, "prize": 1, "promo": 1}


def test_spam_top3_is_computed_from_the_data(tmp_path):
    rows = []
    for category, count in (("prize", 5), ("promo", 4), ("investment", 3), ("other_spam", 2)):
        rows.extend(
            _row(
                label="spam",
                message=f"Synthetic fixture spam {category} item {item}",
                language="en",
                category=category,
                group=GROUP_ONE,
                consent=CONSENT_A,
            )
            for item in range(count)
        )
    csv_path = _write_csv(tmp_path / "top3" / "intake.csv", rows)

    _exit_code, report, _file_text, _output = _run_with_output(tmp_path, [str(csv_path)])

    spam_entry = report["coverage"]["spam_top3"]  # type: ignore[index]
    assert spam_entry["categories"] == [
        {"category": "prize", "count": 5},
        {"category": "promo", "count": 4},
        {"category": "investment", "count": 3},
    ]
    assert "other_spam" not in [item["category"] for item in spam_entry["categories"]]
    assert spam_entry["count"] == 12
    assert spam_entry["minimum"] == 300
    assert spam_entry["needed"] == 288
    assert report["counts"]["categories"]["other_spam"] == 2  # type: ignore[index]


def test_duplicate_messages_counted_as_is_and_reported_as_warning(tmp_path):
    variant = "synthetic PILOT fixture alpha:   routine balance notice TEMPLATE for coverage counting only."
    first = _write_csv(tmp_path / "dup-a" / "intake.csv", [BELOW_ROWS[0]])
    second = _write_csv(
        tmp_path / "dup-b" / "intake.csv",
        [BELOW_ROWS[0], BELOW_ROWS[0] | {"message": variant}],
    )

    _exit_code, report, _file_text, _output = _run_with_output(tmp_path, [str(first), str(second)])

    assert report["totals"]["messages"] == 3, "duplicate rows are counted as-is"
    assert report["warnings"]["duplicate_messages"] == 2
    assert report["coverage"]["language"]["en"]["count"] == 3  # type: ignore[index]
    assert report["coverage"]["category"]["otp"]["count"] == 3  # type: ignore[index]


def test_plan_minimums_are_read_at_runtime(tmp_path):
    csv_path = _write_csv(tmp_path / "below" / "intake.csv", BELOW_ROWS)
    re_ratified = tmp_path / "re-ratified.json"
    re_ratified.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "minimum_campaign_groups": 2,
                "minimum_coverage": {
                    "language": {"en": 2, "tl": 1, "tl-en": 0},
                    "category": {"otp": 2, "bank_alert": 0, "delivery": 0, "spam_top3": 2},
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, report, _file_text, _output = _run_with_output(tmp_path, [str(csv_path), "--plan", str(re_ratified)])

    assert exit_code == 0
    assert report["status"] == "minimums_met"
    assert report["gaps"] == []
    assert report["coverage"]["campaign_groups"]["minimum"] == 2  # type: ignore[index]


def test_default_plan_is_the_ratified_template():
    plan = json.loads((ROOT / "docs" / "templates" / "consented-evaluation-plan.json").read_text(encoding="utf-8"))
    assert plan["minimum_coverage"]["language"] == {"en": 100, "tl": 100, "tl-en": 100}
    assert plan["minimum_coverage"]["category"] == {
        "otp": 150,
        "bank_alert": 150,
        "delivery": 150,
        "spam_top3": 300,
    }
    assert plan["minimum_campaign_groups"] == 12


def test_report_output_path_protection(tmp_path):
    with pytest.raises(ValueError, match="outside the repository"):
        _validate_output_path(ROOT / "docs" / "pilot-status.json")
    assert (
        _validate_output_path(ROOT / "data" / "donations" / "pilot-status.json")
        == (ROOT / "data" / "donations" / "pilot-status.json").resolve()
    )
    assert (
        _validate_output_path(tmp_path / "private" / "pilot-status.json")
        == (tmp_path / "private" / "pilot-status.json").resolve()
    )


def test_repository_tree_output_is_a_clean_error(tmp_path, capsys):
    csv_path = _write_csv(tmp_path / "below" / "intake.csv", BELOW_ROWS)

    exit_code = main([str(csv_path), "--output", str(ROOT / "pilot-status-report.json")])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert '"status": "error"' in captured.err
    assert "outside the repository" in captured.err
    assert not (ROOT / "pilot-status-report.json").exists()
