"""Build/install the wheel in isolation and smoke-test its installed FastAPI app."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SMOKE = r"""
import os
import re
import sys
from pathlib import Path
from fastapi.testclient import TestClient
import api
import api.main as main
import api.macos_service
import src.benchmark
from sklearn.linear_model import LogisticRegression
from src.features import make_model, messages_to_frame
from src.predict import ModelBundle

# Prove imports and assets came from the installed wheel while outside its checkout.
site = Path(api.__file__).resolve().parent.parent
assert "site-packages" in str(site)
assert Path(os.environ["SMSD_SOURCE_ROOT"]).resolve() not in Path(api.__file__).resolve().parents
assert (Path(sys.executable).parent / "smsd-benchmark").is_file()
assert (Path(sys.executable).parent / "smsd-macos-service").is_file()
for asset in ("index.html", "styles.css", "app.js", "sw.js", "manifest.webmanifest", "icon.svg", "history-store.js", "connection-status.js", "result-format.js"):
    assert (main.WEB_DIR / asset).is_file(), asset
html = (main.WEB_DIR / "index.html").read_text()
assert 'id="tab-compare"' in html and 'id="panel-compare"' in html
app_js = (main.WEB_DIR / "app.js").read_text()
assert "async function runComparison()" in app_js
assert "function renderSafetyGuidance" in app_js
assert "const safetyGuidanceState = new WeakMap()" in app_js
assert 'id="safety-guidance"' in html
for asset in re.findall(r'(?:src|href)="(/static/[^"?#]+)', html):
    assert (main.WEB_DIR / Path(asset).name).is_file(), asset

client = TestClient(main.app)
print("wheel-smoke: imports/assets", flush=True)
assert client.get("/health").status_code == 200
print("wheel-smoke: liveness", flush=True)
assert client.get("/ready").status_code == 503
print("wheel-smoke: missing-model readiness", flush=True)
assert client.get("/ready").json()["error"]["code"] == "model_unavailable"
assert client.get("/").status_code == 200
assert client.get("/static/no-such-file").status_code == 404
assert client.get("/static/%2e%2e%2fpyproject.toml").status_code == 404
for name in ("app.js", "api-client.js", "i18n.js", "privacy-preview.js", "history-store.js", "connection-status.js", "result-format.js", "styles.css", "icon.svg"):
    get = client.get(f"/static/{name}")
    head = client.head(f"/static/{name}")
    assert get.status_code == head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(get.content))
    assert head.headers["cache-control"] == "no-cache"

print("wheel-smoke: static routes", flush=True)
pipeline = make_model(LogisticRegression(max_iter=200))
pipeline.fit(
    messages_to_frame(["ordinary family message", "meeting at school", "claim a prize now", "verify account urgently"]),
    ["ham", "ham", "spam", "spam"],
)
print("wheel-smoke: fit synthetic fixture", flush=True)
main._model = ModelBundle(
    pipeline=pipeline,
    threshold=0.5,
    suspicious_threshold=0.3,
    metadata={"model_version": "wheel-synthetic-smoke", "probability_calibrated": False},
)
assert client.get("/ready").status_code == 200
print("wheel-smoke: fixture readiness", flush=True)
result = client.post("/analyze", json={"message": "ordinary family message"})
assert result.status_code == 200, result.text
assert result.json()["prediction"] in {"ham", "spam"}
batch = client.post("/analyze/batch", json={"messages": ["meeting at school", "claim a prize now"]})
assert batch.status_code == 200 and len(batch.json()["results"]) == 2
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="smsd-wheel-smoke-") as temp_name:
        temp = Path(temp_name)
        wheels = temp / "wheels"
        wheels.mkdir()
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "--wheel-dir", str(wheels)],
            check=True,
            cwd=temp,
        )
        wheel = next(wheels.glob("*.whl"))
        venv = temp / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", f"{wheel}[dev]"], check=True, cwd=temp)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["SMSD_MODEL_PATH"] = str(temp / "missing-model.pkl")
        env["SMSD_SOURCE_ROOT"] = str(ROOT)
        subprocess.run([str(python), "-u", "-c", APP_SMOKE], check=True, cwd=temp, env=env, timeout=120)
    print("Installed-wheel smoke passed outside the source checkout (synthetic fixture only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
