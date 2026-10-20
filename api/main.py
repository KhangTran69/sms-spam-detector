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

import json
import logging
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.predict import (
    MAX_MESSAGE_LENGTH,
    ModelArtifactError,
    analyze_batch,
    analyze_message,
    load_model,
    model_info,
)

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"

MAX_BATCH = 50
MAX_BATCH_CHARACTERS = 200_000
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

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
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

logger = logging.getLogger("api.main")


class RequestBodyLimitMiddleware:
    """Bound body consumption even when Content-Length is absent or inaccurate."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {key.lower() for key, _ in headers}
                for name, value in SECURITY_HEADERS.items():
                    key = name.lower().encode("latin-1")
                    if key not in present:
                        headers.append((key, value.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        content_length = next(
            (value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == b"content-length"),
            None,
        )
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BYTES:
                    await _error_response(
                        413,
                        "payload_too_large",
                        f"Request body is too large; the limit is {MAX_REQUEST_BYTES} bytes.",
                    )(scope, receive, secure_send)
                    return
            except ValueError:
                pass

        # Read and cap the body before calling FastAPI. Otherwise its JSON
        # parser can turn a receive-side size exception into a generic 400.
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
                await _error_response(
                    413,
                    "payload_too_large",
                    f"Request body is too large; the limit is {MAX_REQUEST_BYTES} bytes.",
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

        await self.app(scope, replay_body, secure_send)


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


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------
class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str = "ok"
    model_loaded: bool
    model_version: str | None = None


class ReadinessResponse(BaseModel):
    status: str = "ready"
    model_loaded: bool
    model_version: str | None = None


def _reject_blank(value: str) -> str:
    # Kept unstripped: highlight offsets must align with the original message.
    if not value.strip():
        raise ValueError("message must not be blank")
    return value


MessageText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_MESSAGE_LENGTH),
    AfterValidator(_reject_blank),
]


class PredictRequest(BaseModel):
    message: MessageText = Field(..., description="SMS message to classify")


class BatchRequest(BaseModel):
    messages: list[MessageText] = Field(
        ...,
        min_length=1,
        max_length=MAX_BATCH,
        description=f"1 to {MAX_BATCH} SMS messages (one per item)",
    )

    @model_validator(mode="after")
    def _check_total_characters(self) -> BatchRequest:
        total = sum(len(message) for message in self.messages)
        if total > MAX_BATCH_CHARACTERS:
            raise ValueError(
                f"Batch is limited to {MAX_BATCH_CHARACTERS} total characters; received {total}. "
                "Split the messages into smaller requests."
            )
        return self


class PredictResponse(BaseModel):
    prediction: str
    probability: float
    probability_calibrated: bool
    flags: list[str]
    decision_threshold: float
    model_version: str


class Match(BaseModel):
    type: str
    text: str
    start: int
    end: int


class AnalyzeResponse(BaseModel):
    message: str
    prediction: str
    spam_probability: float
    probability_calibrated: bool
    probability: float
    decision_threshold: float
    margin: float
    confidence: str
    risk_band: str
    flags: list[str]
    matches: list[Match]
    brands: list[str]
    model_version: str


class BatchResponse(BaseModel):
    count: int
    results: list[AnalyzeResponse]
    model_version: str
    decision_threshold: float


class FeedbackRequest(BaseModel):
    """Minimal anonymous report; deliberately rejects message/text fields."""

    model_config = ConfigDict(extra="forbid")

    model_version: str = Field(..., min_length=1, max_length=120)
    predicted_label: Literal["ham", "spam"]
    expected_label: Literal["ham", "spam"]
    category: Literal["otp", "bank_alert", "delivery", "personal", "prize_scam", "phishing", "other"] = "other"

    @model_validator(mode="after")
    def _must_report_a_difference(self) -> FeedbackRequest:
        if self.predicted_label == self.expected_label:
            raise ValueError("Feedback is only accepted when the expected label differs from the prediction.")
        return self


class FeedbackResponse(BaseModel):
    status: Literal["received"]
    report_id: str
    message: str


_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "Request validation failed"},
    413: {"model": ErrorResponse, "description": "Request body too large"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
    503: {"model": ErrorResponse, "description": "Model unavailable or incompatible"},
}


# ---------------------------------------------------------------------------
# Middleware: bounded streaming request bodies + security headers
# ---------------------------------------------------------------------------
app.add_middleware(RequestBodyLimitMiddleware)


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
# Routes
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    """Always 200; reports whether the model happens to be loaded (never loads it)."""
    loaded = _model
    return HealthResponse(
        status="ok",
        model_loaded=loaded is not None,
        model_version=_model_version(loaded),
    )


@app.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ErrorResponse, "description": "Model unavailable or incompatible"}},
    summary="Readiness probe (loads and validates the model artifact)",
)
def ready() -> ReadinessResponse:
    model = get_model()
    return ReadinessResponse(status="ready", model_loaded=True, model_version=_model_version(model))


@app.get(
    "/model-info",
    response_model=dict[str, Any],
    responses={503: {"model": ErrorResponse, "description": "Model unavailable or incompatible"}},
    summary="Model metadata (thresholds, bands, provenance, warnings)",
)
def get_model_info() -> dict[str, Any]:
    info = _json_safe(model_info(model=get_model()))
    info["feedback_enabled"] = FEEDBACK_ENABLED
    return info


def _append_feedback_report(report: dict[str, Any]) -> str:
    """Persist only user-selected labels and model metadata, never message text."""
    report_id = uuid.uuid4().hex
    record = {
        "report_id": report_id,
        "created_at": datetime.now(UTC).isoformat(),
        **report,
    }
    encoded = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    with _feedback_lock:
        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        current_size = FEEDBACK_PATH.stat().st_size if FEEDBACK_PATH.exists() else 0
        if current_size + len(encoded) > MAX_FEEDBACK_BYTES:
            raise OSError("Feedback queue is full; the operator must archive it before accepting more reports.")
        with FEEDBACK_PATH.open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    return report_id


@app.post("/predict", response_model=PredictResponse, responses=_ERROR_RESPONSES, summary="Minimal verdict")
def predict(request: PredictRequest) -> PredictResponse:
    analysis = analyze_message(request.message, model=get_model())
    return PredictResponse(
        prediction=analysis["prediction"],
        probability=analysis["probability"],
        probability_calibrated=analysis["probability_calibrated"],
        flags=analysis["flags"],
        decision_threshold=analysis["decision_threshold"],
        model_version=analysis["model_version"],
    )


@app.post("/analyze", response_model=AnalyzeResponse, responses=_ERROR_RESPONSES, summary="Full analysis")
def analyze(request: PredictRequest) -> AnalyzeResponse:
    return AnalyzeResponse.model_validate(analyze_message(request.message, model=get_model()))


@app.post("/analyze/batch", response_model=BatchResponse, responses=_ERROR_RESPONSES, summary="Batch analysis")
def analyze_batch_endpoint(request: BatchRequest) -> BatchResponse:
    results = analyze_batch(request.messages, model=get_model())
    first = results[0] if results else {}
    return BatchResponse(
        count=len(results),
        results=[AnalyzeResponse.model_validate(item) for item in results],
        model_version=first.get("model_version", "unknown"),
        decision_threshold=float(first.get("decision_threshold", 0.5)),
    )


@app.post(
    "/feedback",
    response_model=FeedbackResponse,
    responses=_ERROR_RESPONSES,
    summary="Submit anonymous label feedback (message text is not accepted)",
)
def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    if SMSD_ENV == "production" or not FEEDBACK_ENABLED:
        raise StarletteHTTPException(status_code=404, detail="Anonymous feedback is disabled by the operator.")
    model = get_model()
    current_version = _model_version(model)
    if request.model_version != current_version:
        raise StarletteHTTPException(
            status_code=409,
            detail="Feedback model_version must match the currently served model.",
        )
    report = {
        "model_version": request.model_version,
        "server_model_version": current_version,
        "predicted_label": request.predicted_label,
        "expected_label": request.expected_label,
        "category": request.category,
    }
    try:
        report_id = _append_feedback_report(report)
    except OSError as exc:
        logger.error("Could not save anonymous feedback (%s)", type(exc).__name__)
        raise StarletteHTTPException(status_code=503, detail="Feedback is temporarily unavailable.") from exc
    return FeedbackResponse(
        status="received",
        report_id=report_id,
        message="Thanks. The report contains labels and model metadata only; no SMS text was sent.",
    )


if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        """Serve the bundled single-page UI."""
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def webmanifest():
        """PWA manifest (installable app shell)."""
        return FileResponse(
            WEB_DIR / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        """Service worker for the offline static shell (never caches message data)."""
        return FileResponse(
            WEB_DIR / "sw.js",
            media_type="text/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        )
