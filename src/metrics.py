"""Classification metrics, threshold tuning, and calibration diagnostics.

The product goal is precision-first (never make a legitimate OTP or bank alert
look like a scam), so the threshold is tuned on a validation split rather than
on the test split or the holdout set. All functions are pure/deterministic and
are shared by training and evaluation so the two cannot drift apart.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss

VALID_LABELS = ("ham", "spam")


def _positive_probabilities(probabilities: Iterable[float]) -> np.ndarray:
    probs = np.asarray(list(probabilities), dtype=float)
    if probs.ndim != 1:
        raise ValueError("probabilities must be a 1-D sequence")
    if not np.all(np.isfinite(probs)):
        raise ValueError("probabilities contain NaN/inf")
    if np.any(probs < 0) or np.any(probs > 1):
        raise ValueError("probabilities must be within [0, 1]")
    return probs


def _labels(labels: Sequence[str]) -> np.ndarray:
    array = np.asarray(list(labels), dtype=object)
    if array.ndim != 1:
        raise ValueError("labels must be a 1-D sequence")
    unknown = sorted({str(label) for label in array} - set(VALID_LABELS))
    if unknown:
        raise ValueError(f"labels must be one of {VALID_LABELS}; found {unknown}")
    return array


def binary_metrics(labels: Sequence[str], probabilities: Iterable[float], threshold: float) -> dict[str, Any]:
    """Precision/recall/confusion counts for spam at a given decision threshold."""
    y = _labels(labels)
    probs = _positive_probabilities(probabilities)
    if len(y) != len(probs):
        raise ValueError(f"labels and probabilities differ in length ({len(y)} != {len(probs)})")
    if not 0.0 <= float(threshold) <= 1.0:
        raise ValueError("threshold must be within [0, 1]")
    predicted = np.where(probs >= float(threshold), "spam", "ham")
    is_spam = y == "spam"
    is_pred_spam = predicted == "spam"
    tp = int(np.sum(is_spam & is_pred_spam))
    fp = int(np.sum(~is_spam & is_pred_spam))
    tn = int(np.sum(~is_spam & ~is_pred_spam))
    fn = int(np.sum(is_spam & ~is_pred_spam))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(y) if len(y) else 0.0
    false_positive_rate = fp / (fp + tn) if fp + tn else 0.0
    return {
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "accuracy": float(accuracy),
        "false_positive_rate": float(false_positive_rate),
        "predicted_spam_rate": float((tp + fp) / len(y)) if len(y) else 0.0,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "support": int(len(y)),
        "support_spam": int(np.sum(is_spam)),
        "support_ham": int(np.sum(~is_spam)),
    }


def fbeta(precision: float, recall: float, beta: float) -> float:
    if beta <= 0:
        raise ValueError("beta must be > 0")
    beta_sq = beta * beta
    denominator = beta_sq * precision + recall
    if denominator == 0:
        return 0.0
    return (1 + beta_sq) * precision * recall / denominator


def threshold_sweep(
    labels: Sequence[str],
    probabilities: Iterable[float],
    thresholds: Iterable[float] | None = None,
    *,
    step: float = 0.01,
) -> list[dict[str, Any]]:
    """Evaluate every threshold in a deterministic grid (default 0.00..1.00)."""
    if thresholds is None:
        if not 0 < step <= 1:
            raise ValueError("step must be within (0, 1]")
        count = int(round(1 / step))
        thresholds = [round(index / count, 4) for index in range(count + 1)]
    return [binary_metrics(labels, probabilities, threshold) for threshold in thresholds]


@dataclass(frozen=True)
class ThresholdChoice:
    threshold: float
    precision: float
    recall: float
    f1: float
    fbeta: float
    target_precision: float
    min_recall: float
    achieved_target: bool
    strategy: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def select_threshold(
    labels: Sequence[str],
    probabilities: Iterable[float],
    *,
    target_precision: float = 0.98,
    min_recall: float = 0.0,
    default_threshold: float = 0.5,
) -> ThresholdChoice:
    """Pick a spam threshold on validation data with a documented tradeoff.

    Strategy: among thresholds that reach ``target_precision`` (and optionally
    ``min_recall``), choose the lowest threshold — i.e. the one that catches the
    most spam while keeping the precision promise. If no threshold reaches the
    target, fall back to the threshold maximising F0.5 (precision-weighted) and
    say so explicitly; never silently pretend the target was met.
    """
    if not 0.0 <= target_precision <= 1.0:
        raise ValueError("target_precision must be within [0, 1]")
    if not 0.0 <= min_recall <= 1.0:
        raise ValueError("min_recall must be within [0, 1]")
    sweep = threshold_sweep(labels, probabilities)
    # Thresholds exactly 0/1 are not usable decision boundaries (they predict
    # everything as spam/nothing as spam) and are rejected by model loading.
    candidates = [row for row in sweep if 0.0 < row["threshold"] < 1.0]
    if not candidates:  # pragma: no cover - only possible for empty input
        candidates = [binary_metrics(labels, probabilities, default_threshold)]
    qualifying = [
        row
        for row in candidates
        if row["precision"] >= target_precision and row["recall"] >= min_recall
    ]
    if qualifying:
        # Among thresholds that satisfy the precision/recall contract, pick the
        # one with the best precision-weighted F0.5. This avoids selecting a
        # very low threshold that technically meets a precision floor on
        # validation but produces more false positives on unseen data.
        best = max(
            qualifying,
            key=lambda row: (fbeta(row["precision"], row["recall"], beta=0.5), -row["threshold"]),
        )
        choice = ThresholdChoice(
            threshold=best["threshold"],
            precision=best["precision"],
            recall=best["recall"],
            f1=best["f1"],
            fbeta=fbeta(best["precision"], best["recall"], beta=0.5),
            target_precision=target_precision,
            min_recall=min_recall,
            achieved_target=True,
            strategy="max_f0.5_subject_to_precision_recall",
            note=(
                f"Best precision-weighted F0.5 among validation thresholds with spam precision >= "
                f"{target_precision:.2f}"
                + (f" and recall >= {min_recall:.2f}" if min_recall else "")
                + "; precision is weighted twice as heavily as recall."
            ),
        )
        return choice

    fallback_candidates = [row for row in candidates if row["recall"] >= min_recall]
    if not fallback_candidates:
        fallback_candidates = candidates
    best = max(
        fallback_candidates,
        key=lambda row: (
            fbeta(row["precision"], row["recall"], beta=0.5),
            -row["threshold"],
        ),
    )
    choice = ThresholdChoice(
        threshold=best["threshold"],
        precision=best["precision"],
        recall=best["recall"],
        f1=best["f1"],
        fbeta=fbeta(best["precision"], best["recall"], beta=0.5),
        target_precision=target_precision,
        min_recall=min_recall,
        achieved_target=False,
        strategy="f0.5_fallback",
        note=(
            f"No validation threshold reached spam precision >= {target_precision:.2f}"
            + (f" with recall >= {min_recall:.2f}" if min_recall else "")
            + "; fell back to the F0.5-optimal threshold. Collect more legitimate examples "
            "and re-tune before deployment."
        ),
    )
    # The default threshold is reported for comparison even when not selected.
    _ = default_threshold
    return choice


def expected_calibration_error(
    labels: Sequence[str],
    probabilities: Iterable[float],
    *,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Binned expected/max calibration error and the reliability table."""
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    y = (_labels(labels) == "spam").astype(float)
    probs = _positive_probabilities(probabilities)
    if len(y) != len(probs):
        raise ValueError(f"labels and probabilities differ in length ({len(y)} != {len(probs)})")
    if len(y) == 0:
        raise ValueError("calibration requires at least one example")

    boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[dict[str, Any]] = []
    ece = 0.0
    mce = 0.0
    for index in range(n_bins):
        lower, upper = boundaries[index], boundaries[index + 1]
        # Include the final right edge in the last bin.
        if index == n_bins - 1:
            mask = (probs >= lower) & (probs <= upper)
        else:
            mask = (probs >= lower) & (probs < upper)
        count = int(np.sum(mask))
        if count == 0:
            bins.append(
                {
                    "bin_lower": float(lower),
                    "bin_upper": float(upper),
                    "count": 0,
                    "mean_probability": None,
                    "observed_rate": None,
                }
            )
            continue
        mean_probability = float(np.mean(probs[mask]))
        observed_rate = float(np.mean(y[mask]))
        gap = abs(mean_probability - observed_rate)
        ece += (count / len(y)) * gap
        mce = max(mce, gap)
        bins.append(
            {
                "bin_lower": float(lower),
                "bin_upper": float(upper),
                "count": count,
                "mean_probability": mean_probability,
                "observed_rate": observed_rate,
            }
        )
    return {
        "n": int(len(y)),
        "n_bins": n_bins,
        "expected_calibration_error": float(ece),
        "max_calibration_error": float(mce),
        "bins": bins,
    }


