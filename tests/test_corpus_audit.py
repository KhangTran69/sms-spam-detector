"""Synthetic-only tests for the cross-corpus leakage diagnostic."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.corpus_audit import COSINE_THRESHOLD, PUBLIC_IDS, SEQUENCE_THRESHOLD, Corpus, audit, load_corpus, main

PRIVATE_MARKER = "Synthetic fixture for overlap detection only"
SECOND = "This fictional long notice confirms the scheduled delivery window for the parcel tomorrow."
VARIANT = "This fictional long notice confirms the scheduled delivery window for the parcel tomorrow!"


def _write(path: Path, role: str, rows: list[tuple[str, str]], *, kind: str = "public") -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["message", "label", "data_kind", "dataset_id"])
        for message, label in rows:
            writer.writerow([message, label, kind, PUBLIC_IDS.get(role, "")])
    return path


def test_audit_preserves_duplicate_counts_and_label_conflicts(tmp_path, capsys):
    left = _write(tmp_path / "private-left.csv", "uci", [(PRIVATE_MARKER, "ham"), (PRIVATE_MARKER, "ham")])
    right = _write(
        tmp_path / "private-right.csv",
        "tagalog",
        [(PRIVATE_MARKER, "spam"), ("  " + PRIVATE_MARKER.upper(), "ham"), (SECOND, "ham")],
    )
    assert main(["--uci", str(left), "--tagalog", str(right)]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    pair = report["comparisons"][0]
    assert pair["exact"]["row_pairs"] == 2
    assert pair["normalized"] == {"distinct_keys": 1, "left_rows": 2, "right_rows": 2, "row_pairs": 4}
    assert pair["normalized_conflicting_label_pairs"] == 2
    assert report["corpora"][0]["source_sha256"] == [hashlib.sha256(left.read_bytes()).hexdigest()]
    assert PRIVATE_MARKER not in captured.out
    assert SECOND not in captured.out
    assert left.name not in captured.out
    assert captured.err == ""


def test_near_duplicates_are_separate_from_normalized_and_template_overlap():
    left = Corpus("uci", (SECOND,), ("ham",), ("left",))
    right = Corpus("tagalog", (SECOND, VARIANT), ("ham", "spam"), ("right",))
    pair = audit([left, right])["comparisons"][0]
    assert pair["normalized"]["row_pairs"] == 1
    assert pair["category_independent_template"]["row_pairs"] == 2
    assert pair["near_duplicate_pairs_excluding_normalized"] == 1
    assert pair["near_duplicate_conflicting_label_pairs"] == 1
    assert pair["near_duplicate_left_rows"] == pair["near_duplicate_right_rows"] == 1
    vectors = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit_transform(
        [SECOND.casefold(), SECOND.casefold(), VARIANT.casefold()]
    )
    assert cosine_similarity(vectors[:1], vectors[2:])[0, 0] >= COSINE_THRESHOLD
    assert COSINE_THRESHOLD == SEQUENCE_THRESHOLD == 0.90


@pytest.mark.parametrize("kind", ["consented", "synthetic", "unknown"])
def test_rejects_non_public_data(tmp_path, capsys, kind):
    path = _write(tmp_path / "private.csv", "uci", [(PRIVATE_MARKER, "ham")], kind=kind)
    assert main(["--uci", str(path), "--include-synthetic"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert PRIVATE_MARKER not in captured.err
    assert path.name not in captured.err


def test_rejects_wrong_dataset_identity(tmp_path):
    path = _write(tmp_path / "wrong.csv", "tagalog", [(PRIVATE_MARKER, "ham")])
    with pytest.raises(ValueError, match="provenance"):
        load_corpus("uci", [path])


@pytest.mark.parametrize("message,label", [("", "ham"), ("text", "unknown")])
def test_invalid_row_is_not_silently_skipped(tmp_path, message, label):
    path = _write(tmp_path / "invalid.csv", "uci", [(message, label)])
    with pytest.raises(ValueError, match="Invalid message"):
        load_corpus("uci", [path])


def test_missing_file_and_insufficient_corpora_are_clean_errors(tmp_path, capsys):
    assert main(["--uci", str(tmp_path / "not-present.csv")]) == 2
    assert main([]) == 2
    assert "not-present" not in capsys.readouterr().err


def test_bounded_rows_and_bytes(tmp_path, monkeypatch):
    path = _write(tmp_path / "fixture.csv", "uci", [(PRIVATE_MARKER, "ham"), (SECOND, "spam")])
    monkeypatch.setattr("src.corpus_audit.MAX_ROWS", 1)
    with pytest.raises(ValueError, match="row budget"):
        load_corpus("uci", [path])
    monkeypatch.setattr("src.corpus_audit.MAX_BYTES", 10)
    with pytest.raises(ValueError, match="byte budget"):
        load_corpus("uci", [path])


def test_tracked_synthetic_audit_runs_without_private_inputs(capsys):
    assert main(["--include-synthetic"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["comparisons"]) == 1
    assert [corpus["role"] for corpus in report["corpora"]] == ["synthetic_training", "synthetic_holdout"]
    assert all(corpus["rows"] > 0 for corpus in report["corpora"])


def test_sequence_work_limit_refuses_instead_of_emitting_partial_counts(monkeypatch):
    left = Corpus("uci", (SECOND,), ("ham",), ("left",))
    right = Corpus("tagalog", (SECOND, VARIANT), ("ham", "spam"), ("right",))
    monkeypatch.setattr("src.corpus_audit.MAX_SEQUENCE_WORK", 1)
    with pytest.raises(ValueError, match="sequence comparison work budget"):
        audit([left, right])


@pytest.mark.parametrize("cosine,expected", [(0.899999, 0), (0.90, 1), (0.900001, 1)])
def test_cosine_boundary_is_inclusive_without_counting_exact_pairs(monkeypatch, cosine, expected):
    left = Corpus("uci", (SECOND,), ("ham",), ("left",))
    right = Corpus("tagalog", (SECOND, VARIANT), ("ham", "spam"), ("right",))
    monkeypatch.setattr("src.corpus_audit.cosine_similarity", lambda *args: np.array([[1.0, cosine]]))
    pair = audit([left, right])["comparisons"][0]
    assert pair["normalized"]["row_pairs"] == 1
    assert pair["near_duplicate_pairs_excluding_normalized"] == expected


def test_high_cosine_alone_does_not_pass_sequence_gate(monkeypatch):
    left = Corpus("uci", ("Fictional alphabetical text",), ("ham",), ("left",))
    right = Corpus("tagalog", ("Unrelated imaginary notice",), ("spam",), ("right",))
    monkeypatch.setattr("src.corpus_audit.cosine_similarity", lambda *args: np.array([[1.0]]))
    assert audit([left, right])["comparisons"][0]["near_duplicate_pairs_excluding_normalized"] == 0


def test_within_corpus_conflict_pairs_preserve_multiplicity():
    left = Corpus("uci", (SECOND, SECOND.upper(), SECOND), ("ham", "spam", "ham"), ("left",))
    right = Corpus("tagalog", (VARIANT,), ("ham",), ("right",))
    report = audit([left, right])
    assert report["corpora"][0]["within_corpus"] == {
        "normalized_duplicate_rows": 2,
        "normalized_conflicting_keys": 1,
        "normalized_conflicting_label_pairs": 2,
    }


@pytest.mark.parametrize("role", ["unknown", "consented"])
def test_unsupported_role_refused_before_opening(role, tmp_path):
    with pytest.raises(ValueError, match="Unsupported corpus role"):
        load_corpus(role, [tmp_path / "absent"])


def test_empty_and_malformed_csv_are_not_partial_successes(tmp_path):
    path = _write(tmp_path / "empty.csv", "uci", [])
    with pytest.raises(ValueError, match="empty"):
        load_corpus("uci", [path])
    path.write_text("message,label,data_kind,dataset_id\nmissing columns,ham\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed CSV row"):
        load_corpus("uci", [path])
