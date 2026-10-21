"""Request and response schemas for the HTTP API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from src.predict import MAX_MESSAGE_LENGTH

MAX_BATCH = 50
MAX_BATCH_CHARACTERS = 200_000


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
    suspicious_threshold: float
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
