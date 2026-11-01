"""HTTP route handlers.

Mutable configuration and the model cache stay in :mod:`api.main` (tests and
deployments patch them there), so handlers read them through ``_state()`` at
request time instead of copying them at import.
"""

from __future__ import annotations

import asyncio
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

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.donations import RETENTION_DAYS, create_donation, delete_donation
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
    info["feedback_enabled"] = _state().FEEDBACK_ENABLED
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


@router.get(
    "/metrics/distribution",
    response_model=dict[str, Any],
    summary="Prediction score distribution and covariate drift metrics",
)
def get_distribution_metrics() -> dict[str, Any]:
    return default_monitor.get_metrics()


@router.post("/predict", response_model=PredictResponse, responses=_ERROR_RESPONSES, summary="Minimal verdict")
async def predict(request: PredictRequest) -> PredictResponse:
    analysis = await asyncio.to_thread(analyze_message, request.message, model=_state().get_model())
    default_monitor.record(analysis["probability"], analysis["prediction"])
    return PredictResponse(
        prediction=analysis["prediction"],
        probability=analysis["probability"],
        probability_calibrated=analysis["probability_calibrated"],
        flags=analysis["flags"],
        decision_threshold=analysis["decision_threshold"],
        model_version=analysis["model_version"],
    )


@router.post("/analyze", response_model=AnalyzeResponse, responses=_ERROR_RESPONSES, summary="Full analysis")
async def analyze(request: PredictRequest) -> AnalyzeResponse:
    analysis = await asyncio.to_thread(analyze_message, request.message, model=_state().get_model())
    default_monitor.record(analysis["probability"], analysis["prediction"])
    return AnalyzeResponse.model_validate(analysis)


@router.post("/analyze/batch", response_model=BatchResponse, responses=_ERROR_RESPONSES, summary="Batch analysis")
async def analyze_batch_endpoint(request: BatchRequest) -> BatchResponse:
    results = await asyncio.to_thread(analyze_batch, request.messages, model=_state().get_model())
    for item in results:
        default_monitor.record(item["probability"], item["prediction"])
    first = results[0] if results else {}
    return BatchResponse(
        count=len(results),
        results=[AnalyzeResponse.model_validate(item) for item in results],
        model_version=first.get("model_version", "unknown"),
        decision_threshold=float(first.get("decision_threshold", 0.5)),
    )


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    responses=_ERROR_RESPONSES,
    summary="Submit anonymous label feedback (message text is not accepted)",
)
def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    if _state().SMSD_ENV == "production" or not _state().FEEDBACK_ENABLED:
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


def _donation_request_is_local(request: Request) -> bool:
    """Restrict the optional unauthenticated intake to a local development host."""
    if _state().SMSD_ENV == "production" or request.client is None:
        return False
    try:
        address = ipaddress.ip_address(request.client.host.split("%", maxsplit=1)[0])
    except ValueError:
        return False
    return address.is_loopback or (
        isinstance(address, ipaddress.IPv6Address)
        and address.ipv4_mapped is not None
        and address.ipv4_mapped.is_loopback
    )


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
        payload_data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _donation_error(400, "invalid_json", "The request body must contain valid JSON.")
    details: list[dict[str, Any]]
    try:
        payload = DonationRequest.model_validate(payload_data)
    except ValidationError as exc:
        details = [
            {
                "loc": [str(part) for part in error.get("loc", ())],
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
        record_id = create_donation(
            _state().DONATION_DB_PATH,
            message=payload.message,
            label_hint=payload.label_hint,
            language=payload.language,
            notice_version=_state().DONATION_NOTICE_VERSION,
            review_consent=payload.consent,
            authorized_to_share=payload.authorized_to_share,
            model_research_consent=payload.model_research_consent,
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
        payload_data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _donation_error(400, "invalid_json", "The request body must contain valid JSON.")
    try:
        payload = DonationWithdrawalRequest.model_validate(payload_data)
    except ValidationError as exc:
        details = [
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "msg": str(error.get("msg", "Invalid value")),
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors(include_input=False)
        ]
        return _donation_error(422, "validation_error", "Check the withdrawal field and try again.", details)
    try:
        if re.fullmatch(r"[a-f0-9]{32}", payload.record_id):
            delete_donation(_state().DONATION_DB_PATH, payload.record_id)
    except (OSError, RuntimeError) as exc:
        _state().logger.error("Could not withdraw local donation (%s)", type(exc).__name__)
        return _donation_error(503, "donation_unavailable", "Local donation storage is temporarily unavailable.")
    return JSONResponse(status_code=200, content={"status": "withdrawn"}, headers={"Cache-Control": "no-store"})
