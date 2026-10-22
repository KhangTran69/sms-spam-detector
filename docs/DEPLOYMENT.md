# Deployment

How to run the detector locally and as a container, and what to configure when
exposing it. The API is a plain FastAPI/uvicorn service; the trained artifact is
mounted at runtime, never baked into the image.

## 1. Local setup

Python **>= 3.11** is required (the current dependency ranges resolve to
pandas 3.x / scikit-learn 1.9, which need 3.11+). The project is developed and
verified on **Python 3.13**. CI runs on 3.11 and 3.12.

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

# Runtime dependencies (API, training, and evaluation) in the checkout
pip install -e .

# Test and quality tools for development/CI
pip install -e ".[dev]"

# Existing requirements-file installs remain supported
pip install -r requirements.txt -r requirements-dev.txt

# Optional: replicate the exact tester environment (Python 3.13 pins)
pip install -r requirements.txt -c constraints.txt
```

`constraints.txt` is the tester's `pip freeze` (Python 3.13.3, macOS arm64). It
is a reproduction aid, not a compatibility promise for other platforms; the
bounded ranges in `pyproject.toml` are the package contract. Requirements files
mirror runtime and development dependencies for Docker and existing workflows.
The wheel includes the web UI assets inside the `api` package, so an installed
wheel can serve the complete UI outside the source checkout. Root datasets and
model artifacts are intentionally not packaged; supply a trusted model through
`SMSD_MODEL_PATH` or the documented working-directory model location.

For a reproducible no-corpus demo, `make demo` uses only tracked synthetic CSV
fixtures, writes an ignored candidate at `models/demo_synthetic.pkl`, runs the
internal split and synthetic holdout evaluation, and smoke-tests the API
against that candidate. It does not start a server or replace the configured
serving artifact. Do not interpret its scores as deployment performance
evidence. Override `DEMO_MODEL` and `DEMO_EVALUATION` to direct outputs outside
the checkout during isolated packaging checks.

## 2. Train (artifact required before serving)

```bash
python -m src.train                 # writes models/spam_detector_v1.pkl (+ sidecar .metadata.json)
python -m src.evaluate              # held-out metrics, threshold sweep, synthetic PH holdout
```

- `data/raw/spam.csv` (base corpus) is operator-supplied, required for the
  default full training run, and **not committed**. Its provenance and license
  are unknown until the operator verifies them; do not assume it is UCI data.
  See [data/raw/README.md](../data/raw/README.md) for the verified UCI import
  process. Training can use an imported corpus explicitly with
  `python -m src.train --data data/raw/imported/uci_sms_spam.csv`.
- The synthetic Philippine CSVs are committed and merged automatically.
- The artifact is a joblib-serialized **bundle** (model pipeline + decision
  threshold + label mapping + training config + data-source hashes + version
  metadata + metrics), with a human-readable
  `models/spam_detector_v1.metadata.json` sidecar. `models/` is git-ignored —
  artifacts travel through a registry/volume, not Git.
- `joblib.load()` can execute code from a malicious pickle. Load artifacts only
  from a trusted build/release process; do not accept model uploads. Optionally
  pin the expected model SHA-256 with `SMSD_MODEL_SHA256` (for example,
  `shasum -a 256 models/spam_detector_v1.pkl`). The expected digest must come
  from a trusted channel; this check is not a signature or provenance system.
  When configured, the loader hashes and deserializes the same in-memory bytes,
  avoiding a verify-then-reopen race. It still does not authenticate or make a
  malicious pickle safe.
- Feature version 2.2.0 adds optional char/combined TF-IDF modes without
  changing 2.1.0 word-only preprocessing. The loader accepts that prior mode
  only after checking fitted vectorizer settings and input columns; a version
  label alone does not establish compatibility. Incompatible feature modes or
  schemas still fail readiness.
- Each analysis result carries its own model version, decision threshold, and
  suspicious-band threshold. The UI, copied summary, and batch CSV use these
  per-result values, so delayed `/model-info` metadata cannot relabel an existing
  result.
- The API resolves `SMSD_MODEL_PATH` at startup; when it is unset, code defaults
  to `models/spam_detector_v1.pkl`. Check the running instance with
  `GET /model-info` because a local file or candidate training run does not
  prove what a separately hosted demo serves. On 2026-10-21, the local API at
  `127.0.0.1:8000` reported `spam_detector_v1` (schema 1, feature version
  unknown, threshold 0.50, uncalibrated, with no training-data provenance in
  the response). Its warning identifies it as a legacy artifact; readiness and
  inference still work. The API reports the artifact version but does not
  expose its resolved filesystem path, so this observation identifies the
  model reported by that local process, not the bytes used by a separate hosted
  demo. The
  locally present `spam_detector_v2_1.pkl` is a separate ignored artifact and
  is not the configured fallback.
- For the authoritative current CLI flags run `python -m src.train --help` and
  `python -m src.evaluate --help`.

## 3. Serve locally

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000
# UI:      http://127.0.0.1:8000/
# Docs:    http://127.0.0.1:8000/docs
# Health:  http://127.0.0.1:8000/health
# Ready:   http://127.0.0.1:8000/ready
```

