"""Data-quality checks for the synthetic Philippine pattern files."""
from pathlib import Path

import pytest

from src.evaluate import PHILIPPINE_EXAMPLES
from src.train import load_dataset

ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENT = ROOT / "data" / "raw" / "ph_supplement.csv"
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
    holdout_messages, _ = load_dataset(HOLDOUT)
    for example in PHILIPPINE_EXAMPLES:
        assert example not in supplement_messages
        assert example not in holdout_messages


@pytest.mark.skipif(not (ROOT / "data" / "raw" / "spam.csv").exists(), reason="base dataset not downloaded")
def test_base_dataset_loads():
    messages, labels = load_dataset(ROOT / "data" / "raw" / "spam.csv")
    assert set(labels) == {"ham", "spam"}
    assert len(messages) > 1000
