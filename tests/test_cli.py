"""Startup checks for the local server command."""

from __future__ import annotations

import errno
import sys
from pathlib import Path
from types import SimpleNamespace

from api import cli


def test_cli_reports_missing_runtime_dependencies_before_startup(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "missing_runtime_dependencies", lambda: ["uvicorn", "fastapi"])
    called = False

    def run_server(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run_server))

    assert cli.main([]) == 2
    assert not called
    error = capsys.readouterr().err
    assert "uvicorn, fastapi" in error
    assert "make dev-install" in error


def test_cli_warns_about_missing_model_but_keeps_ui_available(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(cli, "missing_runtime_dependencies", lambda: [])
    missing_model = tmp_path / "missing-model.pkl"
    monkeypatch.setattr("src.predict.default_model_path", lambda: missing_model)
    calls = []
    monkeypatch.setitem(
        sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)))
    )

    assert cli.main(["--port", "8123", "--reload"]) == 0
    assert calls == [(("api.main:app",), {"host": "127.0.0.1", "port": 8123, "reload": True})]
    error = capsys.readouterr().err
    assert str(missing_model) in error
    assert "web UI and health endpoint will start" in error
    assert "SMSD_MODEL_PATH" in error


def test_cli_explains_port_conflict(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "missing_runtime_dependencies", lambda: [])
    monkeypatch.setattr("src.predict.default_model_path", lambda: Path(__file__))

    def address_in_use(*args, **kwargs):
        raise OSError(errno.EADDRINUSE, "address already in use")

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=address_in_use))

    assert cli.main(["--port", "8000"]) == 1
    assert "port is already in use" in capsys.readouterr().err
