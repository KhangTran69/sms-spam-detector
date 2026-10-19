#
# Philippine SMS spam/scam detector service image.
#
# The trained artifact is deliberately NOT baked into the image: models/*.pkl is
# git-ignored and model binaries are deployment data. Mount a models directory
# at /app/models:ro and point SMSD_MODEL_PATH at the bundle inside it.
#
#   docker build -t philippine-sms-spam-detector:local .
#   docker run --rm -p 8000:8000 \
#     -v "$PWD/models:/app/models:ro" \
#     -e SMSD_MODEL_PATH=/app/models/spam_detector_v1.pkl \
#     philippine-sms-spam-detector:local

ARG PYTHON_VERSION=3.12

# ---------- builder: resolve and install wheels once ----------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---------- runtime: minimal image, non-root ----------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="Philippine SMS Spam/Scam Detector" \
      org.opencontainers.image.description="FastAPI service for assistive SMS spam/scam classification (TF-IDF + LogisticRegression)" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.ref.name="main" \
      org.opencontainers.image.source="https://github.com/KhangTran69/sms-spam-detector" \
      org.opencontainers.image.documentation="https://github.com/KhangTran69/sms-spam-detector/blob/main/docs/DEPLOYMENT.md"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:${PATH}"

# Dedicated unprivileged user (no shell, no home writes needed at runtime).
RUN groupadd --gid 10001 smsd \
    && useradd --uid 10001 --gid smsd --no-create-home --shell /usr/sbin/nologin smsd

WORKDIR /app

# Runtime dependencies only (see requirements.txt); copied as a venv so the
# final image does not carry pip/build caches.
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 src/ ./src/
COPY --chown=10001:10001 api/ ./api/
COPY --chown=10001:10001 web/ ./web/

# Mount point for the read-only model artifact (kept out of the image).
RUN mkdir -p /app/models /app/data/feedback \
    && chown -R 10001:10001 /app/models /app/data

USER 10001:10001
EXPOSE 8000

# Liveness probe: /health never loads the model, so it stays 200 even before the
# artifact is mounted (readiness is reported by /ready). Python stdlib only --
# curl is not present in python:*-slim.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; r = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); sys.exit(0 if r.status == 200 else 1)"]

# Host/port flags are uvicorn CLI options; the app reads no PORT env var.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
