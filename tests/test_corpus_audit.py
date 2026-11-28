"""Synthetic-only tests for the cross-corpus leakage diagnostic."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.corpus_audit import PUBLIC_IDS, Corpus, audit, load_corpus, main

PRIVATE_MARKER = "Synthetic fixture for overlap detection only"
SECOND = "This fictional long notice confirms the scheduled delivery window for the parcel tomorrow."
VARIANT = "This fictional long notice confirms the scheduled delivery window for the parcel today."


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
