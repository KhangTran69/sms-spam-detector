"""Executable service-worker update and cache-boundary regressions."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_service_worker_update_is_atomic_and_static_only():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for service-worker behavior regressions")
    script = Path(__file__).with_name("service_worker_behavior.cjs")
    subprocess.run([node, str(script)], check=True, capture_output=True, text=True)