`make serve` uses the project CLI preflight and wraps this with `--reload` for
development. It reports missing Python packages before startup and warns when the
configured model artifact is absent. In that case the UI and liveness endpoint
still start, but readiness and analysis return 503 until a model is available.
Run it in a terminal that stays open; closing that terminal or pressing Ctrl-C
stops the foreground server. Use `--workers N` for more concurrency once memory
permits (the model is loaded lazily per process;
each worker holds its own copy). Do not use `--reload` in production.

### Keep a local macOS server running after closing the terminal

On macOS, install a LaunchAgent for the logged-in user. Create
`~/Library/LaunchAgents/com.ph.smsd.plist`; replace `/Users/YOU/...` with the
checkout and model paths and use the Python executable from its virtual
environment:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ph.smsd</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/.../sms-spam-detector/.venv/bin/python</string>
    <string>-m</string><string>api.cli</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8000</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/YOU/.../sms-spam-detector</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SMSD_MODEL_PATH</key><string>/Users/YOU/.../sms-spam-detector/models/spam_detector_v1.pkl</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>/Users/YOU/Library/Logs/ph-smsd.out.log</string>
  <key>StandardErrorPath</key><string>/Users/YOU/Library/Logs/ph-smsd.err.log</string>
</dict>
</plist>
```

Load and inspect the agent with:

```bash
mkdir -p "$HOME/Library/Logs"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.ph.smsd.plist"
launchctl print "gui/$(id -u)/com.ph.smsd"
curl -fsS http://127.0.0.1:8000/ready
```

`KeepAlive` restarts a process that exits unexpectedly; launchd throttles rapid
restart loops. The service starts at login and stays local to this Mac. Stop it
with `launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.ph.smsd.plist"`;
load it again with `bootstrap` after a planned stop. Logs contain service
diagnostics and request paths, never message bodies; keep them private and
rotate or remove them under your normal local log-retention practice. If port
8000 is already occupied, inspect its owner with `lsof -nP -iTCP:8000 -sTCP:LISTEN`
and change the LaunchAgent port or stop only the verified detector process.

### Keep a local Linux server running after closing the terminal

On a machine using systemd, a user service can supervise the local server and
restart it after an unexpected failure. Create
`~/.config/systemd/user/smsd.service`, replacing the paths with the checkout's
absolute path:

```ini
[Unit]
Description=Local Philippine SMS detector

[Service]
WorkingDirectory=/absolute/path/to/sms-spam-detector
Environment=SMSD_MODEL_PATH=/absolute/path/to/sms-spam-detector/models/spam_detector_v1.pkl
ExecStart=/absolute/path/to/sms-spam-detector/.venv/bin/smsd-serve --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
```

Then run `systemctl --user daemon-reload` and
`systemctl --user enable --now smsd.service`. Check it with
`systemctl --user status smsd.service`; read message-free service output with
`journalctl --user -u smsd.service`. It remains bound to localhost. To have the
user service start at machine boot without an active login session, enable user
lingering through the machine administrator. This example is for Linux/systemd;
other operating systems need their native service manager.

### Verify or restart the local process safely

Check the page shell and its entry assets as well as API health; a live process
can still be serving stale code or an incomplete package:

```bash
for path in / /static/app.js /static/styles.css /manifest.webmanifest /sw.js /health /ready /model-info; do
  printf '%s ' "$path"
  curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' "http://127.0.0.1:8000$path"
done
```

