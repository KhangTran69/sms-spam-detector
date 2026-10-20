"""HTTP route handlers.

Mutable configuration and the model cache stay in :mod:`api.main` (tests and
deployments patch them there), so handlers read them through ``_state()`` at
request time instead of copying them at import.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from fastapi import APIRouter
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.schemas import (
    _ERROR_RESPONSES,
    AnalyzeResponse,
    BatchRequest,
    BatchResponse,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    PredictRequest,
    PredictResponse,
    ReadinessResponse,
)
from src.predict import analyze_batch, analyze_message, model_info

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


@router.post("/predict", response_model=PredictResponse, responses=_ERROR_RESPONSES, summary="Minimal verdict")
def predict(request: PredictRequest) -> PredictResponse:
    analysis = analyze_message(request.message, model=_state().get_model())
    return PredictResponse(
        prediction=analysis["prediction"],
        probability=analysis["probability"],
        probability_calibrated=analysis["probability_calibrated"],
        flags=analysis["flags"],
        decision_threshold=analysis["decision_threshold"],
        model_version=analysis["model_version"],
    )


@router.post("/analyze", response_model=AnalyzeResponse, responses=_ERROR_RESPONSES, summary="Full analysis")
def analyze(request: PredictRequest) -> AnalyzeResponse:
    return AnalyzeResponse.model_validate(analyze_message(request.message, model=_state().get_model()))


@router.post("/analyze/batch", response_model=BatchResponse, responses=_ERROR_RESPONSES, summary="Batch analysis")
def analyze_batch_endpoint(request: BatchRequest) -> BatchResponse:
    results = analyze_batch(request.messages, model=_state().get_model())
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
