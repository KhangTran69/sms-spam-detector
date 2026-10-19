"""FastAPI application for SMS spam prediction and the bundled web UI."""
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from src.predict import analyze_message, load_model, predict_message

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
MAX_BATCH = 50

app = FastAPI(title="Philippine SMS Scam Detector", version="1.1.0")

# The UI ships with the API and runs on the same origin; permissive CORS keeps
# it usable if the page is opened from a different local origin (file:// etc.).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_model = None


def get_model():
    """Load the trained pipeline once and reuse it across requests."""
    global _model
    if _model is None:
        _model = load_model()
    return _model


def require_model():
    try:
        return get_model()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _reject_blank(value: str) -> str:
    # Kept unstripped: match offsets must align with the original message.
    if not value.strip():
        raise ValueError("message must not be blank")
    return value


BoundedMessage = Annotated[str, StringConstraints(min_length=1, max_length=10000)]
MessageText = Annotated[BoundedMessage, AfterValidator(_reject_blank)]


class PredictRequest(BaseModel):
    message: MessageText = Field(..., description="SMS message to classify")


class BatchRequest(BaseModel):
    messages: list[MessageText] = Field(..., min_length=1, max_length=MAX_BATCH)


class PredictResponse(BaseModel):
    prediction: str
    probability: float
    flags: list[str]


class Match(BaseModel):
    type: str
    text: str
    start: int
    end: int


class AnalyzeResponse(BaseModel):
    message: str
    prediction: str
    spam_probability: float
    probability: float
    flags: list[str]
    matches: list[Match]
    brands: list[str]


class BatchResponse(BaseModel):
    count: int
    results: list[AnalyzeResponse]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest):
    model = require_model()
    return predict_message(request.message, model=model)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: PredictRequest):
    """Full analysis: spam probability, highlightable signal spans, brands."""
    model = require_model()
    return analyze_message(request.message, model=model)


@app.post("/analyze/batch", response_model=BatchResponse)
def analyze_batch(request: BatchRequest):
    model = require_model()
    results = [analyze_message(message, model=model) for message in request.messages]
    return {"count": len(results), "results": results}


if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html")
