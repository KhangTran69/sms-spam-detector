import re
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

from src.data import DatasetError, group_leakage_report, load_holdout, load_training_dataset
from src.import_consented import import_consented, template_columns

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SUPPLEMENTS = sorted(RAW.glob("ph_supplement*.csv"))
HOLDOUT = RAW / "ph_holdout.csv"
sys.path.insert(0, str(ROOT / "scripts"))

import curate_supplements  # noqa: E402
import generate_synthetic_ph  # noqa: E402


def _shingles(text: str) -> set[str]:
    text = re.sub(r"\s+", " ", text.lower())
    return {text[i : i + 5] for i in range(len(text) - 4)}


def test_holdout_is_large_balanced_and_synthetic():
    frame = pd.read_csv(HOLDOUT, dtype=str, keep_default_na=False)
    assert len(frame) >= 200
    counts = frame["label"].value_counts()
    assert counts.min() >= 80
    assert set(frame["data_kind"]) == {"synthetic"}
    assert frame["group"].str.strip().ne("").all()


def test_holdout_is_group_and_text_separated_from_training():
    training = load_training_dataset(SUPPLEMENTS[0], SUPPLEMENTS[1:])
    holdout = load_holdout(HOLDOUT, strict=True)
    assert group_leakage_report(training, holdout)["template_family_overlap"] == 0
    train_shingles = [_shingles(message) for message in training.messages]
    worst = max(max(len(a & b) / len(a | b) for b in train_shingles) for a in (_shingles(m) for m in holdout.messages))
    assert worst < 0.6


def test_supplements_have_no_duplicates_or_heavy_templates():
    for path in SUPPLEMENTS:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        normalized = frame["message"].str.casefold().str.split().str.join(" ")
        assert not normalized.duplicated().any(), path.name
    curated = pd.read_csv(RAW / "ph_supplement_2.csv", dtype=str, keep_default_na=False)
    assert curated["message"].map(curate_supplements.family_key).value_counts().max() <= 2


def test_ph_training_classes_are_balanced():
    labels = pd.concat([pd.read_csv(path, dtype=str)["label"] for path in SUPPLEMENTS])
    counts = labels.value_counts()
    assert counts.min() / counts.max() >= 0.75


def test_generator_is_deterministic_and_idempotent(tmp_path):
    target = tmp_path / "s5.csv"
    shutil.copy(RAW / "ph_supplement_5.csv", target)
    generate_synthetic_ph.main(["--train-out", str(target)])
    assert target.read_text(encoding="utf-8") == (RAW / "ph_supplement_5.csv").read_text(encoding="utf-8")


def test_train_and_holdout_families_are_disjoint():
    train = {family for *_, family, _ in generate_synthetic_ph.TRAIN_FAMILIES}
    holdout = {family for *_, family, _ in generate_synthetic_ph.HOLDOUT_FAMILIES}
    assert not train & holdout


def _consented_row(**overrides):
    row = dict.fromkeys(template_columns(), "")
    row.update(
        label="spam",
        message="[BANK]: verify your account at [LINK] or call [PHONE]",
        data_kind="consented",
        source="batch_001",
        category="phishing",
        language="en",
        group="campaign_001",
        consent_record_id="consent_001",
        consent_verified="true",
        consent_active="true",
        consent_scope="training_and_evaluation",
        consent_version="v1",
        consent_date="2026-10-01",
        retention_until="2027-10-01",
        reviewer_a_id="reviewer_a",
        reviewer_a_label="spam",
        reviewer_b_id="reviewer_b",
        reviewer_b_label="spam",
        adjudicator_id="",
        adjudicated_label="spam",
    )
    row.update(overrides)
    return row


def test_consented_import_writes_consented_rows(tmp_path):
    source = tmp_path / "batch.csv"
    pd.DataFrame(
        [
            _consented_row(),
            _consented_row(
                label="ham",
                message="See you after class.",
                reviewer_a_label="ham",
                reviewer_b_label="ham",
                adjudicated_label="ham",
            ),
        ]
    ).to_csv(source, index=False)
    report = import_consented(source, output_dir=tmp_path / "out")
    assert report["rows_written"] == 2
    written = pd.read_csv(tmp_path / "out" / report["output"], dtype=str)
    assert set(written["data_kind"]) == {"consented"}


@pytest.mark.parametrize(
    ("message", "rule"),
    [
        ("Call me at 09171234567", "possible_phone_number"),
        ("email me juan@example.com", "possible_email_address"),
        ("Your OTP is 482913", "possible_live_code_or_numeric_identifier"),
    ],
)
def test_consented_import_rejects_unredacted(tmp_path, message, rule):
    source = tmp_path / "batch.csv"
    pd.DataFrame([_consented_row(message=message)]).to_csv(source, index=False)
    with pytest.raises(DatasetError, match=rule) as excinfo:
        import_consented(source, output_dir=tmp_path / "out")
    assert message not in str(excinfo.value)


def test_consented_import_requires_consent(tmp_path):
    source = tmp_path / "batch.csv"
    pd.DataFrame([_consented_row(consent_record_id="")]).to_csv(source, index=False)
    with pytest.raises(DatasetError, match="consent_record_id"):
        import_consented(source, output_dir=tmp_path / "out")
