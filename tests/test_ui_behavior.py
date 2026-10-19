"""Execute UI logic with a minimal DOM to reproduce request races and Unicode offsets."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_ui_request_races_and_unicode():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for executable UI regressions")
    script = Path(__file__).with_name("ui_behavior.cjs")
    subprocess.run([node, str(script)], check=True, capture_output=True, text=True)
