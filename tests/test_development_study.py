"""Development experiments are isolated from frozen evidence and production artifacts."""

from __future__ import annotations

import csv
import hashlib
import json

import pytest

from src.corpus_audit import Corpus, load_corpus
from src.development_study import FROZEN_INPUTS, canonical_message, main, study

ROWS = [
    ("Please bring the blue folder tomorrow", "ham"),
    ("Dinner is ready in the kitchen", "ham"),
    ("Our garden needs watering this morning", "ham"),
    ("The library closes early on Friday", "ham"),
    ("Your appointment moved to Thursday", "ham"),
    ("We can walk home after school", "ham"),
    ("Congratulations on the fictional prize", "spam"),
    ("Exclusive imaginary cash reward", "spam"),
    ("Unsolicited promotional offer awaits", "spam"),
    ("Fictional urgent account warning", "spam"),
    ("Pretend advertisement for a giveaway", "spam"),
    ("Claim the imaginary bonus today", "spam"),
]


def _fixture(tmp_path):
    path = tmp_path / "development.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["message", "label", "data_kind"])
        writer.writerows([message, label, "synthetic"] for message, label in ROWS)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_development_study_real_fit_and_paired_formatting(tmp_path, capsys):
    path, digest = _fixture(tmp_path)
    argv = ["--role", "synthetic_training", "--development", str(path), "--approved-sha256", digest, "--folds", "2"]
    assert main(argv) == 0
    raw = capsys.readouterr().out
    report = json.loads(raw)
    assert report["purpose"] == "development_comparison_only"
    assert report["source_sha256"] == digest
    assert len(report["folds"]) == 2
    assert sum(fold["validation_rows"] for fold in report["folds"]) == len(ROWS)
    assert len({fold["sha256"] for fold in report["folds"]}) == 2
    assert len(report["recipes"]) == 4
    for recipe in report["recipes"]:
        assert recipe["metrics"]["support"] == len(ROWS)
        if recipe["canonical_input"]:
            assert all(recipe["formatting"][name]["prediction_flips"] == 0 for name in ("uppercase", "whitespace"))
    assert not any(message in raw for message, _ in ROWS)
    assert list(tmp_path.iterdir()) == [path]


def test_canonical_input_is_case_and_whitespace_invariant():
    assert canonical_message("  HÉLLO  WORLD\t") == canonical_message("héllo world")


def test_snapshot_hash_and_frozen_inputs_fail_closed(tmp_path, capsys):
    path, digest = _fixture(tmp_path)
    corpus = load_corpus("synthetic_training", [path])
    with pytest.raises(ValueError, match="fingerprint"):
        study(corpus, "0" * 64)
    frozen = next(iter(FROZEN_INPUTS))
    assert main(["--role", "tagalog", "--development", str(path), "--approved-sha256", frozen]) == 2
    assert capsys.readouterr().out == ""
    assert digest not in capsys.readouterr().err


def test_duplicate_and_conflicting_labels_refused():
    digest = "1" * 64
    corpus = Corpus("synthetic_training", ("Test one", "TEST ONE", "Test two", "Test three"),
                    ("ham", "spam", "ham", "spam"), (digest,))
    with pytest.raises(ValueError, match="duplicates"):
        study(corpus, digest, folds=2)


def test_cross_fold_overlap_prevents_fit(tmp_path, monkeypatch):
    path, digest = _fixture(tmp_path)
    corpus = load_corpus("synthetic_training", [path])
    monkeypatch.setattr(
        "src.development_study.compare_corpora",
        lambda *args: {
            "normalized": {"row_pairs": 0},
            "category_independent_template": {"row_pairs": 0},
            "near_duplicate_pairs_excluding_normalized": 1,
        },
    )
    with pytest.raises(ValueError, match="near-duplicate"):
        study(corpus, digest, folds=2)
