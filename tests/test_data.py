"""Data-quality checks for the synthetic Philippine pattern files."""
from pathlib import Path

import pytest

from src.evaluate import PHILIPPINE_EXAMPLES
from src.train import load_dataset

ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENT = ROOT / "data" / "raw" / "ph_supplement.csv"
SUPPLEMENT_2 = ROOT / "data" / "raw" / "ph_supplement_2.csv"
HOLDOUT = ROOT / "data" / "raw" / "ph_holdout.csv"


def test_supplement_loads_with_both_classes():
    messages, labels = load_dataset(SUPPLEMENT)
    assert set(labels) == {"ham", "spam"}
    assert len(messages) == len(labels) > 50
    assert all(isinstance(m, str) and m.strip() for m in messages)


def test_holdout_loads_with_both_classes():
    messages, labels = load_dataset(HOLDOUT)
    assert set(labels) == {"ham", "spam"}
    assert len(messages) == len(labels) >= 15


def test_supplement_and_holdout_are_disjoint():
    supplement_messages, _ = load_dataset(SUPPLEMENT)
    holdout_messages, _ = load_dataset(HOLDOUT)
    assert not (set(supplement_messages) & set(holdout_messages))


def test_brief_examples_are_not_in_training_or_holdout():
    """Leakage guard: the three diagnostic examples must stay out of the data files."""
    supplement_messages, _ = load_dataset(SUPPLEMENT)
    supplement_2_messages, _ = load_dataset(SUPPLEMENT_2)
    holdout_messages, _ = load_dataset(HOLDOUT)
    for example in PHILIPPINE_EXAMPLES:
        assert example not in supplement_messages
        assert example not in supplement_2_messages
        assert example not in holdout_messages


def test_second_supplement_loads_with_both_classes():
    messages, labels = load_dataset(SUPPLEMENT_2)
    assert set(labels) == {"ham", "spam"}
    assert len(messages) == len(labels) > 200
    assert labels.count("spam") > labels.count("ham")  # scam-category-heavy by design
    assert all(isinstance(m, str) and m.strip() for m in messages)


def test_second_supplement_is_disjoint_from_other_files():
    supplement_2_messages, _ = load_dataset(SUPPLEMENT_2)
    supplement_messages, _ = load_dataset(SUPPLEMENT)
    holdout_messages, _ = load_dataset(HOLDOUT)
    assert not (set(supplement_2_messages) & set(supplement_messages))
    assert not (set(supplement_2_messages) & set(holdout_messages))


@pytest.mark.skipif(not (ROOT / "data" / "raw" / "spam.csv").exists(), reason="base dataset not downloaded")
def test_merged_supplements_deduplicate_across_files():
    from src.train import load_training_data

    messages, labels = load_training_data(
        ROOT / "data" / "raw" / "spam.csv", (SUPPLEMENT, SUPPLEMENT_2)
    )
    assert len(messages) == len(set(messages))
    assert any("Mayor's office" in m for m in messages)  # supplement_2 content merged


@pytest.mark.skipif(not (ROOT / "data" / "raw" / "spam.csv").exists(), reason="base dataset not downloaded")
def test_base_dataset_loads():
    messages, labels = load_dataset(ROOT / "data" / "raw" / "spam.csv")
    assert set(labels) == {"ham", "spam"}
    assert len(messages) > 1000
