"""HTTP route handlers.

Mutable configuration and the model cache stay in :mod:`api.main` (tests and
deployments patch them there), so handlers read them through ``_state()`` at
request time instead of copying them at import.
"""

from __future__ import annotations

import hmac
import html
import ipaddress
import json
import os
import re
import sys
import uuid
from datetime import UTC, datetime
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.blocking import run_blocking
from api.donations import RETENTION_DAYS, DonationConflict, create_donation, delete_donation
from api.ops_metrics import operations_monitor
from api.rate_limiter import RateLimiterUnavailable, RedisRateLimiter, UnavailableRateLimiter
from api.schemas import (
    _ERROR_RESPONSES,
    AnalyzeResponse,
    BatchRequest,
    BatchResponse,
    DonationRequest,
    DonationResponse,
    DonationWithdrawalRequest,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    PredictRequest,
    PredictResponse,
    ReadinessResponse,
)
from src.monitor import default_monitor
from src.predict import analyze_batch, analyze_message, model_info
from src.privacy.scrub import detect_pii

router = APIRouter()


def _state() -> ModuleType:
    return sys.modules["api.main"]


def _record_linear_monitor(analysis: dict[str, Any]) -> None:
    """Keep the calibrated linear score baseline separate from raw transformer scores."""
    if analysis.get("model_path", "linear") == "linear":
        default_monitor.record(analysis["spam_probability"], analysis["prediction"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    """Always 200; reports whether the model happens to be loaded (never loads it)."""
    loaded = _state()._model
    return HealthResponse(
        status="ok",
        model_loaded=loaded is not None,
        model_version=_state()._model_version(loaded),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ErrorResponse, "description": "Model unavailable or incompatible"}},
    summary="Readiness probe (loads and validates the model artifact)",
)
def ready() -> ReadinessResponse:
    limiter = _state().RATE_LIMITER
    if isinstance(limiter, UnavailableRateLimiter):
        raise RateLimiterUnavailable("Rate limiting backend unavailable")
    if isinstance(limiter, RedisRateLimiter):
        limiter.ensure_available()
    model = _state().get_model()
    return ReadinessResponse(status="ready", model_loaded=True, model_version=_state()._model_version(model))


@router.get(
    "/model-info",
    response_model=dict[str, Any],
    responses={503: {"model": ErrorResponse, "description": "Model unavailable or incompatible"}},
    summary="Model metadata (thresholds, bands, provenance, warnings)",
)
def get_model_info() -> dict[str, Any]:
    info = _state()._json_safe(model_info(model=_state().get_model()))
    ensemble_configured = _state().TRANSFORMER_MODEL_PATH is not None
    info["feedback_enabled"] = _state().FEEDBACK_ENABLED and not ensemble_configured
    info["feedback_disabled_for_ensemble"] = _state().FEEDBACK_ENABLED and ensemble_configured
    info["ensemble_configured"] = ensemble_configured
    info["ensemble_checkpoint_directory_available"] = bool(
        _state().TRANSFORMER_MODEL_PATH is not None and _state().TRANSFORMER_MODEL_PATH.is_dir()
    )
    info["ensemble_confidence_band"] = (
        _state().TRANSFORMER_CONFIDENCE_BAND if _state().TRANSFORMER_MODEL_PATH is not None else None
    )
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
    with _state()._feedback_lock:
        _state().FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        current_size = _state().FEEDBACK_PATH.stat().st_size if _state().FEEDBACK_PATH.exists() else 0
        if current_size + len(encoded) > _state().MAX_FEEDBACK_BYTES:
            raise OSError("Feedback queue is full; the operator must archive it before accepting more reports.")
        with _state().FEEDBACK_PATH.open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    return report_id


def _authorize_metrics(request: Request) -> None:
    """Production metrics require an operator token; no public fallback."""
    state = _state()
    if state.SMSD_ENV != "production":
        return
    token = state.METRICS_TOKEN
    supplied = request.headers.getlist("x-smsd-metrics-token")
    provided = supplied[0] if len(supplied) == 1 else ""
    if not token or not token.isascii() or not provided.isascii() or not hmac.compare_digest(provided, token):
        raise HTTPException(status_code=404, detail="Not found", headers={"Cache-Control": "no-store"})


