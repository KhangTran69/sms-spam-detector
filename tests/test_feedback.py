"""Privacy checks for the anonymous correction queue and aggregate summary."""

from __future__ import annotations

import json

import pytest

from src.feedback import FeedbackDataError, load_reports, summarize_reports


def _report(**extra):
    return {
        "report_id": "receipt-id",
        "created_at": "2026-10-19T00:00:00+00:00",
        "model_version": "smsd-test",
        "server_model_version": "smsd-test",
        "predicted_label": "spam",
        "expected_label": "ham",
        "category": "otp",
        **extra,
    }


def test_missing_feedback_queue_is_an_empty_aggregate(tmp_path):
    assert summarize_reports(load_reports(tmp_path / "missing.jsonl"))["report_count"] == 0


def test_summary_contains_aggregate_counts_only(tmp_path):
    path = tmp_path / "reports.jsonl"
    path.write_text(
        "\n".join(json.dumps(report) for report in (_report(), _report(report_id="another"))) + "\n",
        encoding="utf-8",
    )
    reports = load_reports(path)
    summary = summarize_reports(reports)
    assert summary["report_count"] == 2
    assert summary["label_corrections"] == {"spam->ham": 2}
    assert summary["categories"] == {"otp": 2}
    assert summary["server_model_versions"] == {"smsd-test": 2}
    assert summary["message_text_included"] is False
    assert "report_id" not in json.dumps(summary)
    assert "created_at" not in json.dumps(summary)


def test_queue_rejects_any_sms_text_or_unknown_field(tmp_path):
    path = tmp_path / "unsafe.jsonl"
    path.write_text(json.dumps(_report(message="private SMS text")) + "\n", encoding="utf-8")
    with pytest.raises(FeedbackDataError, match="free-text") as error:
        load_reports(path)
    assert "private SMS text" not in str(error.value)


def test_cli_writes_an_aggregate_summary_without_identifiers(tmp_path, capsys):
    from src.feedback import _main

    path = tmp_path / "reports.jsonl"
    path.write_text(json.dumps(_report()) + "\n", encoding="utf-8")
    output = tmp_path / "summary.json"

    assert _main(["--path", str(path), "--output", str(output)]) == 0

    rendered = output.read_text(encoding="utf-8")
    payload = json.loads(rendered)
    assert payload["report_count"] == 1
    assert "receipt-id" not in rendered
    assert "Aggregate summary saved" in capsys.readouterr().out


def test_cli_rejects_an_unsafe_queue_without_echoing_text(tmp_path, capsys):
    from src.feedback import _main

    path = tmp_path / "unsafe.jsonl"
    path.write_text(json.dumps(_report(message="private SMS text")) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        _main(["--path", str(path)])

    assert error.value.code == 2
    assert "private SMS text" not in capsys.readouterr().err


def test_queue_rejects_matching_labels_and_invalid_categories(tmp_path):
    for payload in (
        _report(predicted_label="ham", expected_label="ham"),
        _report(category="raw_sms"),
    ):
        path = tmp_path / "invalid.jsonl"
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        with pytest.raises(FeedbackDataError):
            load_reports(path)
