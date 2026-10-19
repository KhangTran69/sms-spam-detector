"""Load a trained model and classify SMS messages."""
from __future__ import annotations

from pathlib import Path

import joblib

from src.features import messages_to_frame
from src.preprocess import extract_features, extract_matches

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "spam_detector_v1.pkl"
FLAG_NAMES = ("has_url", "has_phone", "has_money", "has_urgency")


def load_model(path: str | Path = DEFAULT_MODEL):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Model not found at {path}. Train it with: python -m src.train")
    return joblib.load(path)


def analyze_message(message: str, model=None, model_path: str | Path = DEFAULT_MODEL) -> dict:
    """Full analysis for the web UI: verdict, spam probability, signal spans, brands.

    `matches` are character-offset spans into the original message (from
    `extract_matches`), so a client can highlight them without re-parsing.
    """
    model = model or load_model(model_path)
    frame = messages_to_frame([message])
    probabilities = model.predict_proba(frame)[0]
    classes = list(model.classes_)
    if "spam" not in classes:
        raise ValueError("Model does not know the 'spam' class")
    spam_probability = float(probabilities[classes.index("spam")])
    prediction = "spam" if spam_probability >= 0.5 else "ham"
    indicators = extract_features(message)
    flags = [name for name in FLAG_NAMES if indicators[name]]
    matches = extract_matches(message)
    brands: list[str] = []
    for match in matches:
        if match["type"] == "brand":
            brand = match["text"].lower()
            if brand not in brands:
                brands.append(brand)
    return {
        "message": message,
        "prediction": prediction,
        "spam_probability": spam_probability,
        "probability": spam_probability if prediction == "spam" else 1.0 - spam_probability,
        "flags": flags,
        "matches": matches,
        "brands": brands,
    }


def predict_message(message: str, model=None, model_path: str | Path = DEFAULT_MODEL) -> dict:
    analysis = analyze_message(message, model=model, model_path=model_path)
    return {key: analysis[key] for key in ("prediction", "probability", "flags")}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Classify one SMS message")
    parser.add_argument("message")
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    args = parser.parse_args()
    print(predict_message(args.message, model_path=args.model))