@router.get(
    "/metrics/distribution",
    response_model=dict[str, Any],
    summary="Prediction score distribution and covariate drift metrics",
)
def get_distribution_metrics(request: Request, response: Response) -> dict[str, Any]:
    _authorize_metrics(request)
    response.headers["Cache-Control"] = "no-store"
    return default_monitor.get_metrics()


@router.get(
    "/metrics/operations",
    response_model=dict[str, Any],
    summary="Process-local aggregated operations telemetry without message content",
)
def get_operations_metrics(request: Request, response: Response) -> dict[str, Any]:
    _authorize_metrics(request)
    response.headers["Cache-Control"] = "no-store"
    return operations_monitor.snapshot()


@router.post("/predict", response_model=PredictResponse, responses=_ERROR_RESPONSES, summary="Minimal verdict")
async def predict(request: PredictRequest) -> PredictResponse:
    analysis = await run_blocking(
        analyze_message,
        request.message,
        model=await run_blocking(_state().get_model),
        transformer_model_path=_state().TRANSFORMER_MODEL_PATH,
        confidence_band=_state().TRANSFORMER_CONFIDENCE_BAND,
    )
    _record_linear_monitor(analysis)
    return PredictResponse(
        prediction=analysis["prediction"],
        probability=analysis["probability"],
        probability_calibrated=analysis["probability_calibrated"],
        flags=analysis["flags"],
        decision_threshold=analysis["decision_threshold"],
        model_version=analysis["model_version"],
        model_path=analysis["model_path"],
    )


@router.post("/analyze", response_model=AnalyzeResponse, responses=_ERROR_RESPONSES, summary="Full analysis")
async def analyze(request: PredictRequest) -> AnalyzeResponse:
    analysis = await run_blocking(
        analyze_message,
        request.message,
        model=await run_blocking(_state().get_model),
        transformer_model_path=_state().TRANSFORMER_MODEL_PATH,
        confidence_band=_state().TRANSFORMER_CONFIDENCE_BAND,
    )
    _record_linear_monitor(analysis)
    return AnalyzeResponse.model_validate(analysis)


@router.post("/analyze/batch", response_model=BatchResponse, responses=_ERROR_RESPONSES, summary="Batch analysis")
async def analyze_batch_endpoint(request: BatchRequest) -> BatchResponse:
    results = await run_blocking(
        analyze_batch,
        request.messages,
        model=await run_blocking(_state().get_model),
        transformer_model_path=_state().TRANSFORMER_MODEL_PATH,
        confidence_band=_state().TRANSFORMER_CONFIDENCE_BAND,
    )
    for item in results:
        _record_linear_monitor(item)
    first = results[0] if results else {}
    return BatchResponse(
        count=len(results),
        results=[AnalyzeResponse.model_validate(item) for item in results],
        model_version=first.get("model_version", "unknown"),
        decision_threshold=float(first.get("decision_threshold", 0.5)),
        metadata_scope="first_result",
    )


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    responses=_ERROR_RESPONSES,
    summary="Submit anonymous label feedback (message text is not accepted)",
)
def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    if (
        _state().SMSD_ENV == "production"
        or not _state().FEEDBACK_ENABLED
        or _state().TRANSFORMER_MODEL_PATH is not None
    ):
        if _state().TRANSFORMER_MODEL_PATH is not None and _state().FEEDBACK_ENABLED:
            raise StarletteHTTPException(
                status_code=404,
                detail="Anonymous feedback is disabled while the optional ensemble is configured because the route cannot be attributed.",
            )
        raise StarletteHTTPException(status_code=404, detail="Anonymous feedback is disabled by the operator.")
    model = _state().get_model()
    current_version = _state()._model_version(model)
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
        _state().logger.error("Could not save anonymous feedback (%s)", type(exc).__name__)
        raise StarletteHTTPException(status_code=503, detail="Feedback is temporarily unavailable.") from exc
    return FeedbackResponse(
        status="received",
        report_id=report_id,
        message="Thanks. The report contains labels and model metadata only; no SMS text was sent.",
    )


def _donation_error(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    response = _state()._error_response(status_code, code, message, details)
    response.headers["Cache-Control"] = "no-store"
    return response


def _donations_enabled() -> bool:
    return bool(_state().DONATIONS_ENABLED and _state().DONATIONS_OPERATOR_CONTACT.strip())


def _loopback_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", maxsplit=1)[0])
    except ValueError:
        return False
    return address.is_loopback or (
        isinstance(address, ipaddress.IPv6Address)
        and address.ipv4_mapped is not None
        and address.ipv4_mapped.is_loopback
    )


def _local_origin(value: str) -> tuple[str, str, int] | None:
    """Accept only a literal loopback origin; never resolve an arbitrary hostname."""
    if any(char.isspace() or ord(char) < 32 for char in value) or any(char in value for char in "?#\\"):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"(?:localhost|[0-9.]+|\[[0-9a-f:.]+\])(?::[0-9]{1,5})?", parsed.netloc, re.IGNORECASE)
        or port == 0
        or (hostname != "localhost" and not _loopback_ip(hostname))
    ):
        return None
    return parsed.scheme, hostname, port if port is not None else (443 if parsed.scheme == "https" else 80)


def _donation_request_is_local(request: Request) -> bool:
    """Require a local peer, loopback authority, and matching browser origin."""
    if _state().SMSD_ENV == "production" or request.client is None:
        return False
    if not _loopback_ip(request.client.host):
        return False
    # Donations are direct-loopback only. A reverse proxy can itself be a
    # loopback peer; reject recognizable forwarding metadata even if Host
    # has been rewritten. This is not a substitute for isolating the origin.
    if any(
        name in request.headers
        for name in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip")
    ):
        return False
    hosts = request.headers.getlist("host")
    if len(hosts) != 1 or not hosts[0] or any(char.isspace() for char in hosts[0]):
        return False
    authority = _local_origin(f"{request.scope['scheme']}://{hosts[0]}")
    if authority is None:
        return False
    origins = request.headers.getlist("origin")
    if origins and (len(origins) != 1 or _local_origin(origins[0]) != authority):
        return False
    # Local CLI requests may omit browser headers. Browser writes must be
    # same-origin, not merely same-site (which includes other local ports).
    sites = request.headers.getlist("sec-fetch-site")
    return request.method in {"GET", "HEAD"} or not sites or sites == ["same-origin"]


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("Nonfinite JSON constant.")


async def _donation_json(request: Request) -> Any:
    # Do not allow ambiguous consent/withdrawal objects or nonstandard JSON.
    return json.loads(await request.body(), object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant)


def _render_notice_contact(response: Response, *, fallback: str) -> Response:
    if response.status_code >= 400:
        return response
    body = getattr(response, "body", b"")
    contact = _state().DONATIONS_OPERATOR_CONTACT.strip() or fallback
    rendered = body.replace(b"__DONATIONS_OPERATOR_CONTACT__", html.escape(contact).encode("utf-8"))
    headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
    return Response(content=rendered, media_type="text/html", headers=headers)


