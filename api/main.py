"""FastAPI application for SMS spam prediction and the bundled web UI.

Design notes
------------
* Model loading is lazy and locked: the artifact is loaded on the first request
  that needs it, reused afterwards, and a missing/corrupt artifact never stops
  the process from starting (the API returns 503 with an actionable message).
* Every error response uses one stable schema:
  ``{"error": {"code": str, "message": str, "details": list | None}}``.
  Validation details are sanitized so user message text is never echoed back.
* CORS is same-origin by default. Configure extra trusted browser origins with
  the ``SMSD_CORS_ORIGINS`` environment variable (comma-separated). Wildcards
  are rejected; ``allow_credentials`` stays disabled.
* Messages are analyzed in memory only: nothing is logged, stored, or returned
  beyond the response body.
* The model artifact path can be overridden with ``SMSD_MODEL_PATH`` (handled by
  ``src.predict.default_model_path``) for containers/deployments.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.predict import (
    ModelArtifactError,
    load_model,
)

ROOT = Path(__file__).resolve().parents[1]
# Bundled with the package (see [tool.setuptools.package-data]) so `pip install .` serves the UI.
WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_REQUEST_BYTES = 1_000_000  # 1 MB cap on the raw JSON body
FEEDBACK_ENABLED = os.environ.get("SMSD_FEEDBACK_ENABLED", "").strip().lower() in {"1", "true", "yes"}
SMSD_ENV = os.environ.get("SMSD_ENV", "development").strip().lower()
ALLOW_LEGACY_MODEL = os.environ.get("SMSD_ALLOW_LEGACY_MODEL", "").strip().lower() in {"1", "true", "yes"}
if SMSD_ENV == "production":
    # Anonymous correction intake has no authentication or abuse controls.
    FEEDBACK_ENABLED = False
_feedback_path = os.environ.get("SMSD_FEEDBACK_PATH", "").strip()
FEEDBACK_PATH = Path(_feedback_path) if _feedback_path else ROOT / "data" / "feedback" / "reports.jsonl"
MAX_FEEDBACK_BYTES = 10 * 1024 * 1024
_feedback_lock = threading.Lock()
DEFAULT_CORS_ORIGINS = ("http://127.0.0.1:8000", "http://localhost:8000")
PREDICTION_RATE_LIMIT = max(1, int(os.environ.get("SMSD_RATE_LIMIT_PER_MINUTE", "60")))
_rate_lock = threading.Lock()
_rate_windows: dict[str, tuple[int, int]] = {}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'"
    ),
}

_HTTP_ERROR_CODES = {
    400: "bad_request",
    409: "conflict",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "model_unavailable",
}

RATE_LIMIT_ENDPOINTS = {"/predict", "/analyze", "/analyze/batch", "/feedback"}
RATE_LIMIT = int(os.environ.get("SMSD_RATE_LIMIT", "0"))
RATE_LIMIT_WINDOW = int(os.environ.get("SMSD_RATE_LIMIT_WINDOW", "60"))
_rate_limit_lock = threading.Lock()
_rate_limit_records: dict[str, list[float]] = defaultdict(list)


def _client_ip(scope: dict[str, Any]) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == b"x-forwarded-for":
            first_ip = value.decode("latin-1").split(",")[0].strip()
            if first_ip:
                return first_ip
    client = scope.get("client")
    if client and len(client) > 0 and client[0]:
        return str(client[0])
    return "127.0.0.1"


def _check_rate_limit(ip: str, now: float | None = None) -> tuple[bool, int]:
    limit = RATE_LIMIT
    if limit <= 0:
        return True, 0
    current_time = time.time() if now is None else now
    window = RATE_LIMIT_WINDOW
    cutoff = current_time - window
    with _rate_limit_lock:
        timestamps = [t for t in _rate_limit_records.get(ip, []) if t > cutoff]
        if len(timestamps) >= limit:
            oldest = timestamps[0]
            retry_after = max(1, int(oldest + window - current_time))
            _rate_limit_records[ip] = timestamps
            return False, retry_after
        timestamps.append(current_time)
        _rate_limit_records[ip] = timestamps
        return True, 0


def _reset_rate_limits() -> None:
    with _rate_limit_lock:
        _rate_limit_records.clear()
    with _rate_lock:
        _rate_windows.clear()


logger = logging.getLogger("api.main")


class RequestBodyLimitMiddleware:
    """Bound body consumption, enforce rate limits, security headers, request ID, and structured logging."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        raw_headers = scope.get("headers", [])
        incoming_req_id = next(
            (v.decode("latin-1").strip() for k, v in raw_headers if k.lower() == b"x-request-id" and v.strip()),
            None,
        )
        request_id = incoming_req_id or uuid.uuid4().hex
        status_code = 500

        async def secure_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                headers = list(message.get("headers", []))
                present = {key.lower() for key, _ in headers}
                for name, value in SECURITY_HEADERS.items():
                    key = name.lower().encode("latin-1")
                    if key not in present:
                        headers.append((key, value.encode("latin-1")))
                if b"x-request-id" not in present:
                    headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        client_ip = _client_ip(scope)
        path = scope.get("path", "")
        method = scope.get("method", "")

        # 1. Rate limiting check
        if path in RATE_LIMIT_ENDPOINTS:
            allowed, retry_after = _check_rate_limit(client_ip)
            if not allowed:
                elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
                logger.info(
                    '{"event": "request_completed", "request_id": "%s", "method": "%s", "path": "%s", "status": 429, "latency_ms": %.2f, "client_ip": "%s"}',
                    request_id,
                    method,
                    path,
                    elapsed_ms,
                    client_ip,
                )
                await _error_response(
                    429,
                    "rate_limited",
                    "Rate limit exceeded. Please try again later.",
                    headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
                )(scope, receive, secure_send)
                return

        # 2. Content-Length pre-check
        content_length = next(
            (value.decode("latin-1") for key, value in raw_headers if key.lower() == b"content-length"),
            None,
        )
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BYTES:
                    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
                    logger.info(
                        '{"event": "request_completed", "request_id": "%s", "method": "%s", "path": "%s", "status": 413, "latency_ms": %.2f, "client_ip": "%s"}',
                        request_id,
                        method,
                        path,
                        elapsed_ms,
                        client_ip,
                    )
                    await _error_response(
                        413,
                        "payload_too_large",
                        f"Request body is too large; the limit is {MAX_REQUEST_BYTES} bytes.",
                        headers={"X-Request-ID": request_id},
                    )(scope, receive, secure_send)
                    return
            except ValueError:
                pass

        # 3. Read and cap the body before calling FastAPI
        chunks: list[bytes] = []
        consumed = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            consumed += len(chunk)
            if consumed > MAX_REQUEST_BYTES:
                elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
                logger.info(
                    '{"event": "request_completed", "request_id": "%s", "method": "%s", "path": "%s", "status": 413, "latency_ms": %.2f, "client_ip": "%s"}',
                    request_id,
                    method,
                    path,
                    elapsed_ms,
                    client_ip,
                )
                await _error_response(
                    413,
                    "payload_too_large",
                    f"Request body is too large; the limit is {MAX_REQUEST_BYTES} bytes.",
                    headers={"X-Request-ID": request_id},
                )(scope, receive, secure_send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        delivered = False

        async def replay_body():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        try:
            await self.app(scope, replay_body, secure_send)
        finally:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info(
                '{"event": "request_completed", "request_id": "%s", "method": "%s", "path": "%s", "status": %d, "latency_ms": %.2f, "client_ip": "%s"}',
                request_id,
                method,
                path,
                status_code,
                elapsed_ms,
                client_ip,
            )


class PredictionRateLimitMiddleware:
    """Bound anonymous prediction traffic per connecting IP (single process)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") in {"/predict", "/analyze", "/analyze/batch"}
        ):
            client = scope.get("client")
            key = client[0] if client else "unknown"
            now = int(time.time())
            retry_after = None
            with _rate_lock:
                start, count = _rate_windows.get(key, (now, 0))
                if now - start >= 60:
                    start, count = now, 0
                if count >= PREDICTION_RATE_LIMIT:
                    retry_after = max(1, 60 - (now - start))
                else:
                    _rate_windows[key] = (start, count + 1)
                if len(_rate_windows) > 10_000:
                    expired = [ip for ip, state in _rate_windows.items() if now - state[0] >= 60]
                    for ip in expired:
                        _rate_windows.pop(ip, None)
            if retry_after is not None:
                response = _error_response(
                    429,
                    "rate_limited",
                    "Too many prediction requests; retry later.",
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def cors_origins(raw: str | None = None) -> list[str]:
    """Return the allowed browser origins for CORS.

    Defaults to local same-origin development URLs. Set ``SMSD_CORS_ORIGINS``
    to a comma-separated list to add trusted origins. ``*`` is deliberately
    ignored so the API can never be opened to every origin by accident.
    """
    if raw is None:
        raw = os.environ.get("SMSD_CORS_ORIGINS", "")
    origins: list[str] = []
    for item in raw.split(","):
        origin = item.strip().rstrip("/")
        if not origin or origin == "*":
            continue
        if origin not in origins:
            origins.append(origin)
    return origins or list(DEFAULT_CORS_ORIGINS)


CORS_ORIGINS = cors_origins()

app = FastAPI(
    title="Philippine SMS Scam Detector",
    version="2.0.0",
    description=(
        "Classify Philippine SMS messages as spam/scam or ham. "
        "Messages are processed in memory and never stored or logged. "
        "Scores come from a model trained on a public English corpus plus synthetic "
        "Philippine templates and are not proof of real-world accuracy. Optional anonymous "
        "feedback stores selected labels and model metadata only, never SMS text."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# ---------------------------------------------------------------------------
# Model lifecycle
# ---------------------------------------------------------------------------
_model = None
_model_lock = threading.Lock()


def get_model():
    """Load the model artifact once (lazy, thread-safe) and reuse it.

    Raises ``FileNotFoundError`` / ``ModelArtifactError``; the exception handlers
    below translate those into a 503. Tests may monkeypatch this function or
    ``_model`` to inject an in-memory bundle.
    """
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = load_model()
    if SMSD_ENV == "production" and getattr(_model, "legacy", False) and not ALLOW_LEGACY_MODEL:
        raise ModelArtifactError(
            "Production requires a versioned model bundle with recorded training metadata. "
            "Train and evaluate a candidate bundle before deployment."
        )
    return _model


def _model_version(model: Any) -> str | None:
    """Best-effort version string for a loaded bundle/pipeline (None if unknown)."""
    if model is None:
        return None
    version = getattr(model, "version", None)
    if isinstance(version, str) and version:
        return version
    metadata = getattr(model, "metadata", None)
    if isinstance(metadata, dict):
        value = metadata.get("model_version")
        if isinstance(value, str) and value:
            return value
    return None


def _json_safe(value: Any) -> Any:
    """Recursively convert metadata to plain JSON types (numpy/paths/objects)."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (str, int, float)):
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:  # pragma: no cover - defensive only
            pass
    return str(value)


# ---------------------------------------------------------------------------
# Stable error schema
# ---------------------------------------------------------------------------
def _error_payload(code: str, message: str, details: list[Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    merged_headers = dict(SECURITY_HEADERS)
    if headers:
        merged_headers.update(headers)
    return JSONResponse(
        status_code=status_code,
        content=_error_payload(code, message, details),
        headers=merged_headers,
    )


def _with_train_hint(message: str) -> str:
    if "src.train" in message:
        return message
    return f"{message} Train the model with: python -m src.train"


def sanitize_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Keep only location/type/message; never the submitted input or context.

    Pydantic includes the raw ``input`` value in its errors, which would echo
    SMS contents back to the client. This strips it.
    """
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        details.append(
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "msg": str(error.get("msg", "Invalid value")),
                "type": str(error.get("type", "value_error")),
            }
        )
    return details


from api.schemas import (  # noqa: E402,F401  (re-exported for compatibility)
    _ERROR_RESPONSES,
    MAX_BATCH,
    MAX_BATCH_CHARACTERS,
    AnalyzeResponse,
    BatchRequest,
    BatchResponse,
    ErrorBody,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    Match,
    MessageText,
    PredictRequest,
    PredictResponse,
    ReadinessResponse,
    _reject_blank,
)

# ---------------------------------------------------------------------------
# Middleware: bounded streaming request bodies + security headers
# ---------------------------------------------------------------------------
app.add_middleware(RequestBodyLimitMiddleware)
app.add_middleware(PredictionRateLimitMiddleware)


# ---------------------------------------------------------------------------
# Exception handlers (stable error schema)
# ---------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        422,
        "validation_error",
        "Request validation failed. Check the request fields and try again.",
        sanitize_validation_errors(exc),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else "Request failed."
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    return _error_response(exc.status_code, code, message, headers=exc.headers)


@app.exception_handler(ModelArtifactError)
@app.exception_handler(FileNotFoundError)
async def model_unavailable_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    message = _with_train_hint(str(exc).strip() or "The model artifact is unavailable.")
    return _error_response(503, "model_unavailable", message)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # No traceback or message content in the response; log only the type/path.
    logger.error(
        "Unhandled API error on %s %s (%s)",
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return _error_response(
        500,
        "internal_error",
        "Internal server error. The request could not be completed.",
    )


# ---------------------------------------------------------------------------
# Routes (handlers live in api.routes; state above stays patchable here)
# ---------------------------------------------------------------------------
from api import routes as _routes  # noqa: E402

app.include_router(_routes.router)
health = _routes.health
ready = _routes.ready
get_model_info = _routes.get_model_info
predict = _routes.predict
analyze = _routes.analyze
analyze_batch_endpoint = _routes.analyze_batch_endpoint
submit_feedback = _routes.submit_feedback
_append_feedback_report = _routes._append_feedback_report


_STATIC_ASSETS = {
    "app.js",
    "api-client.js",
    "i18n.js",
    "privacy-preview.js",
    "history-store.js",
    "connection-status.js",
    "result-format.js",
    "styles.css",
    "icon.svg",
}


@app.api_route("/static/{asset_name}", methods=["GET", "HEAD"], include_in_schema=False)
def static_asset(asset_name: str, request: Request):
    """Serve the small, known UI bundle with consistent safe failure behavior."""
    if asset_name not in _STATIC_ASSETS:
        return _error_response(404, "not_found", "The requested resource was not found.")
    try:
        body = (WEB_DIR / asset_name).read_bytes()
    except OSError:
        logger.error("Bundled UI asset unavailable (%s)", asset_name)
        return _error_response(
            503,
            "ui_unavailable",
            "The bundled web interface is unavailable. Reinstall the project or run it from a complete checkout.",
        )
    media_type = {
        "app.js": "text/javascript",
        "api-client.js": "text/javascript",
        "i18n.js": "text/javascript",
        "privacy-preview.js": "text/javascript",
        "history-store.js": "text/javascript",
        "connection-status.js": "text/javascript",
        "result-format.js": "text/javascript",
        "styles.css": "text/css",
        "icon.svg": "image/svg+xml",
    }[asset_name]
    headers = {"Cache-Control": "no-cache", "Content-Length": str(len(body))}
    return Response(b"" if request.method == "HEAD" else body, media_type=media_type, headers=headers)


def _ui_asset_response(
    filename: str,
    *,
    media_type: str,
    headers: dict[str, str] | None = None,
) -> Response:
    """Read a small bundled UI entry asset and fail with a safe setup hint.

    Reading before constructing the response catches missing/unreadable package
    assets synchronously, instead of letting a streaming ``FileResponse`` fail
    after headers have started and become an opaque internal server error.
    """
    path = WEB_DIR / filename
    try:
        body = path.read_bytes()
    except OSError:
        logger.error("Bundled UI asset unavailable (%s)", filename)
        return _error_response(
            503,
            "ui_unavailable",
            "The bundled web interface is unavailable. Reinstall the project or run it from a complete checkout.",
        )
    response_headers = {"Cache-Control": "no-cache"}
    if headers:
        response_headers.update(headers)
    return Response(content=body, media_type=media_type, headers=response_headers)


@app.get("/", include_in_schema=False)
def index():
    """Serve the bundled single-page UI."""
    return _ui_asset_response("index.html", media_type="text/html")


@app.get("/manifest.webmanifest", include_in_schema=False)
def webmanifest():
    """PWA manifest (installable app shell)."""
    return _ui_asset_response("manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """Service worker for the offline static shell (never caches message data)."""
    return _ui_asset_response(
        "sw.js",
        media_type="text/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )
