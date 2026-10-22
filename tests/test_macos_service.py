from __future__ import annotations

import plistlib
from types import SimpleNamespace
from urllib.error import HTTPError

from api import macos_service


def test_install_writes_user_local_agent_without_message_arguments(monkeypatch, tmp_path) -> None:
    agent = tmp_path / "LaunchAgents" / "com.ph.smsd.plist"
    monkeypatch.setattr(macos_service, "launch_agent_path", lambda: agent)
    monkeypatch.setattr(macos_service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(macos_service.Path, "cwd", lambda: tmp_path / "checkout")
    monkeypatch.setattr(macos_service.sys, "platform", "darwin")
    calls = []

    def launchctl(arguments):
        calls.append(arguments)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(macos_service, "_loaded", lambda: False)
    monkeypatch.setattr(macos_service, "_launchctl", launchctl)
    monkeypatch.setattr("src.predict.default_model_path", lambda: tmp_path / "models" / "trusted.pkl")

    assert macos_service.main(["install", "--port", "8123"]) == 0
    definition = plistlib.loads(agent.read_bytes())
    assert definition["Label"] == macos_service.LABEL
    assert definition["ProgramArguments"][-2:] == ["--port", "8123"]
    assert definition["ProgramArguments"][2] == "api.cli"
    assert definition["WorkingDirectory"] == str(tmp_path / "checkout")
    assert definition["EnvironmentVariables"]["SMSD_MODEL_PATH"].endswith("models/trusted.pkl")
    assert definition["KeepAlive"] == {"SuccessfulExit": False}
    assert "StandardErrorPath" in definition
    assert calls == [["bootstrap", f"gui/{macos_service.os.getuid()}", str(agent)]]
    assert macos_service._configured_port(agent) == 8123


def test_restart_reloads_an_installed_agent(monkeypatch, tmp_path) -> None:
    agent = tmp_path / "com.ph.smsd.plist"
    agent.write_text("plist", encoding="utf-8")
    monkeypatch.setattr(macos_service, "launch_agent_path", lambda: agent)
    monkeypatch.setattr(macos_service.sys, "platform", "darwin")
    state = {"loaded": True}
    monkeypatch.setattr(macos_service, "_loaded", lambda: state["loaded"])
    calls = []

    def launchctl(arguments):
        calls.append(arguments)
        if arguments[0] == "bootout":
            state["loaded"] = False
        elif arguments[0] == "bootstrap":
            state["loaded"] = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(macos_service, "_launchctl", launchctl)
    assert macos_service.main(["restart"]) == 0
    domain = f"gui/{macos_service.os.getuid()}"
    assert calls == [["bootout", domain, str(agent)], ["bootstrap", domain, str(agent)]]


def test_uninstall_removes_agent_after_stopping(monkeypatch, tmp_path) -> None:
    agent = tmp_path / "com.ph.smsd.plist"
    agent.write_text("plist", encoding="utf-8")
    monkeypatch.setattr(macos_service, "launch_agent_path", lambda: agent)
    monkeypatch.setattr(macos_service.sys, "platform", "darwin")
    monkeypatch.setattr(macos_service, "_loaded", lambda: True)
    monkeypatch.setattr(macos_service, "_launchctl", lambda _args: SimpleNamespace(returncode=0, stdout="", stderr=""))

    assert macos_service.main(["uninstall"]) == 0
    assert not agent.exists()


def test_status_distinguishes_loaded_process_from_model_readiness(monkeypatch, tmp_path, capsys) -> None:
    agent = tmp_path / "com.ph.smsd.plist"
    agent.write_bytes(plistlib.dumps({"ProgramArguments": ["python", "-m", "api.cli", "--port", "8124"]}))
    monkeypatch.setattr(macos_service, "launch_agent_path", lambda: agent)
    monkeypatch.setattr(macos_service.sys, "platform", "darwin")
    monkeypatch.setattr(
        macos_service, "_launchctl", lambda _args: SimpleNamespace(returncode=0, stdout="loaded", stderr="")
    )

    class Healthy:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def check_url(url, timeout):
        assert timeout in {1, 2}
        if url.endswith("/health"):
            return Healthy()
        raise HTTPError(url, 503, "model unavailable", {}, None)

    monkeypatch.setattr(macos_service, "urlopen", check_url)
    assert macos_service.main(["status"]) == 1
    output = capsys.readouterr().out
    assert "LaunchAgent is loaded" in output
    assert "API: reachable" in output
    assert "Model: unavailable" in output
