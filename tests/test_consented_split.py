from __future__ import annotations

import json
import os
import stat
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.consented_split import split_consented_dataset
from src.dataset_splits import load_dataset


def write_consent_fixture(path: Path, row_count: int = 30) -> Path:
    today = datetime.now(UTC).date()
    rows = []
    for index in range(row_count):
        label = "ham" if index % 2 == 0 else "spam"
        scam = "not_suspected" if label == "ham" else "suspected"
        token = f"{string.ascii_lowercase[index // 26]}{string.ascii_lowercase[index % 26]}"
        rows.append(
            {
                "label": label,
                "scam_assessment": scam,
                "message": f"Synthetic {token} fixture message category {label}",
                "data_kind": "consented",
                "source": "consented_batch_01",
                "category": "otp_legit" if label == "ham" else "phishing",
                "language": "fil" if index % 3 == 0 else "en",
                "group": f"campaign_{index:04d}",
                "consent_record_id": f"consent_{index:04d}",
                "consent_verified": "true",
                "consent_active": "true",
                "review_consent": "true",
                "model_research_consent": "true",
                "authorized_to_share": "true",
                "consent_scope": "model_research",
                "consent_version": "test_v1",
                "consent_date": today.isoformat(),
                "retention_until": (today + timedelta(days=90)).isoformat(),
                "reviewer_a_id": "reviewer_a",
                "reviewer_a_label": label,
                "reviewer_a_scam_assessment": scam,
                "reviewer_a_label_confidence": "high",
                "reviewer_b_id": "reviewer_b",
                "reviewer_b_label": label,
                "reviewer_b_scam_assessment": scam,
                "reviewer_b_label_confidence": "high",
                "adjudicator_id": "",
                "adjudicated_label": label,
                "adjudicated_scam_assessment": scam,
                "adjudicated_label_confidence": "high",
                "review_status": "adjudicated",
                "received_at": f"{(today - timedelta(days=row_count - index)).isoformat()}T12:00:00Z",
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_splitter_writes_private_chronological_campaign_holdout_and_safe_manifest(tmp_path):
    source = write_consent_fixture(tmp_path / "synthetic-consented.csv")
    development_dir = tmp_path / "development-private"
    evaluation_dir = tmp_path / "sealed-private"

    result = split_consented_dataset(
        source,
        development_output_dir=development_dir,
        evaluation_output_dir=evaluation_dir,
    )

    development = development_dir / result["development"]["filename"]
    evaluation = evaluation_dir / result["sealed_evaluation"]["filename"]
    manifest_path = development_dir / result["manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    development_data = load_dataset(development, role="training", require_both_classes=True, min_class_count=0)
    evaluation_data = load_dataset(evaluation, role="holdout", require_both_classes=True, min_class_count=0)

    assert result["status"] == "split"
    assert result["split_method"] == "chronological_group_holdout"
    assert set(development_data.groups).isdisjoint(evaluation_data.groups)
    assert set(development_data.messages).isdisjoint(evaluation_data.messages)
    assert (
        pd.to_datetime(development_data.frame["received_at"]).max()
        < pd.to_datetime(evaluation_data.frame["received_at"]).min()
    )
    assert manifest["split"]["group_leakage"] == 0
    assert manifest["sealed_evaluation"]["sealed"] is True
    assert set(manifest["sealed_evaluation"]["coverage_counts"]) == {"language", "category"}
    assert (
        sum(manifest["sealed_evaluation"]["coverage_counts"]["language"].values())
        == result["sealed_evaluation"]["rows"]
    )
    assert manifest["message_text_included"] is False
    serialized = manifest_path.read_text(encoding="utf-8")
    assert "Synthetic" not in serialized
    assert "campaign_0000" not in serialized
    if os.name == "posix":
        assert stat.S_IMODE(development_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(evaluation_dir.stat().st_mode) == 0o700
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in (development, evaluation, manifest_path))


def test_splitter_rejects_duplicate_and_unseparated_input_before_writing(tmp_path):
    source = write_consent_fixture(tmp_path / "duplicate.csv")
    frame = pd.read_csv(source)
    frame.loc[1, "message"] = frame.loc[0, "message"]
    frame.to_csv(source, index=False)
    development_dir = tmp_path / "development-private"
    evaluation_dir = tmp_path / "sealed-private"

    with pytest.raises(ValueError, match="duplicate_message_before_split"):
        split_consented_dataset(
            source,
            development_output_dir=development_dir,
            evaluation_output_dir=evaluation_dir,
        )

    assert not development_dir.exists()
    assert not evaluation_dir.exists()


def test_splitter_rejects_near_duplicate_templates_across_campaign_groups(tmp_path):
    source = write_consent_fixture(tmp_path / "near-duplicate.csv")
    frame = pd.read_csv(source)
    frame.loc[0, "message"] = "Your account service notification is ready for review today."
    frame.loc[1, "message"] = "Your account service notification is ready for review now!"
    frame.loc[[0, 1], "category"] = "bank_alert"
    frame.to_csv(source, index=False)
    development_dir = tmp_path / "development-private"
    evaluation_dir = tmp_path / "sealed-private"

    with pytest.raises(ValueError, match="near_duplicate_template_spans_campaign_groups"):
        split_consented_dataset(
            source,
            development_output_dir=development_dir,
            evaluation_output_dir=evaluation_dir,
        )

    assert not development_dir.exists()
    assert not evaluation_dir.exists()


def test_splitter_rejects_source_changed_after_consent_preflight(tmp_path, monkeypatch):
    import src.consented_split as consented_split

    source = write_consent_fixture(tmp_path / "changing.csv")
    original_load_dataset = consented_split.load_dataset

    def change_source_before_load(path, **kwargs):
        frame = pd.read_csv(path)
        frame.loc[0, "language"] = "tl"
        frame.to_csv(path, index=False)
        return original_load_dataset(path, **kwargs)

    monkeypatch.setattr(consented_split, "load_dataset", change_source_before_load)
    development_dir = tmp_path / "development-private"
    evaluation_dir = tmp_path / "sealed-private"

    with pytest.raises(ValueError, match="changed after preflight"):
        split_consented_dataset(
            source,
            development_output_dir=development_dir,
            evaluation_output_dir=evaluation_dir,
        )

    assert not development_dir.exists()
    assert not evaluation_dir.exists()


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("consent_active", "false"),
        ("retention_until", "2000-01-01"),
        ("consent_scope", "training"),
        ("consent_record_id", None),
    ],
)
def test_splitter_fails_closed_for_missing_withdrawn_expired_or_insufficient_consent(
    tmp_path, changed_field, changed_value
):
    source = write_consent_fixture(tmp_path / "invalid-consent.csv")
    frame = pd.read_csv(source, dtype=str, keep_default_na=False)
    if changed_value is None:
        frame = frame.drop(columns=[changed_field])
    else:
        frame[changed_field] = changed_value
    frame.to_csv(source, index=False)
    development_dir = tmp_path / "development-private"
    evaluation_dir = tmp_path / "sealed-private"

    with pytest.raises(ValueError):
        split_consented_dataset(
            source,
            development_output_dir=development_dir,
            evaluation_output_dir=evaluation_dir,
        )

    assert not development_dir.exists()
    assert not evaluation_dir.exists()
