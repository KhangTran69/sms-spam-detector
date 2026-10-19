"""Dataset loading, validation, multi-supplement merging, and leakage tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.data import (
    DEFAULT_DATA,
    DEFAULT_SUPPLEMENTS,
    DatasetError,
    group_leakage_report,
    grouped_splits,
    load_dataset,
    load_holdout,
    load_training_dataset,
    make_group_key,
    resolve_supplement_paths,
    split_dataset,
)
from src.train import load_dataset as legacy_load_dataset
from src.train import load_training_data as legacy_load_training_data

ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENT = ROOT / "data" / "raw" / "ph_supplement.csv"
SUPPLEMENT_2 = ROOT / "data" / "raw" / "ph_supplement_2.csv"
SUPPLEMENT_3 = ROOT / "data" / "raw" / "ph_supplement_3.csv"
HOLDOUT = ROOT / "data" / "raw" / "ph_holdout.csv"

BRIEF_EXAMPLES = (
    "Nag-claim ka ng ₱500,000 sa GMA Kapuso Foundation. Call now 09123456789",
    "BDO: Your account is locked. Verify here: http://bit.ly/fakebdo",
    "Congrats! You won ₱1M from PCSO. Text your name and address to 0922xxxxxxx",
)


def write_csv(path: Path, rows, columns=("label", "message")) -> Path:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
    return path


def tiny_training_csv(path: Path) -> Path:
    rows = [
        ("ham", "Salamat sa tulong mo kahapon"),
        ("ham", "See you at the meeting tomorrow"),
        ("ham", "Ok lang ako, salamat po"),
        ("spam", "Congratulations! You won a free prize. Claim now!"),
        ("spam", "Free cash prize waiting, text WIN to 09171234567"),
        ("spam", "You are a winner! Claim your prize agad"),
    ]
    return write_csv(path, rows)


# ----------------------------- schema / label validation -----------------------------


def test_missing_file_has_actionable_error(tmp_path):
    with pytest.raises(DatasetError, match="not found"):
        load_dataset(tmp_path / "missing.csv")


def test_empty_file_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DatasetError, match="empty"):
        load_dataset(path)


def test_header_only_file_rejected(tmp_path):
    path = tmp_path / "header.csv"
    path.write_text("label,message\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="no data rows"):
        load_dataset(path)


def test_unrecognized_schema_rejected(tmp_path):
    path = write_csv(tmp_path / "bad.csv", [("x", "y")], columns=("foo", "bar"))
    with pytest.raises(DatasetError, match="message/label columns"):
        load_dataset(path)


def test_unknown_label_rejected(tmp_path):
    path = write_csv(tmp_path / "labels.csv", [("ham", "a"), ("maybe", "b")])
    with pytest.raises(DatasetError, match="unrecognized labels"):
        load_dataset(path)


def test_blank_message_strict_and_lenient(tmp_path):
    path = write_csv(tmp_path / "blank.csv", [("ham", "hello"), ("spam", "   ")])
    with pytest.raises(DatasetError, match="blank message"):
        load_dataset(path)
    # Class checks are irrelevant here; tiny fixture opts out of them.
    dataset = load_dataset(path, strict=False, require_both_classes=False, min_class_count=0)
    assert len(dataset) == 1


def test_conflicting_duplicate_labels_rejected(tmp_path):
    path = write_csv(
        tmp_path / "conflict.csv",
        [("ham", "same text"), ("spam", "same text"), ("ham", "other"), ("spam", "another")],
    )
    with pytest.raises(DatasetError, match="conflicting labels"):
        load_dataset(path)


def test_exact_duplicates_are_removed_before_split(tmp_path):
    path = write_csv(
        tmp_path / "dupes.csv",
        [("ham", "same text"), ("ham", "same text"), ("spam", "spam text"), ("ham", "other ham")],
    )
    dataset = load_dataset(path, min_class_count=0)
    assert len(dataset) == 3
    assert any("duplicate" in warning for warning in dataset.warnings)
    assert dataset.records[0].duplicates_removed == 1


def test_missing_class_rejected(tmp_path):
    path = write_csv(tmp_path / "only_ham.csv", [("ham", "one"), ("ham", "two")])
    with pytest.raises(DatasetError, match="both ham and spam"):
        load_dataset(path)
    dataset = load_dataset(path, require_both_classes=False)
    assert dataset.class_counts == {"ham": 2, "spam": 0}


def test_single_example_class_rejected_for_splitting(tmp_path):
    path = write_csv(tmp_path / "tinyclass.csv", [("ham", "one"), ("ham", "two"), ("spam", "three")])
    with pytest.raises(DatasetError, match="at least 2"):
        load_dataset(path)


def test_kaggle_v1_v2_layout_and_label_aliases(tmp_path):
    path = write_csv(
        tmp_path / "kaggle.csv",
        [("ham", "hello there"), ("spam", "win money"), ("legitimate", "ok po"), ("scam", "claim prize")],
        columns=("v1", "v2"),
    )
    dataset = load_dataset(path)
    assert set(dataset.labels) == {"ham", "spam"}
    assert len(dataset) == 4


def test_metadata_columns_are_preserved(tmp_path):
    path = write_csv(
        tmp_path / "meta.csv",
        [
            ("ham", "Your OTP is 123456", "otp", "en", "consented_q1", "high", "otp-family"),
            ("spam", "You won a prize", "prize_scam", "taglish", "consented_q1", "medium", "prize-family"),
        ],
        columns=("label", "message", "category", "language", "source", "labeling_confidence", "group"),
    )
    dataset = load_dataset(path, min_class_count=0)
    frame = dataset.frame
    assert list(frame.columns) == [
        "message",
        "label",
        "source",
        "category",
        "language",
        "labeling_confidence",
        "group",
        "received_at",
        "data_kind",
        "source_file",
    ]
    assert frame.loc[0, "category"] == "otp"
    assert frame.loc[0, "language"] == "en"
    assert frame.loc[0, "source"] == "consented_q1"
    assert frame.loc[0, "group"] == "otp-family"
    assert frame.loc[0, "labeling_confidence"] == "high"


def test_time_split_keeps_campaigns_disjoint_and_respects_date_order(tmp_path):
    rows = []
    for period in range(6):
        stamp = f"2026-01-{period + 1:02d}T12:00:00Z"
        rows.extend(
            [
                ("ham", f"ordinary message {period}", f"ham-campaign-{period}", stamp),
                ("spam", f"scam message {period}", f"spam-campaign-{period}", stamp),
            ]
        )
    path = write_csv(
        tmp_path / "dated.csv",
        rows,
        columns=("label", "message", "group", "received_at"),
    )
    dataset = load_dataset(path)
    split = grouped_splits(dataset, val_size=0.25, test_size=0.25, split_by="time")
    train_set, val_set, test_set = split_dataset(dataset, split)
    assert split.method == "chronological_group_holdout"
    assert set(train_set.labels) == set(val_set.labels) == set(test_set.labels) == {"ham", "spam"}
    assert set(train_set.groups).isdisjoint(val_set.groups)
    assert set(train_set.groups).isdisjoint(test_set.groups)
    assert set(val_set.groups).isdisjoint(test_set.groups)
    train_max = pd.to_datetime(train_set.frame["received_at"]).max()
    val_max = pd.to_datetime(val_set.frame["received_at"]).max()
    test_max = pd.to_datetime(test_set.frame["received_at"]).max()
    assert train_max < val_max < test_max


def test_time_split_requires_dates(tmp_path):
    dataset = load_dataset(tiny_training_csv(tmp_path / "undated.csv"))
    with pytest.raises(DatasetError, match="valid received_at"):
        grouped_splits(dataset, split_by="time")


def test_imbalance_warning(tmp_path):
    rows = [("ham", f"ordinary message number {index}") for index in range(50)]
    rows += [("spam", f"prize message {index}") for index in range(2)]
    dataset = load_dataset(write_csv(tmp_path / "imbalance.csv", rows))
    assert any("imbalanced" in warning for warning in dataset.warnings)


# ----------------------------- supplements -----------------------------


def test_supplement_resolution_none_and_explicit_missing(tmp_path):
    assert resolve_supplement_paths(None, strict=True)[0] == []
    assert resolve_supplement_paths("none", strict=True)[0] == []
    assert resolve_supplement_paths("NONE", strict=True)[0] == []
    with pytest.raises(DatasetError, match="not found"):
        resolve_supplement_paths(tmp_path / "missing.csv", strict=True)
    paths, warnings = resolve_supplement_paths([tmp_path / "missing.csv"], strict=False)
    assert paths == [] and warnings


def test_supplement_none_cannot_be_mixed_with_paths(tmp_path):
    with pytest.raises(DatasetError, match="cannot be combined"):
        resolve_supplement_paths(["none", str(SUPPLEMENT)], strict=True)


def test_multiple_supplements_merge_and_deduplicate(tmp_path):
    base = tiny_training_csv(tmp_path / "base.csv")
    sup1 = write_csv(
        tmp_path / "sup1.csv",
        [("spam", "Another synthetic scam template"), ("ham", "Another synthetic ham template")],
    )
    sup2 = write_csv(
        tmp_path / "sup2.csv",
        [("spam", "Another synthetic scam template"), ("ham", "A third ham template")],
    )
    dataset = load_training_dataset(base, [sup1, sup2])
    assert len(dataset) == 9
    assert len(dataset.records) == 3
    assert any("duplicate" in warning for warning in dataset.warnings)
    paths, _ = resolve_supplement_paths([sup1, sup1, sup2], strict=True)
    assert paths == [sup1, sup2]


def test_cross_source_label_conflict_rejected(tmp_path):
    base = tiny_training_csv(tmp_path / "base.csv")
    supplement = write_csv(tmp_path / "conflict.csv", [("spam", "Salamat sa tulong mo kahapon")])
    with pytest.raises(DatasetError, match="conflicting labels"):
        load_training_dataset(base, [supplement])


def test_explicit_missing_supplement_fails_but_default_missing_is_skipped(tmp_path):
    base = tiny_training_csv(tmp_path / "base.csv")
    with pytest.raises(DatasetError, match="Supplement CSV not found"):
        load_training_dataset(base, tmp_path / "missing.csv", strict_supplement_paths=True)
    dataset = load_training_dataset(base, tmp_path / "missing.csv", strict_supplement_paths=False)
    assert len(dataset) == 6
    assert any("Optional supplement not found" in warning for warning in dataset.warnings)


def test_default_training_dataset_includes_all_three_supplements():
    if not DEFAULT_DATA.exists():
        pytest.skip("base dataset not downloaded")
    dataset = load_training_dataset()
    assert len(dataset.records) == 1 + len(DEFAULT_SUPPLEMENTS)
    loaded_paths = {Path(record.path) for record in dataset.records}
    assert {SUPPLEMENT, SUPPLEMENT_2, SUPPLEMENT_3} <= loaded_paths
    assert dataset.class_counts["ham"] > 1000
    assert dataset.class_counts["spam"] > 100


def test_supplement_files_have_both_classes_and_no_blank_messages():
    for path in (SUPPLEMENT, SUPPLEMENT_2, SUPPLEMENT_3):
        dataset = load_dataset(path, require_both_classes=True)
        assert dataset.class_counts["ham"] > 0
        assert dataset.class_counts["spam"] > 0
        assert all(message.strip() for message in dataset.messages)


def test_second_supplement_is_categorized_and_disjoint():
    dataset = load_dataset(SUPPLEMENT_2, require_both_classes=True)
    assert "category" in dataset.frame.columns
    assert dataset.frame["category"].ne("unknown").all()
    assert not (set(dataset.messages) & set(load_dataset(SUPPLEMENT).messages))
    assert not (set(dataset.messages) & set(load_holdout().messages))


def test_holdout_metadata_and_disjointness():
    holdout = load_holdout()
    assert holdout is not None
    assert holdout.class_counts["ham"] >= 20
    assert holdout.class_counts["spam"] >= 15
    for column in ("category", "language", "source", "labeling_confidence"):
        assert column in holdout.frame.columns
        assert holdout.frame[column].ne("unknown").all()
    supplement_messages = set()
    for path in (SUPPLEMENT, SUPPLEMENT_2, SUPPLEMENT_3):
        supplement_messages |= set(load_dataset(path).messages)
    assert not (set(holdout.messages) & supplement_messages)
    for example in BRIEF_EXAMPLES:
        assert example not in set(holdout.messages)
        assert example not in supplement_messages


def test_brief_examples_are_not_in_base_dataset():
    if not DEFAULT_DATA.exists():
        pytest.skip("base dataset not downloaded")
    base = load_dataset(DEFAULT_DATA)
    for example in BRIEF_EXAMPLES:
        assert example not in set(base.messages)


def test_holdout_exact_overlap_is_a_hard_error(tmp_path):
    base = tiny_training_csv(tmp_path / "base.csv")
    holdout_path = write_csv(
        tmp_path / "holdout.csv",
        [
            ("ham", "Salamat sa tulong mo kahapon"),
            ("ham", "We can meet at noon"),
            ("spam", "new scam one"),
            ("spam", "new scam two"),
        ],
    )
    training = load_training_dataset(base, None)
    holdout = load_dataset(holdout_path, role="holdout")
    with pytest.raises(DatasetError, match="leaks the answer"):
        group_leakage_report(training, holdout)


def test_repo_holdout_has_no_exact_leakage():
    if not DEFAULT_DATA.exists():
        pytest.skip("base dataset not downloaded")
    training = load_training_dataset()
    holdout = load_holdout()
    assert holdout is not None
    report = group_leakage_report(training, holdout)
    assert report["exact_message_overlap"] == 0


# ----------------------------- grouping / splitting -----------------------------


def test_group_key_masks_entities_and_separates_categories():
    first = make_group_key("Nag-claim ka ng ₱100,000 sa GMA Kapuso Foundation. Call 09171234567")
    second = make_group_key("Nag-claim ka ng ₱900,000 sa GMA Kapuso Foundation. Call 09185551234")
    assert first == second
    other = make_group_key("BDO account locked. Verify at http://bit.ly/x")
    assert other != first
    categorized = make_group_key("Same text", category="prize_scam")
    assert categorized.startswith("cat:prize_scam|")


def build_grouped_csv(path: Path, groups: int = 30) -> Path:
    rows = []
    for index in range(groups):
        rows.append(("ham", f"ordinary personal message {index}", f"ham-group-{index}"))
        rows.append(("spam", f"claim your prize message {index}", f"spam-group-{index}"))
    return write_csv(path, rows, columns=("label", "message", "group"))


def test_grouped_split_is_deterministic_and_leakage_free(tmp_path):
    dataset = load_dataset(build_grouped_csv(tmp_path / "grouped.csv"))
    first = grouped_splits(dataset, val_size=0.2, test_size=0.2, seed=7)
    second = grouped_splits(dataset, val_size=0.2, test_size=0.2, seed=7)
    assert first.splits == second.splits
    assert first.method == "stratified_group_kfold"
    assert first.as_dict(dataset.groups)["group_leakage"] == 0
    for indices in first.splits.values():
        labels = {dataset.labels[index] for index in indices}
        assert labels == {"ham", "spam"}
    assert set(first.train_idx).isdisjoint(first.val_idx)
    assert set(first.train_idx).isdisjoint(first.test_idx)
    assert set(first.val_idx).isdisjoint(first.test_idx)
    assert sum(first.sizes().values()) == len(dataset)


def test_random_split_is_labelled_as_diagnostic(tmp_path):
    dataset = load_dataset(build_grouped_csv(tmp_path / "grouped.csv"))
    split = grouped_splits(dataset, val_size=0.2, test_size=0.2, seed=1, split_by="random")
    assert split.method == "stratified_random"
    assert any("Group-aware" in warning or "Requested random" in warning for warning in split.warnings)


def test_split_dataset_returns_disjoint_frames(tmp_path):
    dataset = load_dataset(build_grouped_csv(tmp_path / "grouped.csv"))
    split = grouped_splits(dataset, val_size=0.2, test_size=0.2, seed=3)
    train, val, test = split_dataset(dataset, split)
    assert len(train) + len(val) + len(test) == len(dataset)
    assert not (set(train.messages) & set(val.messages))
    assert not (set(train.messages) & set(test.messages))


def test_legacy_wrappers_still_return_tuples(tmp_path):
    base = tiny_training_csv(tmp_path / "base.csv")
    messages, labels = legacy_load_dataset(base)
    assert len(messages) == len(labels) == 6
    messages, labels = legacy_load_training_data(base, None)
    assert len(messages) == 6
