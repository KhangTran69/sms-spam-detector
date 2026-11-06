import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_quality_gate  # noqa: E402


def _write(tmp_path, f1, *, holdout_kind=None, license_name=None, languages=None):
    payload = {
        "threshold": 0.5,
        "metrics": {
            "test_at_threshold": {"f1": f1, "precision": 0.9, "recall": 0.9, "n": 10},
            "calibration": {"test": {"expected_calibration_error": 0.01}},
        },
    }
    if holdout_kind is not None:
        payload["holdout_source"] = {
            "role": "holdout",
            "sha256": "a" * 64,
            "rows_loaded": 20,
            "data_kind_counts": {holdout_kind: 20},
            "language_counts": languages or {"unknown": 20},
            "provenance": {"license": license_name or "unknown", "dataset_id": "fixture-dataset"},
        }
        payload["metrics"]["holdout_at_threshold"] = {
            "threshold": 0.5,
            "precision": 0.75,
            "recall": 0.75,
            "f1": 0.75,
            "accuracy": 14 / 18,
            "false_positive_rate": 0.2,
            "predicted_spam_rate": 8 / 18,
            "tp": 6,
            "fp": 2,
            "tn": 8,
            "fn": 2,
            "support": 18,
            "support_spam": 8,
            "support_ham": 10,
        }
    path = tmp_path / "meta.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_gate_passes_at_floor(tmp_path):
    assert check_quality_gate.main([str(_write(tmp_path, 0.90)), "--min-f1", "0.90"]) == 0


def test_gate_fails_below_floor(tmp_path):
    assert check_quality_gate.main([str(_write(tmp_path, 0.8625)), "--min-f1", "0.90"]) == 1


def test_required_real_holdout_has_distinct_failure_for_synthetic_data(tmp_path, capsys):
    path = _write(tmp_path, 0.90, holdout_kind="synthetic")

    status = check_quality_gate.main([str(path), "--require-real-holdout"])

    captured = capsys.readouterr()
    assert status == 2
    assert "holdout_class=synthetic" in captured.out
    assert "--require-real-holdout" in captured.err
    assert "SMS" not in captured.out + captured.err


def test_required_real_holdout_accepts_licensed_public_english_data(tmp_path):
    path = _write(
        tmp_path,
        0.90,
        holdout_kind="public",
        license_name="CC BY 4.0",
        languages={"en": 20},
    )

    assert check_quality_gate.main([str(path), "--require-real-holdout"]) == 0


def test_required_real_holdout_accepts_consented_data(tmp_path):
    path = _write(tmp_path, 0.90, holdout_kind="consented")

    assert check_quality_gate.main([str(path), "--require-real-holdout"]) == 0


def test_required_real_holdout_rejects_unlicensed_public_data(tmp_path):
    path = _write(tmp_path, 0.90, holdout_kind="public", license_name="unknown", languages={"en": 20})

    assert check_quality_gate.main([str(path), "--require-real-holdout"]) == 2


def test_required_real_holdout_rejects_mixed_provenance(tmp_path):
    path = _write(tmp_path, 0.90, holdout_kind="public")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["holdout_source"]["data_kind_counts"] = {"public": 10, "synthetic": 10}
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert check_quality_gate.main([str(path), "--require-real-holdout"]) == 2


def test_required_real_holdout_requires_source_hash_and_row_counts(tmp_path):
    path = _write(tmp_path, 0.90, holdout_kind="public", license_name="CC BY 4.0", languages={"en": 20})
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["holdout_source"]["sha256"] = "not-a-digest"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert check_quality_gate.main([str(path), "--require-real-holdout"]) == 2


def test_required_real_holdout_rejects_empty_evaluation_metrics(tmp_path):
    path = _write(tmp_path, 0.90, holdout_kind="consented")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"]["holdout_at_threshold"] = {}
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert check_quality_gate.main([str(path), "--require-real-holdout"]) == 2


def test_required_real_holdout_rejects_zero_evaluated_support(tmp_path):
    path = _write(tmp_path, 0.90, holdout_kind="consented")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"]["holdout_at_threshold"]["support"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert check_quality_gate.main([str(path), "--require-real-holdout"]) == 2


def test_required_real_holdout_rejects_malformed_evaluation_metrics(tmp_path):
    path = _write(tmp_path, 0.90, holdout_kind="consented")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"]["holdout_at_threshold"]["f1"] = "not-a-score"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert check_quality_gate.main([str(path), "--require-real-holdout"]) == 2


def test_required_real_holdout_rejects_scores_inconsistent_with_counts(tmp_path):
    path = _write(tmp_path, 0.90, holdout_kind="consented")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"]["holdout_at_threshold"]["f1"] = 0.99
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert check_quality_gate.main([str(path), "--require-real-holdout"]) == 2
