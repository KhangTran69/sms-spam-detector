"""Regression checks for paired, message-free formatting diagnostics."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.corpus_audit import Corpus
from src.robustness_audit import audit, main

FIXTURE = Corpus("synthetic_holdout", ("first private marker", "second private marker"), ("ham", "spam"), ("digest",))


def test_paired_errors_distinguish_new_and_corrected_errors():
    def score(messages):
        if messages[0].isupper():
            return [0.9, 0.1]
        return [0.1, 0.9]

    result = audit(FIXTURE, score, 0.5)
    assert result["baseline_errors"] == {"fp": 0, "fn": 0}
    uppercase = result["variants"]["uppercase"]
    assert uppercase["changed_rows"] == 2
    assert uppercase["prediction_flips"] == 2
    assert uppercase["error_delta"] == {"fp": 1, "fn": 1}
    assert uppercase["new_errors"] == 2
    assert uppercase["corrected_errors"] == 0
    assert result["variants"]["decomposed_unicode"]["changed_rows"] == 0
    assert "private marker" not in json.dumps(result)


def test_corrections_are_counted_separately():
    result = audit(FIXTURE, lambda rows: [0.1, 0.9] if rows[0].isupper() else [0.9, 0.1], 0.5)
    assert result["variants"]["uppercase"]["corrected_errors"] == 2
    assert result["variants"]["uppercase"]["error_delta"] == {"fp": -1, "fn": -1}


@pytest.mark.parametrize("values", [[0.1], [float("nan"), 0.1], [-0.1, 0.5], [0.1, 1.1]])
def test_invalid_predictions_refused(values):
    with pytest.raises(ValueError, match="Invalid score vector"):
        audit(FIXTURE, lambda _: values, 0.5)


@pytest.mark.parametrize("threshold", [0, 1, float("nan")])
def test_invalid_threshold_refused(threshold):
    with pytest.raises(ValueError, match="fixed threshold"):
        audit(FIXTURE, lambda _: [0.1, 0.9], threshold)


def test_non_synthetic_and_single_class_refused():
    for corpus in (
        Corpus("tagalog", FIXTURE.messages, FIXTURE.labels, ("digest",)),
        Corpus("synthetic_holdout", FIXTURE.messages, ("ham", "ham"), ("digest",)),
        Corpus("synthetic_holdout", FIXTURE.messages, ("ham",), ("digest",)),
    ):
        with pytest.raises(ValueError, match="synthetic holdout"):
            audit(corpus, lambda _: [0.1, 0.9], 0.5)


def test_cli_binds_artifact_and_uses_only_tracked_holdout(monkeypatch, capsys):
    monkeypatch.setattr("src.robustness_audit.load_corpus", lambda role, paths: FIXTURE)
    monkeypatch.setattr(
        "src.robustness_audit.load_model",
        lambda path, identify_artifact: SimpleNamespace(threshold=0.5, artifact_sha256="model-digest"),
    )
    monkeypatch.setattr("src.robustness_audit.spam_probabilities", lambda bundle, messages: [0.1, 0.9])
    assert main(["--model", "trusted.pkl"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["model_sha256"] == "model-digest"
    assert result["class_counts"] == {"ham": 1, "spam": 1}


def test_cli_error_is_content_free(monkeypatch, capsys):
    def fail(*args):
        raise OSError("private path")

    monkeypatch.setattr("src.robustness_audit.load_corpus", fail)
    assert main(["--model", "trusted.pkl"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "private path" not in output.err
