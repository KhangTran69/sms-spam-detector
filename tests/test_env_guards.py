"""Import-time environment guard tests for api.main.

These guards run at module import (misconfigured env must fail loudly at
startup, not silently misconfigure the service). Each test reloads the module
in-process under a controlled environment so the guard lines are measured by
coverage, and a fixture restores a clean module state afterwards.
"""

from __future__ import annotations

import importlib

import pytest

import api.main as api_main


@pytest.fixture()
def restore_module(monkeypatch):
    yield
    monkeypatch.undo()
    importlib.reload(api_main)


def test_non_numeric_body_timeout_rejected(restore_module, monkeypatch):
    monkeypatch.setenv("SMSD_BODY_TIMEOUT_SECONDS", "not-a-number")
    with pytest.raises(ValueError, match="could not convert"):
        importlib.reload(api_main)


def test_non_finite_body_timeout_rejected(restore_module, monkeypatch):
    monkeypatch.setenv("SMSD_BODY_TIMEOUT_SECONDS", "nan")
    with pytest.raises(ValueError, match="finite"):
        importlib.reload(api_main)


def test_non_positive_in_flight_writes_rejected(restore_module, monkeypatch):
    monkeypatch.setenv("SMSD_MAX_IN_FLIGHT_WRITES", "0")
    with pytest.raises(ValueError, match="SMSD_MAX_IN_FLIGHT_WRITES"):
        importlib.reload(api_main)


def test_unknown_smsd_env_rejected(restore_module, monkeypatch):
    monkeypatch.setenv("SMSD_ENV", "staging")
    with pytest.raises(ValueError, match="SMSD_ENV"):
        importlib.reload(api_main)


def test_out_of_band_transformer_confidence_rejected(restore_module, monkeypatch):
    monkeypatch.setenv("SMSD_TRANSFORMER_CONFIDENCE_BAND", "0.9")
    with pytest.raises(RuntimeError, match="SMSD_TRANSFORMER_CONFIDENCE_BAND"):
        importlib.reload(api_main)


def test_non_numeric_transformer_confidence_rejected(restore_module, monkeypatch):
    monkeypatch.setenv("SMSD_TRANSFORMER_CONFIDENCE_BAND", "not-a-number")
    with pytest.raises(RuntimeError, match="SMSD_TRANSFORMER_CONFIDENCE_BAND"):
        importlib.reload(api_main)


def test_clean_environment_imports():
    importlib.reload(api_main)