@router.api_route("/donate", methods=["GET", "HEAD"], include_in_schema=False)
def donation_form(request: Request) -> Response:
    if not _donations_enabled() or not _donation_request_is_local(request):
        raise StarletteHTTPException(status_code=404, detail="Donation collection is disabled by the operator.")
    if request.method == "HEAD":
        return Response(content=b"", media_type="text/html", headers={"Cache-Control": "no-store"})
    response = _render_notice_contact(
        _state()._ui_asset_response("donate.html", media_type="text/html"),
        fallback="Local service operator (contact not configured)",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/privacy-notice", include_in_schema=False)
def donation_privacy_notice() -> Response:
    response = _render_notice_contact(
        _state()._ui_asset_response("privacy-notice.html", media_type="text/html"),
        fallback="Local service operator (contact not configured)",
    )
    response.headers["Cache-Control"] = "no-cache"
    return response


@router.post(
    "/donate",
    response_model=DonationResponse,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": DonationRequest.model_json_schema()}},
        }
    },
    summary="Submit an explicitly consented message for local human review",
)
async def donate(request: Request) -> Response:
    """Store only after explicit version-matched consent and conservative PII scan."""
    if not _donations_enabled() or not _donation_request_is_local(request):
        raise StarletteHTTPException(status_code=404, detail="Donation collection is disabled by the operator.")
    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
    if content_type != "application/json":
        return _donation_error(415, "unsupported_media_type", "Submit the donation as application/json.")
    try:
        payload_data = await _donation_json(request)
    except (ValueError, RecursionError):
        return _donation_error(400, "invalid_json", "The request body must contain valid JSON.")
    details: list[dict[str, Any]]
    try:
        payload = DonationRequest.model_validate(payload_data)
    except ValidationError as exc:
        details = [
            {
                "loc": (
                    ["body", "<unknown-field>"]
                    if error.get("type") == "extra_forbidden"
                    else [str(part) for part in error.get("loc", ())]
                ),
                "msg": str(error.get("msg", "Invalid value")),
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors(include_input=False)
        ]
        return _donation_error(422, "validation_error", "Check the donation fields and try again.", details)
    if not payload.consent:
        return _donation_error(400, "consent_required", "Explicit consent is required before a donation can be saved.")
    if not payload.authorized_to_share:
        return _donation_error(
            400,
            "sharing_authorization_required",
            "Confirm that you are authorized to share this message before submitting it.",
        )
    if payload.notice_version != _state().DONATION_NOTICE_VERSION:
        return _donation_error(
            409,
            "notice_version_mismatch",
            "Review the current privacy notice and submit again if you still consent.",
        )

    spans = detect_pii(payload.message)
    if spans:
        details = [
            {"start": span.start, "end": span.end, "category": span.category, "value": span.value} for span in spans
        ]
        return _donation_error(
            422,
            "pii_detected",
            "Remove or redact the flagged personal details, then choose Submit again.",
            details,
        )
    try:
        record_id = await run_blocking(
            create_donation,
            _state().DONATION_DB_PATH,
            message=payload.message,
            label_hint=payload.label_hint,
            language=payload.language,
            notice_version=_state().DONATION_NOTICE_VERSION,
            review_consent=payload.consent,
            authorized_to_share=payload.authorized_to_share,
            model_research_consent=payload.model_research_consent,
            submission_key=payload.submission_key,
        )
    except DonationConflict:
        return _donation_error(
            409,
            "submission_conflict",
            "This submission key was already used. Contact the operator before trying again.",
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _state().logger.error("Could not save local donation (%s)", type(exc).__name__)
        return _donation_error(503, "donation_unavailable", "Local donation storage is temporarily unavailable.")
    result = DonationResponse(
        status="received",
        record_id=record_id,
        retention_days=RETENTION_DAYS,
        notice_version=_state().DONATION_NOTICE_VERSION,
    )
    return JSONResponse(
        status_code=201,
        content=result.model_dump(),
        headers={"Cache-Control": "no-store"},
    )


@router.delete(
    "/donate",
    include_in_schema=True,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": DonationWithdrawalRequest.model_json_schema()}},
        }
    },
    summary="Withdraw and erase a local donation",
)
async def withdraw_donation(request: Request) -> Response:
    if not _donations_enabled() or not _donation_request_is_local(request):
        raise StarletteHTTPException(status_code=404, detail="Donation collection is disabled by the operator.")
    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
    if content_type != "application/json":
        return _donation_error(415, "unsupported_media_type", "Submit the withdrawal as application/json.")
    try:
        payload_data = await _donation_json(request)
    except (ValueError, RecursionError):
        return _donation_error(400, "invalid_json", "The request body must contain valid JSON.")
    try:
        payload = DonationWithdrawalRequest.model_validate(payload_data)
    except ValidationError as exc:
        details = [
            {
                "loc": (
                    ["body", "<unknown-field>"]
                    if error.get("type") == "extra_forbidden"
                    else [str(part) for part in error.get("loc", ())]
                ),
                "msg": str(error.get("msg", "Invalid value")),
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors(include_input=False)
        ]
        return _donation_error(422, "validation_error", "Check the withdrawal field and try again.", details)
    try:
        if re.fullmatch(r"[a-f0-9]{32}", payload.record_id):
            await run_blocking(delete_donation, _state().DONATION_DB_PATH, payload.record_id)
    except (OSError, RuntimeError) as exc:
        _state().logger.error("Could not withdraw local donation (%s)", type(exc).__name__)
        return _donation_error(503, "donation_unavailable", "Local donation storage is temporarily unavailable.")
    return JSONResponse(status_code=200, content={"status": "withdrawn"}, headers={"Cache-Control": "no-store"})
