from __future__ import annotations

from argparse import Namespace

import pandas as pd

from src.benchmark import _commands, main
from src.data import Dataset
from src.evaluate import _baseline_report


def test_benchmark_commands_are_explicit_and_do_not_default_to_hidden_supplements(tmp_path) -> None:
    args = Namespace(
        data=tmp_path / "approved.csv",
        supplement=None,
        holdout=None,
        model_version="candidate-v1",
        seed=17,
        split_by="group",
        text_features="combined",
        threshold_policy="cv-robust",
        val_size=0.15,
        test_size=0.15,
        target_precision=0.95,
        min_recall=0.8,
    )
    train, evaluate = _commands(args, tmp_path / "candidate.pkl", tmp_path / "benchmark.json")

    assert "--no-supplements" in train and "--no-supplements" in evaluate
    assert "--data" in train and str(args.data) in train
    assert "--holdout" in train and "none" in train
    assert "--seed" in train and "17" in train
    assert "--threshold-policy" in train and "cv-robust" in train
    assert "--json-out" in evaluate and str(tmp_path / "benchmark.json") in evaluate
    assert not any("message" in arg.lower() for arg in train + evaluate)


def test_benchmark_rejects_missing_input_before_creating_outputs(tmp_path, capsys) -> None:
    output = tmp_path / "result"
    assert main(["--data", str(tmp_path / "missing.csv"), "--output-dir", str(output)]) == 2
    assert "input file(s) not found" in capsys.readouterr().err
    assert not output.exists()


def test_benchmark_rejects_existing_outputs_without_overwriting(tmp_path, capsys) -> None:
    output = tmp_path / "result"
    output.mkdir()
    (output / "benchmark.json").write_text("protected", encoding="utf-8")
    data = tmp_path / "data.csv"
    data.write_text("label,message\nham,hello\nspam,prize\n", encoding="utf-8")
    assert main(["--data", str(data), "--output-dir", str(output)]) == 2
    assert (output / "benchmark.json").read_text(encoding="utf-8") == "protected"
    assert "already exist" in capsys.readouterr().err


def test_report_includes_same_split_multinomial_baseline_without_message_text() -> None:
    train = Dataset(
        pd.DataFrame(
            {
                "message": ["meeting at noon", "cheap prize offer", "project notes", "claim free gift"],
                "label": ["ham", "spam", "ham", "spam"],
                "group": ["a", "b", "c", "d"],
                "data_kind": ["public"] * 4,
            }
        )
    )
    test = Dataset(
        pd.DataFrame(
            {
                "message": ["ordinary meeting", "claim your prize"],
                "label": ["ham", "spam"],
                "group": ["e", "f"],
                "data_kind": ["synthetic", "synthetic"],
            }
        )
    )

    report = _baseline_report(train, test, text_features="word", seed=42)

    assert report["name"] == "MultinomialNB"
    assert report["fit_split"] == "train"
    assert report["at_threshold"]["support"] == 2
    assert report["by_data_kind"][0]["data_kind"] == "synthetic"
    assert report["by_data_kind"][0]["support"] == 2
    assert "ordinary meeting" not in str(report)
