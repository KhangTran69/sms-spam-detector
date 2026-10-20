import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_quality_gate  # noqa: E402


def _write(tmp_path, f1):
    payload = {
        "threshold": 0.5,
        "metrics": {
            "test_at_threshold": {"f1": f1, "precision": 0.9, "recall": 0.9, "n": 10},
            "calibration": {"test": {"expected_calibration_error": 0.01}},
        },
    }
    path = tmp_path / "meta.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_gate_passes_at_floor(tmp_path):
    assert check_quality_gate.main([str(_write(tmp_path, 0.90)), "--min-f1", "0.90"]) == 0


def test_gate_fails_below_floor(tmp_path):
    assert check_quality_gate.main([str(_write(tmp_path, 0.8625)), "--min-f1", "0.90"]) == 1
