"""``smsd-serve``: run the API and bundled web UI with uvicorn."""

from __future__ import annotations

import argparse
import importlib.util
import sys

RUNTIME_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "numpy": "numpy",
    "pandas": "pandas",
    "sklearn": "scikit-learn",
    "joblib": "joblib",
    "pydantic": "pydantic",
    "matplotlib": "matplotlib",
}


def missing_runtime_dependencies() -> list[str]:
    """Return package names that the API needs but the current Python lacks."""
    missing = []
    for module, package in RUNTIME_MODULES.items():
        try:
            available = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            available = False
        if not available:
            missing.append(package)
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the SMS spam/scam detector API and web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="restart the development server when Python files change")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if sys.version_info < (3, 11):  # noqa: UP036 — keep direct source execution actionable
        print("Cannot start the detector: Python 3.11 or newer is required.", file=sys.stderr)
        return 2

    missing = missing_runtime_dependencies()
    if missing:
        print(
            "Cannot start the detector: missing runtime packages "
            f"{', '.join(missing)}. Install them with `python -m pip install -r requirements.txt` "
            "or `make dev-install`.",
            file=sys.stderr,
        )
        return 2

    try:
        from src.predict import default_model_path
    except ModuleNotFoundError as error:
        package = error.name or "a runtime dependency"
        print(
            f"Cannot start the detector: Python package {package!r} is missing. "
            "Install project dependencies with `python -m pip install -r requirements.txt`.",
            file=sys.stderr,
        )
        return 2

    artifact = default_model_path()
    if not artifact.is_file():
        print(
            f"Model artifact not found at {artifact}. The web UI and health endpoint will start, "
            "but analysis will return 503 until a model is available. Train one with "
            "`python -m src.train` or set SMSD_MODEL_PATH to an existing trusted artifact.",
            file=sys.stderr,
        )

    import uvicorn

    try:
        uvicorn.run("api.main:app", host=args.host, port=args.port, reload=args.reload)
    except OSError as error:
        if error.errno in {48, 98, 10048}:
            print(
                f"Cannot listen on {args.host}:{args.port}: the port is already in use. "
                "Stop the identified local server or choose another port with --port.",
                file=sys.stderr,
            )
            return 1
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
