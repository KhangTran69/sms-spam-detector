"""Manage a per-user macOS LaunchAgent for the local detector."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

LABEL = "com.ph.smsd"


def launch_agent_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _loaded() -> bool:
    return _launchctl(["print", f"{_domain()}/{LABEL}"]).returncode == 0


def _configured_port(path: Path) -> int:
    try:
        definition = plistlib.loads(path.read_bytes())
        arguments = definition.get("ProgramArguments", [])
        return int(arguments[arguments.index("--port") + 1])
    except (OSError, ValueError, IndexError, TypeError, plistlib.InvalidFileException):
        return 8000


def _write_agent(path: Path, *, port: int, model: Path, working_directory: Path) -> None:
    log_dir = Path.home() / "Library" / "Logs" / "ph-smsd"
    log_dir.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    definition = {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "api.cli",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        "WorkingDirectory": str(working_directory.resolve()),
        "EnvironmentVariables": {
            "SMSD_MODEL_PATH": str(model.expanduser().resolve()),
            "PYTHONUNBUFFERED": "1",
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "StandardOutPath": str(log_dir / "service.out.log"),
        "StandardErrorPath": str(log_dir / "service.err.log"),
    }
    temporary = path.with_suffix(".plist.tmp")
    temporary.write_bytes(plistlib.dumps(definition, sort_keys=True))
    temporary.replace(path)


def _start(path: Path) -> int:
    if not path.is_file():
        print("LaunchAgent is not installed. Run `smsd-macos-service install` first.", file=sys.stderr)
        return 1
    if _loaded():
        result = _launchctl(["kickstart", "-k", f"{_domain()}/{LABEL}"])
    else:
        result = _launchctl(["bootstrap", _domain(), str(path)])
    if result.returncode:
        print(result.stderr.strip() or "launchctl could not start the detector.", file=sys.stderr)
        return 1
    print("Local detector LaunchAgent started.")
    return 0


def _stop(path: Path) -> int:
    if not _loaded():
        print("Local detector LaunchAgent is already stopped.")
        return 0
    result = _launchctl(["bootout", _domain(), str(path)])
    if result.returncode:
        print(result.stderr.strip() or "launchctl could not stop the detector.", file=sys.stderr)
        return 1
    print("Local detector LaunchAgent stopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the local detector's macOS LaunchAgent.")
    parser.add_argument("action", choices=("install", "start", "stop", "status", "restart", "uninstall"))
    parser.add_argument("--port", type=int, default=8000, help="Local API port used by install (default: 8000).")
    parser.add_argument("--model", type=Path, default=None, help="Trusted model artifact used by install.")
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        print("This command manages macOS LaunchAgents and must run on macOS.", file=sys.stderr)
        return 2
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    path = launch_agent_path()
    try:
        if args.action == "install":
            from src.predict import default_model_path

            model = args.model or default_model_path()
            _write_agent(path, port=args.port, model=model, working_directory=Path.cwd())
            return _start(path)
        if args.action == "start":
            return _start(path)
        if args.action == "stop":
            return _stop(path)
        if args.action == "restart":
            stopped = _stop(path)
            return stopped if stopped else _start(path)
        if args.action == "uninstall":
            stopped = _stop(path)
            if stopped:
                return stopped
            path.unlink(missing_ok=True)
            print("Local detector LaunchAgent uninstalled.")
            return 0
        result = _launchctl(["print", f"{_domain()}/{LABEL}"])
        if result.returncode:
            print("Local detector LaunchAgent is stopped.")
            return 1
        port = _configured_port(path)
        print("Local detector LaunchAgent is loaded.")
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                print(f"Detector API: reachable (HTTP {response.status})")
        except (OSError, URLError):
            print(f"Detector API: unavailable at 127.0.0.1:{port}")
            return 1
        try:
            with urlopen(f"http://127.0.0.1:{port}/ready", timeout=2) as response:
                print(f"Model: ready (HTTP {response.status})")
        except HTTPError as error:
            print(f"Model: unavailable (HTTP {error.code}); check SMSD_MODEL_PATH and service.err.log")
            return 1
        except (OSError, URLError):
            print("Model: readiness check failed; retry status after startup completes")
            return 1
        return 0
    except FileNotFoundError as error:
        print(
            f"Cannot manage the LaunchAgent: {error}. Install Xcode command-line tools or use macOS launchctl.",
            file=sys.stderr,
        )
        return 2
    except OSError as error:
        print(f"Cannot manage the LaunchAgent at {path}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
