"""Train and save baseline and primary SMS classifiers."""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401  (re-exported for notebook use)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, precision_score
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB

from src.features import make_model, messages_to_frame

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "raw" / "spam.csv"
DEFAULT_SUPPLEMENT = ROOT / "data" / "raw" / "ph_supplement.csv"
DEFAULT_MODEL = ROOT / "models" / "spam_detector_v1.pkl"
TEST_SIZE = 0.2
RANDOM_STATE = 42


def _read_csv(path: str | Path) -> pd.DataFrame:
    """Read a CSV, preferring UTF-8 and falling back to latin-1 (Kaggle exports)."""
    try:
        return pd.read_csv(path, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin-1")


def load_dataset(path: str | Path) -> tuple[list[str], list[str]]:
    """Load one labeled CSV (Kaggle v1/v2 or label/message columns)."""
    df = _read_csv(path)
    if {"v1", "v2"}.issubset(df.columns):
        labels, messages = df["v1"], df["v2"]
    elif {"label", "message"}.issubset(df.columns):
        labels, messages = df["label"], df["message"]
    else:
        raise ValueError(f"{path}: CSV needs either Kaggle columns v1/v2 or columns label/message")
    labels = labels.astype(str).str.strip().str.lower().replace(
        {"ham": "ham", "legitimate": "ham", "legit": "ham", "spam": "spam", "scam": "spam"}
    )
    keep = labels.isin(["ham", "spam"]) & messages.notna()
    return messages[keep].astype(str).tolist(), labels[keep].tolist()


def load_training_data(
    data_path: str | Path = DEFAULT_DATA,
    supplement_path: str | Path | None = DEFAULT_SUPPLEMENT,
) -> tuple[list[str], list[str]]:
    """Load the base dataset plus the optional Philippine supplement, deduplicated.

    Exact duplicate message texts are dropped (first occurrence wins), so a
    pattern present in both files is not double-counted.
    """
    if data_path is None:
        raise ValueError("data_path is required")
    messages, labels = load_dataset(data_path)
    base_counts = {"ham": labels.count("ham"), "spam": labels.count("spam")}
    supplement_counts = None
    if supplement_path is not None and Path(supplement_path).exists():
        sup_messages, sup_labels = load_dataset(supplement_path)
        messages = messages + sup_messages
        labels = labels + sup_labels
        supplement_counts = {"ham": sup_labels.count("ham"), "spam": sup_labels.count("spam")}
    seen: set[str] = set()
    dedup_messages: list[str] = []
    dedup_labels: list[str] = []
    dropped = 0
    for message, label in zip(messages, labels):
        if message in seen:
            dropped += 1
            continue
        seen.add(message)
        dedup_messages.append(message)
        dedup_labels.append(label)
    print(f"Dataset: base={sum(base_counts.values())} {base_counts}", end="")
    if supplement_counts is not None:
        print(f" + supplement={sum(supplement_counts.values())} {supplement_counts}", end="")
    print(f" | dropped {dropped} duplicates | total={len(dedup_messages)}")
    return dedup_messages, dedup_labels


def train(
    data_path: str | Path = DEFAULT_DATA,
    model_path: str | Path = DEFAULT_MODEL,
    supplement_path: str | Path | None = DEFAULT_SUPPLEMENT,
    test_size: float = TEST_SIZE,
    random_state: int = RANDOM_STATE,
):
    messages, labels = load_training_data(data_path, supplement_path)
    if len(set(labels)) < 2:
        raise ValueError("Training data must contain both ham and spam examples")
    X_train, X_test, y_train, y_test = train_test_split(
        messages, labels, test_size=test_size, random_state=random_state, stratify=labels
    )
    train_frame, test_frame = messages_to_frame(X_train), messages_to_frame(X_test)

    baseline = make_model(MultinomialNB())
    primary = make_model(
        LogisticRegression(class_weight="balanced", max_iter=2000, solver="liblinear", random_state=random_state)
    )
    baseline.fit(train_frame, y_train)
    primary.fit(train_frame, y_train)

    print(f"\nMultinomialNB baseline (test split, {len(y_test)} messages)")
    print(classification_report(y_test, baseline.predict(test_frame), zero_division=0))
    print("Balanced LogisticRegression (primary)")
    predictions = primary.predict(test_frame)
    print(classification_report(y_test, predictions, zero_division=0))
    print(f"Spam precision: {precision_score(y_test, predictions, pos_label='spam', zero_division=0):.4f}")

    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(primary, model_path)
    print(f"Saved model to {model_path}")
    return primary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--supplement", default=str(DEFAULT_SUPPLEMENT), help="Philippine supplement CSV; pass 'none' to disable")
    parser.add_argument("--output", default=str(DEFAULT_MODEL))
    args = parser.parse_args()
    supplement = None if args.supplement.lower() == "none" else args.supplement
    train(args.data, args.output, supplement)