On macOS, identify the listener and inspect both its command and working
directory before stopping anything:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
# Replace 12345 below with the PID reported by lsof.
ps -p 12345 -o pid=,command=
lsof -a -p 12345 -d cwd
```

Only if that PID is the detector's Uvicorn process and its working directory is
this checkout, stop that specific process with `kill -TERM 12345`, replacing
`12345` with the verified PID. Then start the server in a terminal from the repository root with
`.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000` and
repeat the route checks. If the listener belongs to another project or the
identity is unclear, leave it running and use a free port such as 8001. Do not
use a broad `pkill uvicorn` command. The detector does not log SMS contents;
retain only message-free status codes and route names when diagnosing failures.

The home page, manifest, service worker, and allowlisted static bundle assets
return a sanitized `ui_unavailable` 503 if a bundled file is missing or
unreadable. Unknown static asset names return 404. Reinstall the package or run
from a complete checkout. A 200 from `/health` alone proves only that the
process is alive; verify the UI routes and `/ready` separately.

The wheel smoke check builds the package, installs it into a clean temporary
environment, changes outside the checkout, and verifies that Python imports
and UI assets come from the installed wheel. It checks missing-model readiness,
then injects a small in-memory synthetic classifier to exercise readiness and
analysis. Run it with `python scripts/wheel_smoke.py`; it never writes into the
serving model path. Static assets support GET and HEAD; successful responses
use `Cache-Control: no-cache`, and unknown names and traversal attempts return
404. CI also runs a Chromium behavior suite at a 360px viewport.

The **Compare messages** tab is part of the bundled static UI. It submits two
messages together through `POST /analyze/batch`; comparison inputs are not saved
in history. After updating static UI assets, update the asset query identifiers
in `api/web/index.html` and `api/web/sw.js` and increment the service-worker
cache name together. The install step waits for all shell downloads and removes
only a failed candidate cache, preserving the previous release.

The service worker installs a versioned shell into a new release cache and
waits for every asset write to finish before it activates. If any download
fails, it deletes only the incomplete candidate cache and leaves the previous
worker and shell available. Once active, it serves exact release URLs from its
own cache; it does not write network responses into that cache, avoiding
mixed-version HTML, CSS, and JavaScript. A missing cached shell file can be
fetched online but is not cached at runtime; if offline, the worker returns a
small no-store 503 response. Only a subsequent successful worker installation
replaces the shell. API routes and message-bearing requests are never cached.

Threshold evaluation diagnostics distinguish absent metadata, malformed or
contradictory policy metadata, changed validation candidates, artifact-threshold
mismatches, and a correctly retained default under `cv-robust`. A matching data
hash alone is not enough to call the recorded policy consistent.

To run the automated browser suite locally, use `npm ci`,
`npx playwright install chromium`, and `npm run test:browser`. It verifies
mocked UI states plus real localhost analysis through a temporary model trained
from tracked synthetic fixtures. The browser run checks missing-model readiness
separately from API reachability, service failure/recovery without resubmitting a
message, the real missing-model 503, an interrupted analysis response, mobile
reflow, and offline shell behavior. It blocks external requests during the real
API scenario. Automated accessibility checks do not replace manual
screen-reader testing.

Smoke test:

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready
curl -s -X POST http://127.0.0.1:8000/predict \
  -H 'Content-Type: application/json' \
  -d '{"message":"BDO: Your account is locked. Verify here: http://bit.ly/fakebdo"}'
```

## 4. Docker

The image is built from `python:3.12-slim` in two stages (dependency install,
then a minimal runtime). It installs `requirements.txt` only, copies `src/`,
and `api/` (including `api/web/`), runs as **non-root uid 10001**, exposes 8000, and defines a
stdlib-Python `HEALTHCHECK` against `/health` (curl is not in the slim image).
OCI labels are set in the Dockerfile.

**The model artifact is not in the image.** `models/*.pkl` is git-ignored and
excluded by `.dockerignore`; the image contains no data or artifacts. Mount a
read-only models directory and point `SMSD_MODEL_PATH` at the bundle.

```bash
docker build -t philippine-sms-spam-detector:local .

docker run --rm -p 127.0.0.1:8000:8000 \
  -v "$PWD/models:/app/models:ro" \
  -e SMSD_MODEL_PATH=/app/models/spam_detector_v1.pkl \
  -e SMSD_CORS_ORIGINS="http://127.0.0.1:8000,http://localhost:8000" \
  philippine-sms-spam-detector:local
```

### Docker Compose

```bash
python -m src.train            # create ./models/spam_detector_v1.pkl on the host first
docker compose build
docker compose up -d
docker compose ps              # health status
docker compose logs -f api
docker compose down            # add -v only if you know what you are deleting
```

`docker-compose.yml` binds the port to loopback, mounts `./models:/app/models:ro`,
sets model/CORS/feedback environment variables, uses `restart: unless-stopped`, runs the same
`/health` healthcheck, drops all Linux capabilities with
`no-new-privileges`, and caps resources (1 CPU / 512 MiB limit; 0.25 CPU /
256 MiB reservation). Adjust limits for your workload.

