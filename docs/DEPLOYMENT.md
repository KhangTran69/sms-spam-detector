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

# Runtime + test dependencies (test tooling is kept in requirements.txt so a
# single install supports training, tests, and serving)
pip install -r requirements.txt

# Development/CI tools (ruff, mypy, pytest-cov)
pip install -r requirements-dev.txt

# Optional: replicate the exact tester environment (Python 3.13 pins)
pip install -r requirements.txt -c constraints.txt
```

`constraints.txt` is the tester's `pip freeze` (Python 3.13.3, macOS arm64). It
is a reproduction aid, not a compatibility promise for other platforms; the
bounded ranges in `requirements.txt` are the contract.

## 2. Train (artifact required before serving)

```bash
python -m src.train                 # writes models/spam_detector_v1.pkl (+ sidecar .metadata.json)
python -m src.evaluate              # held-out metrics, threshold sweep, synthetic PH holdout
```

- `data/raw/spam.csv` (base corpus) is required for a full training run and is
  **not committed** (public UCI-derived English dataset; download links are in
  the [README](../README.md)).
- The synthetic Philippine CSVs are committed and merged automatically.
- The artifact is a joblib-serialized **bundle** (model pipeline + decision
  threshold + label mapping + training config + data-source hashes + version
  metadata + metrics), with a human-readable
  `models/spam_detector_v1.metadata.json` sidecar. `models/` is git-ignored —
  artifacts travel through a registry/volume, not Git.
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
`api/`, and `web/`, runs as **non-root uid 10001**, exposes 8000, and defines a
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
| `SMSD_MODEL_PATH` | `models/spam_detector_v1.pkl` (repo-relative, resolved from the project root; `/app/models/spam_detector_v1.pkl` in the container) | Path to the joblib model bundle to load. Must be readable by the runtime user; mount `models/` read-only. |
| `SMSD_CORS_ORIGINS` | `http://127.0.0.1:8000,http://localhost:8000` | Comma-separated allowlist of browser origins. Wildcard `*` entries are ignored, and an empty/wildcard-only value falls back to the default local origins; credentials are disabled. Set your reverse-proxy origin (e.g. `https://sms.example.org`) if the UI is served from a different origin. |
| `SMSD_FEEDBACK_ENABLED` | `false` | Enables the optional anonymous label-correction endpoint and UI. Keep disabled unless the operator has reviewed retention and abuse controls. |
| `SMSD_FEEDBACK_PATH` | `data/feedback/reports.jsonl` | Local JSONL queue containing selected labels, broad category, timestamp, and model version only; never SMS text. Compose stores it in the named `smsd_feedback` volume. |

- There is **no** `PORT`, log-level, or threshold environment variable. Pass
  host/port/log level to uvicorn on the command line
  (`uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level info`). Thresholds
  come from the artifact (`GET /model-info`).
- Request limits are constants: max message length 10,000 chars, batch 1–50
  messages and 200,000 chars total, request body ≤ 1 MB. They are not
  env-configurable.
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
