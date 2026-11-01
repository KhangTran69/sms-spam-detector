from __future__ import annotations

import json
import os

import pandas as pd

from src.dataset_loading import load_dataset
from src.import_public_dataset import import_kaggle_ph_dataset
from src.import_public_dataset import main as import_public_main
from src.public_datasets import (
    MessageRecord,
    import_kaggle_tagalog_dataset,
    normalize_kaggle_ph_csv,
    normalize_kaggle_tagalog_csv,
)


def write_kaggle_export(path):
    pd.DataFrame(
        [
            ("2026-01-01T12:00:00+08:00", "spam", "Prize alert: claim now"),
            ("2026-01-02T12:00:00+08:00", "ads", "Promo from a known business"),
            ("2026-01-03T12:00:00+08:00", "gov", "Weather advisory"),
            ("2026-01-04T12:00:00+08:00", "notifs", "Delivery update"),
            ("2026-01-05T12:00:00+08:00", "OTP", "<REDACTED>"),
            ("2026-01-06T12:00:00+08:00", "spam", "  "),
            ("2026-01-07T12:00:00+08:00", "spam", " prize ALERT: claim now "),
            ("2026-01-08T12:00:00+08:00", "mystery", "Unmapped category sample"),
        ],
        columns=("date-received", "category", "text"),
    ).to_csv(path, index=False)
    return path


def test_normalize_maps_categories_and_reports_exclusions_and_duplicates(tmp_path):
    source = write_kaggle_export(tmp_path / "kaggle.csv")

    records, report = normalize_kaggle_ph_csv(source)

    assert all(isinstance(record, MessageRecord) for record in records)
    assert [(record.category, record.label) for record in records] == [
        ("spam", "spam"),
        ("ads", "spam"),
        ("gov", "ham"),
        ("notifs", "ham"),
    ]
    assert records[0].received_at == "2026-01-01T12:00:00+08:00"
    assert records[0].source == "ph_spam_marketing_sms_timestamps"
    assert report == {
        "rows_seen": 8,
        "rows_loaded": 4,
        "blank_or_redacted_excluded": 2,
        "unknown_category_rows": 1,
        "duplicates_removed": 1,
        "distinct_unknown_category_count": 1,
    }


def test_record_ids_are_stable_and_do_not_include_message_text(tmp_path):
    source = write_kaggle_export(tmp_path / "kaggle.csv")

    first, _ = normalize_kaggle_ph_csv(source)
    second, _ = normalize_kaggle_ph_csv(source)

    assert [item.record_id for item in first] == [item.record_id for item in second]
    assert "Prize alert" not in first[0].record_id
    assert len(first[0].record_id) == 64


def test_import_writes_canonical_csv_accepted_by_existing_loader(tmp_path, monkeypatch):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    external = tmp_path / "data" / "external"
    external.mkdir(parents=True)
    source = write_kaggle_export(tmp_path / "kaggle.csv")
    monkeypatch.setattr("src.import_public_dataset.ROOT", tmp_path)

    output, report = import_kaggle_ph_dataset(source, external / "normalized.csv")
    dataset = load_dataset(output, require_both_classes=True, min_class_count=0)

    assert len(dataset) == 4
    assert dataset.class_counts == {"ham": 2, "spam": 2}
    assert pd.read_csv(output)["record_id"].str.fullmatch(r"[a-f0-9]{64}").all()
    assert "record_id" not in dataset.frame.columns
    assert report["unknown_category_rows"] == 1
    assert dataset.records[0].provenance["license"] == "CC BY 4.0"
    assert dataset.records[0].provenance["dataset_id"] == "ph-spam-marketing-sms-w-timestamps"
    manifest = json.dumps(dataset.summary())
    assert "Prize alert" not in manifest


