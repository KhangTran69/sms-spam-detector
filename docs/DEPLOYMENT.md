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
The wheel currently contains Python packages, not the root data and web
assets; run from a checkout or use Docker for a complete service deployment.

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
- The API resolves `SMSD_MODEL_PATH` at startup; when it is unset, code defaults
  to `models/spam_detector_v1.pkl`. Check the running instance with
  `GET /model-info` because a local file or candidate training run does not
  prove what a separately hosted demo serves. On 2026-10-20, the local API at
  `127.0.0.1:8000` reported `spam_detector_v1` (schema 1, threshold 0.50,
  uncalibrated); its process ran from this repository. The API reports the
  artifact version but does not expose its resolved filesystem path. The
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

`make serve` wraps this with `--reload` for development. Use `--workers N` for
more concurrency once memory permits (the model is loaded lazily per process;
each worker holds its own copy). Do not use `--reload` in production.

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
