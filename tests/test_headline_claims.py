from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_headline_claims  # noqa: E402


def test_guard_flags_unsupported_headline_without_echoing_it(tmp_path, capsys):
    headline = "DO_NOT_ECHO_SMS: 99% accurate Philippine scam detector"
    document = tmp_path / "README.md"
    document.write_text(f"# {headline}\n", encoding="utf-8")

    status = check_headline_claims.main([str(document)])

    captured = capsys.readouterr()
    assert status == 1
    assert "unsupported performance claim" in captured.err
    assert str(document) in captured.err
    assert headline not in captured.out + captured.err
    assert "DO_NOT_ECHO_SMS" not in captured.out + captured.err


def test_guard_allows_explicit_evidence_limit_headlines(tmp_path):
    document = tmp_path / "MODEL_CARD.md"
    document.write_text("# No real-world accuracy is established\n", encoding="utf-8")

    assert check_headline_claims.main([str(document)]) == 0


def test_unrelated_negation_does_not_hide_accuracy_claim(tmp_path, capsys):
    document = tmp_path / "README.md"
    document.write_text("# No setup needed: 99% accurate detector\n", encoding="utf-8")

    assert check_headline_claims.main([str(document)]) == 1
    assert "unsupported performance claim" in capsys.readouterr().err


def test_explicit_disclaimer_does_not_hide_second_claim_in_same_headline(tmp_path, capsys):
    document = tmp_path / "README.md"
    document.write_text("# No real-world accuracy is established; 99% accurate detector\n", encoding="utf-8")

    assert check_headline_claims.main([str(document)]) == 1
    assert "unsupported performance claim" in capsys.readouterr().err


def test_guard_flags_unqualified_accurate_detector_claim(tmp_path, capsys):
    document = tmp_path / "README.md"
    document.write_text("# Highly accurate SMS detector\n", encoding="utf-8")

    assert check_headline_claims.main([str(document)]) == 1
    assert "unsupported performance claim" in capsys.readouterr().err


def test_guard_allows_directly_disclaimed_generic_accuracy_claim(tmp_path):
    document = tmp_path / "MODEL_CARD.md"
    document.write_text("# Not a highly accurate SMS detector\n", encoding="utf-8")

    assert check_headline_claims.main([str(document)]) == 0


def test_current_public_headlines_pass_guard(capsys):
    assert check_headline_claims.main([]) == 0
    assert "claim" not in capsys.readouterr().err.lower()