def test_import_refuses_output_outside_external_data(tmp_path, monkeypatch):
    (tmp_path / "data" / "external").mkdir(parents=True)
    source = write_kaggle_export(tmp_path / "kaggle.csv")
    monkeypatch.setattr("src.import_public_dataset.ROOT", tmp_path)

    try:
        import_kaggle_ph_dataset(source, tmp_path / "outside.csv")
    except ValueError as error:
        assert "data/external" in str(error)
    else:
        raise AssertionError("expected a path safety error")


def test_tagalog_dataset_maps_labels_and_drops_sender_metadata(tmp_path):
    source = tmp_path / "tagalog-sms.csv"
    pd.DataFrame(
        [
            ("2026-01-01T12:00:00+08:00", "Example sender", "Synthetic prize message", "spam"),
            ("2026-01-02T12:00:00+08:00", "Example sender", "Synthetic shop promotion", "ads"),
            ("2026-01-03T12:00:00+08:00", "Example sender", "Synthetic government alert", "gov"),
            ("2026-01-04T12:00:00+08:00", "Example sender", "Synthetic service notice", "notifs"),
            ("2026-01-05T12:00:00+08:00", "Example sender", "Synthetic expired one-time code", "otp"),
            ("2026-01-06T12:00:00+08:00", "Example sender", "Synthetic unknown label", "other"),
        ],
        columns=("Date", "Sender", "Text", "Category"),
    ).to_csv(source, index=False)

    records, report = normalize_kaggle_tagalog_csv(source)

    assert [(record.category, record.label) for record in records] == [
        ("spam", "spam"),
        ("ads", "spam"),
        ("gov", "ham"),
        ("notifs", "ham"),
        ("otp", "ham"),
    ]
    assert records[0].source == "tagalog_sms"
    assert records[0].received_at == "2026-01-01T12:00:00+08:00"
    assert report["distinct_unknown_category_count"] == 1
    assert all("sender" not in record.__dict__ for record in records)


def test_unknown_category_report_never_echoes_untrusted_values(tmp_path):
    source = tmp_path / "sensitive-category.csv"
    pd.DataFrame(
        [("2026-01-01", "analyst@example.invalid", "Synthetic fixture")],
        columns=("date-received", "category", "text"),
    ).to_csv(source, index=False)

    _records, report = normalize_kaggle_ph_csv(source)

    assert report["unknown_category_rows"] == 1
    assert report["distinct_unknown_category_count"] == 1
    assert "analyst@example.invalid" not in json.dumps(report)


def test_tagalog_import_outputs_only_normalized_fields(tmp_path, monkeypatch):
    (tmp_path / "data" / "external").mkdir(parents=True)
    source = tmp_path / "tagalog-sms.csv"
    pd.DataFrame(
        [
            ("2026-01-01", "Example sender", "Synthetic prize message", "spam"),
            ("2026-01-02", "Example sender", "Synthetic bill reminder", "notifs"),
        ],
        columns=("Date", "Sender", "Text", "Category"),
    ).to_csv(source, index=False)
    monkeypatch.setattr("src.import_public_dataset.ROOT", tmp_path)

    output, report = import_kaggle_tagalog_dataset(source, tmp_path / "data" / "external" / "tagalog.csv")

    normalized = pd.read_csv(output)
    assert "sender" not in {column.lower() for column in normalized.columns}
    assert normalized["data_kind"].tolist() == ["public", "public"]
    assert normalized["dataset_id"].tolist() == ["tagalog-sms"] * 2
    assert normalized["license"].tolist() == ["CC0: Public Domain"] * 2
    assert report["rows_loaded"] == 2
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o600
        assert output.parent.stat().st_mode & 0o777 == 0o700


def test_import_cli_defaults_kaggle_output_to_external_storage(tmp_path, monkeypatch, capsys):
    source = write_kaggle_export(tmp_path / "kaggle.csv")
    monkeypatch.setattr("src.import_public_dataset.ROOT", tmp_path)

    result = import_public_main(["--source", "kaggle-ph", "--input", str(source)])

    assert result == 0
    assert (tmp_path / "data" / "external" / "ph-spam-marketing-sms.csv").is_file()
    assert "unknown category: 1" in capsys.readouterr().out