If `/ready` returns 503 while `/health` is 200, the artifact is missing or
incompatible — check the mount path and `SMSD_MODEL_PATH`.

## 5. Environment variables

These variables are read by the application. None is a secret.

| Variable | Default | Meaning |
|---|---|---|
| `SMSD_ENV` | `development` | Set to `production` to reject legacy bare-pipeline artifacts at readiness and inference and force anonymous feedback off. |
| `SMSD_ALLOW_LEGACY_MODEL` | `false` | Explicit development-only override for a legacy artifact while `SMSD_ENV=production`; avoid using it for deployed traffic. |
| `SMSD_MODEL_PATH` | `models/spam_detector_v1.pkl` (repo-relative, resolved from the project root; `/app/models/spam_detector_v1.pkl` in the container) | Path to the joblib model bundle to load. Must be readable by the runtime user; mount `models/` read-only. |
| `SMSD_MODEL_SHA256` | unset | Optional 64-character expected SHA-256 for the exact model file, checked before deserialization. Use a trusted digest; see the pickle warning above. |
| `SMSD_CORS_ORIGINS` | `http://127.0.0.1:8000,http://localhost:8000` | Comma-separated allowlist of browser origins. Wildcard `*` entries are ignored, and an empty/wildcard-only value falls back to the default local origins; credentials are disabled. Set your reverse-proxy origin (e.g. `https://sms.example.org`) if the UI is served from a different origin. |
| `SMSD_FEEDBACK_ENABLED` | `false` | Enables optional anonymous label correction in non-production environments. Production mode always disables it; stale model-version reports are rejected. |
| `SMSD_FEEDBACK_PATH` | `data/feedback/reports.jsonl` | Local JSONL queue containing selected labels, broad category, timestamp, and model version only; never SMS text. Compose stores it in the named `smsd_feedback` volume. |

- There is **no** `PORT`, log-level, or threshold environment variable. Pass
  host/port/log level to uvicorn on the command line
  (`uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level info`). Thresholds
  come from the artifact (`GET /model-info`).
- Request limits are constants: max message length 10,000 chars, batch 1–50
  messages and 200,000 chars total, request body ≤ 1 MB. The ASGI middleware
  reads streamed bodies before JSON parsing and enforces the cap without
  `Content-Length`; it keeps the capped chunks and briefly joins them before
  dispatch, so concurrent requests can use several megabytes each. These
  limits are not env-configurable. Set matching ingress limits and
  request/read timeouts, concurrency limits, and rate limiting at the reverse
  proxy or gateway before exposing the API publicly. The app does not currently
  implement rate limiting or an operational metrics endpoint.
- The request body cap and security headers share one ASGI middleware. Keep
  ingress request/read timeouts, concurrency limits, and rate limits configured
  at the reverse proxy or gateway; the app does not enforce those controls.
- **Never put secrets in these variables or in Git.** No API keys are needed.
  TLS private keys belong in the reverse proxy's secret store, outside the
  repository and image.

## 6. Health and readiness

| Endpoint | Semantics | Use |
|---|---|---|
| `GET /health` | Liveness only. Always 200 when the process is up; never loads the model. Body: `{"status":"ok","model_loaded":bool,"model_version":str|null}`. | Container/orchestrator liveness probe, dashboards. |
| `GET /ready` | Readiness gate. Loads/verifies the artifact; 200 when ready, 503 (`model_unavailable`) when missing/incompatible. | Deploy gate, load-balancer readiness, "is it safe to send traffic?" |
| `GET /model-info` | JSON-safe metadata: version, schema version, classes, thresholds, bands, training data info, synthetic-data note, metrics, warnings. | Debugging, audit, UI threshold display. |

Notes:

- The Docker `HEALTHCHECK` deliberately uses `/health`: it never loads the
  model, so a fresh process can be "healthy" (liveness) while `model_loaded` is
  still `false` until `/ready` or the first model-using request triggers the
  lazy load. Gate rollout on `/ready` (or `/model-info`), not on the Docker
  health status alone.
- Model loading is lazy (first request) but `/ready` forces/verifies it, so a
  deploy gate catches a bad artifact before users do. A missing artifact returns
  a stable `503` error envelope, not a crash.
- Do not use `/predict` as a healthcheck; it costs inference and requires a
  message.

## 7. Reverse proxy and TLS