def calibration_metrics(
    labels: Sequence[str],
    probabilities: Iterable[float],
    *,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Brier score, log loss, and calibration bins for the spam probability."""
    y = (_labels(labels) == "spam").astype(float)
    probs = _positive_probabilities(probabilities)
    if len(y) != len(probs):
        raise ValueError(f"labels and probabilities differ in length ({len(y)} != {len(probs)})")
    if len(y) == 0:
        raise ValueError("calibration requires at least one example")
    clipped = np.clip(probs, 1e-15, 1 - 1e-15)
    metrics: dict[str, Any] = {
        "n": int(len(y)),
        "brier_score": float(brier_score_loss(y, probs)),
        "log_loss": float(log_loss(y, clipped, labels=[0, 1])),
    }
    metrics.update(expected_calibration_error(labels, probabilities, n_bins=n_bins))
    return metrics


def per_group_metrics(
    frame,
    probabilities: Iterable[float],
    threshold: float,
    *,
    group_columns: Sequence[str] = ("source_file", "category"),
    min_count: int = 1,
) -> list[dict[str, Any]]:
    """Metrics grouped by metadata columns (source file, message category, ...).

    ``frame`` must have a ``label`` column; missing/blank group values are
    reported as ``"unknown"`` rather than dropped, so coverage is visible.
    """
    probs = _positive_probabilities(probabilities)
    if len(frame) != len(probs):
        raise ValueError(f"frame and probabilities differ in length ({len(frame)} != {len(probs)})")
    missing = [column for column in ("label", *group_columns) if column not in frame.columns]
    if missing:
        raise ValueError(f"frame is missing columns: {missing}")
    labels = _labels(frame["label"].astype(str).tolist())
    results: list[dict[str, Any]] = []
    group_frame = frame.copy()
    group_frame["_probability"] = probs
    group_frame["_label"] = labels
    grouped = group_frame.groupby(list(group_columns), dropna=False, sort=True)
    for key, chunk in grouped:
        if len(chunk) < min_count:
            continue
        key_values = key if isinstance(key, tuple) else (key,)
        entry: dict[str, Any] = {
            column: (None if value is None or (isinstance(value, float) and math.isnan(value)) else str(value))
            for column, value in zip(group_columns, key_values)
        }
        metrics = binary_metrics(chunk["_label"].tolist(), chunk["_probability"].tolist(), threshold)
        entry.update(metrics)
        results.append(entry)
    return results


def false_positive_categories(
    frame,
    probabilities: Iterable[float],
    threshold: float,
    *,
    category_column: str = "category",
) -> dict[str, int]:
    """Count legitimate messages flagged as spam, grouped by message category.

    This is the product-facing error metric: how often does the model flag
    OTPs, bank alerts, delivery notices, or ordinary Taglish conversation?
    """
    probs = _positive_probabilities(probabilities)
    if len(frame) != len(probs):
        raise ValueError(f"frame and probabilities differ in length ({len(frame)} != {len(probs)})")
    if "label" not in frame.columns:
        raise ValueError("frame must have a label column")
    if category_column not in frame.columns:
        return {}
    counts: dict[str, int] = {}
    for label, probability, category in zip(frame["label"], probs, frame[category_column]):
        if str(label) != "ham":
            continue
        if float(probability) >= float(threshold):
            key = "unknown" if category is None or str(category).strip() == "" else str(category)
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def jsonable(value: Any) -> Any:
    """Recursively convert numpy/scikit-learn scalars into JSON-safe values."""
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    return value