Terminate TLS at a reverse proxy and keep the app on a private network. Example
nginx (adjust names and certificate paths, which live outside this repo):

```nginx
server {
    listen 443 ssl http2;
    server_name sms.example.org;

    ssl_certificate     /etc/letsencrypt/live/sms.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sms.example.org/privkey.pem;

    client_max_body_size 1m;          # match the API body cap
    add_header Strict-Transport-Security "max-age=31536000" always;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        # Do NOT log request bodies; the API receives message text in POST bodies.
    }
}

server {
    listen 80;
    server_name sms.example.org;
    return 301 https://$host$request_uri;
}
```

- Redirect HTTP → HTTPS; use HSTS once you are sure TLS persists.
- Keep `client_max_body_size` aligned with the 1 MB API cap and set sensible
  request timeouts/rate limits at the proxy (the app does not rate-limit).
- Disable proxy access-log body capture and any APM body sampling; see
  [PRIVACY.md](PRIVACY.md).
- Restrict egress from the container (it needs none at runtime).
- The UI is same-origin by default; only add extra origins to
  `SMSD_CORS_ORIGINS` when you actually split UI/API origins.

## 8. Operations

**Resource expectations.** Inference is cheap: a few hundred MB RSS for the
sklearn pipeline plus the Python runtime; 512 MiB is a comfortable limit for
SMS-length requests. CPU is bursty; 1 CPU handles local/UI traffic. Scale out
(replicas behind the proxy) rather than up. Keep model loading lazy so startup
is fast; use `/ready` after each start.

**Startup order.** Mount models → start container → wait for `/ready` → send
traffic. A missing model is a configuration error, not a reason to fall back to
a fake/stub prediction: the API returns 503 instead.

**No secrets in Git.** The repository contains no credentials; `.env` is
git-ignored. Do not add TLS keys, registry tokens, or API keys to the image,
compose file, or CI. CI uses the default `GITHUB_TOKEN` with `contents: read`
only and does not deploy.

**Rollback to a previous artifact.** Because the artifact is mounted, rollback
does not require rebuilding the image:

1. Keep previous bundles (and their `.metadata.json` sidecars) under versioned
   paths, e.g. `models/releases/spam_detector_v1.0.0.pkl` +
   `.metadata.json`, immutable and access-controlled.
2. Point `SMSD_MODEL_PATH` (or the compose volume/target path) back to the last
   known-good bundle, restart/recreate the container, and wait for `/ready`.
3. Record the version, time, reason, and operator in the audit log; verify
   `GET /model-info` reports the expected `model_version`.
4. To roll back the code as well, redeploy the previous image tag/digest and the
   matching artifact; never pair mismatched schema versions — `/ready` will
   fail if the artifact is incompatible.

**Browser history privacy.** The UI may store the last few checks in
`localStorage` only when the user opts in; nothing is stored server-side and the
history can be cleared from the UI. On shared devices, use a private window or
clear history. Optional feedback is disabled by default; when enabled, it writes
only selected labels and model metadata to the local queue. See
[PRIVACY.md](PRIVACY.md) for the full policy.

**First-response checklist when the service misbehaves:**

- `/health` 200 but `/ready` 503 → artifact path/permissions/incompatible
  schema; check logs (message-free), `SMSD_MODEL_PATH`, mount.
- 502/504 at the proxy → app not listening on the expected port/host or request
  timeout; check `docker compose ps` and uvicorn logs.
- 413 → body over 1 MB; batch over limits → 422 with field details.
- Unexpected verdicts → check `/model-info` version/threshold first, then review
  false positives per [RETRAINING.md](RETRAINING.md) monitoring guidance.

## Appendix: optional anonymous correction reports

The web form appears only when the operator opts in:

```bash
SMSD_FEEDBACK_ENABLED=true uvicorn api.main:app --host 127.0.0.1 --port 8000
```

A submitted report stores the chosen correction, broad category, timestamp, and model version in `data/feedback/reports.jsonl`. It never sends or stores the SMS text, sender details, or IP address. Reports are unverified review signals; they are never automatically added to training. The queue is local, ignored by Git, and capped at 10 MiB. For Docker Compose, set `SMSD_FEEDBACK_ENABLED=true`; reports persist in the named `smsd_feedback` Docker volume. Do not expose this anonymous endpoint publicly without authentication or deployment-level abuse controls and a retention policy.

Summarize an enabled local queue without exporting report IDs or timestamps:

```bash
python -m src.feedback --path data/feedback/reports.jsonl --output data/processed/feedback-summary.json
```
