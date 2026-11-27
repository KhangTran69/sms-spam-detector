"""Lightweight model prediction score monitoring and distribution drift detection.

Tracks rolling prediction score distributions and detects covariate drift against
baseline evaluation data using Population Stability Index (PSI) and Kolmogorov-Smirnov
tests without persisting raw SMS message content.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import ks_2samp

logger = logging.getLogger("smsd.monitor")

# PSI Alert Thresholds (standard industry benchmarks)
PSI_MODERATE_DRIFT = 0.10
PSI_SIGNIFICANT_DRIFT = 0.20
MAX_BASELINE_BYTES = 256 * 1024
MAX_BASELINE_SCORES = 10_000
MIN_BASELINE_SCORES = 50
BASELINE_SCORE_SEMANTICS = "calibrated_linear_spam_probability_v1"


def write_artifact_baseline(
    path: Path, model_version: str, artifact_sha256: str, source_kind: str, scores: Sequence[float]
) -> None:
    """Create a private score-only reference without overwriting an existing file."""
    if not MIN_BASELINE_SCORES <= len(scores) <= MAX_BASELINE_SCORES:
        raise ValueError("Invalid baseline sample count")
    if source_kind not in ("approved_development", "synthetic_diagnostic"):
        raise ValueError("Invalid baseline source kind")
    if len(artifact_sha256) != 64 or any(char not in "0123456789abcdef" for char in artifact_sha256):
        raise ValueError("Invalid artifact digest")
    if not model_version.strip():
        raise ValueError("Model version required")
    if any(type(score) not in (int, float) or not 0 <= score <= 1 for score in scores):
        raise ValueError("Invalid baseline score")
    payload = {
        "schema_version": 1,
        "model_version": model_version,
        "artifact_sha256": artifact_sha256,
        "score_semantics": BASELINE_SCORE_SEMANTICS,
        "source_kind": source_kind,
        # Sort to discard the association with the original row ordering.
        "scores": sorted(float(score) for score in scores),
    }
    encoded = (json.dumps(payload, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > MAX_BASELINE_BYTES:
        raise ValueError("Baseline exceeds size limit")
    # Exclusive creation (also rejects existing symbolic links). The parent
    # directory must already be provisioned as private storage by the operator.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        raise


def read_artifact_baseline(path: Path, model_version: str, artifact_sha256: str) -> tuple[list[float], str]:
    """Read only a bounded, exact-artifact-matched score file (never SMS content)."""
    with path.open("rb") as handle:
        raw = handle.read(MAX_BASELINE_BYTES + 1)
    if len(raw) > MAX_BASELINE_BYTES:
        raise ValueError("Baseline exceeds size limit")
    payload = json.loads(raw)
    expected = {"schema_version", "model_version", "artifact_sha256", "score_semantics", "source_kind", "scores"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("Invalid baseline schema")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or payload["model_version"] != model_version
        or payload["artifact_sha256"] != artifact_sha256
        or payload["score_semantics"] != BASELINE_SCORE_SEMANTICS
        or payload["source_kind"] not in ("approved_development", "synthetic_diagnostic")
    ):
        raise ValueError("Incompatible baseline provenance")
    scores = payload["scores"]
    if not isinstance(scores, list) or not MIN_BASELINE_SCORES <= len(scores) <= MAX_BASELINE_SCORES:
        raise ValueError("Invalid baseline sample count")
    if any(type(score) not in (float, int) or not 0 <= score <= 1 for score in scores):
        raise ValueError("Invalid baseline score")
    return [float(score) for score in scores], str(payload["source_kind"])


def compute_distribution_summary(scores: Sequence[float]) -> dict[str, Any]:
    """Compute summary statistics for a sequence of probability scores."""
    if not scores:
        return {
            "count": 0,
            "mean": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "percentiles": {
                "p10": 0.0,
                "p25": 0.0,
                "p50": 0.0,
                "p75": 0.0,
                "p90": 0.0,
                "p99": 0.0,
            },
        }

    arr = np.asarray(scores, dtype=np.float64)
    percentiles = np.percentile(arr, [10, 25, 50, 75, 90, 99])
    return {
        "count": int(len(arr)),
        "mean": round(float(np.mean(arr)), 4),
        "std": round(float(np.std(arr)), 4),
        "min": round(float(np.min(arr)), 4),
        "max": round(float(np.max(arr)), 4),
        "percentiles": {
            "p10": round(float(percentiles[0]), 4),
            "p25": round(float(percentiles[1]), 4),
            "p50": round(float(percentiles[2]), 4),
            "p75": round(float(percentiles[3]), 4),
            "p90": round(float(percentiles[4]), 4),
            "p99": round(float(percentiles[5]), 4),
        },
    }


def compute_psi(
    baseline_scores: Sequence[float],
    current_scores: Sequence[float],
    *,
    bins: int = 10,
    epsilon: float = 1e-4,
) -> float:
    """Calculate Population Stability Index (PSI) between two score distributions.

    Decile bins are established on the [0.0, 1.0] interval. Epsilon smoothing
    prevents division by zero or undefined log ratios.
    """
    if len(baseline_scores) < 2 or len(current_scores) < 2:
        return 0.0

    b_arr = np.clip(np.asarray(baseline_scores, dtype=np.float64), 0.0, 1.0)
    c_arr = np.clip(np.asarray(current_scores, dtype=np.float64), 0.0, 1.0)

    # Establish quantile-based bins from baseline distribution for robust deciles
    quantiles = np.linspace(0, 100, bins + 1)
    bin_edges = np.unique(np.percentile(b_arr, quantiles))
    if len(bin_edges) < 3:
        bin_edges = np.linspace(0.0, 1.0, bins + 1)
    bin_edges[0] = -1e-9
    bin_edges[-1] = 1.0 + 1e-9

    b_counts, _ = np.histogram(b_arr, bins=bin_edges)
    c_counts, _ = np.histogram(c_arr, bins=bin_edges)

    b_pct = b_counts / len(b_arr)
    c_pct = c_counts / len(c_arr)

    # Apply epsilon smoothing
    b_pct = np.where(b_pct == 0, epsilon, b_pct)
    c_pct = np.where(c_pct == 0, epsilon, c_pct)

    b_pct = b_pct / np.sum(b_pct)
    c_pct = c_pct / np.sum(c_pct)

    psi = np.sum((c_pct - b_pct) * np.log(c_pct / b_pct))
    if math.isnan(psi) or math.isinf(psi):
        return 0.0
    return max(0.0, round(float(psi), 4))


def compute_drift(
    baseline_scores: Sequence[float],
    current_scores: Sequence[float],
) -> dict[str, Any]:
    """Evaluate drift metrics including PSI and Kolmogorov-Smirnov test."""
    if len(baseline_scores) < 5 or len(current_scores) < 5:
        return {
            "psi": 0.0,
            "drift_status": "insufficient_data",
            "ks_statistic": 0.0,
            "ks_pvalue": 1.0,
            "ks_drift_detected": False,
        }

    psi = compute_psi(baseline_scores, current_scores)
    if psi >= PSI_SIGNIFICANT_DRIFT:
        status = "significant_drift"
    elif psi >= PSI_MODERATE_DRIFT:
        status = "moderate_drift"
    else:
        status = "stable"

    ks_res = ks_2samp(baseline_scores, current_scores)
    ks_stat = round(float(ks_res.statistic), 4)
    ks_pval = round(float(ks_res.pvalue), 4)

    return {
        "psi": psi,
        "drift_status": status,
        "ks_statistic": ks_stat,
        "ks_pvalue": ks_pval,
        "ks_drift_detected": bool(ks_pval < 0.05),
    }


class PredictionMonitor:
    """Thread-safe rolling buffer of prediction score distributions.

    Guarantees privacy by strictly logging timestamps, probabilities, and labels
    without retaining raw input text.
    """

    def __init__(
        self,
        window_size: int = 1000,
        baseline_scores: Sequence[float] | None = None,
    ) -> None:
        self.window_size = window_size
        self._scores: deque[float] = deque(maxlen=window_size)
        self._labels: deque[str] = deque(maxlen=window_size)
        self._lock = threading.Lock()
        self._baseline_scores: list[float] = list(baseline_scores) if baseline_scores else []
        self._last_alert_time: datetime | None = None
        self._events_since_check = 0
        self._baseline_status = "configured" if self._baseline_scores else "not_configured"
        self._baseline_model_version: str | None = None
        self._baseline_source_kind: str | None = None

    def configure_artifact_baseline(
        self,
        path: Path | None,
        *,
        model_version: str,
        artifact_sha256: str | None,
        calibrated: bool,
        ensemble_configured: bool,
    ) -> None:
        """Bind a baseline to one immutable, calibrated linear-only artifact.

        Bad monitoring configuration is visible but does not prevent inference.
        """
        scores: list[float] = []
        status = "not_configured"
        source_kind = None
        if path is not None:
            if not calibrated or ensemble_configured or not artifact_sha256:
                status = "incompatible_baseline"
            else:
                try:
                    scores, source_kind = read_artifact_baseline(path, model_version, artifact_sha256)
                    status = "configured"
                except (OSError, ValueError, RecursionError):
                    status = "invalid_baseline"
            if status != "configured":
                logger.warning("Model monitoring baseline disabled: %s", status)
        with self._lock:
            self._baseline_scores = scores
            self._baseline_status = status
            self._baseline_model_version = model_version
            self._baseline_source_kind = source_kind
            self._scores.clear()
            self._labels.clear()
            self._last_alert_time = None
            self._events_since_check = 0

    def set_baseline(self, scores: Sequence[float]) -> None:
        """Set baseline scores (e.g. from holdout or validation dataset)."""
        with self._lock:
            self._baseline_scores = list(scores)
            self._baseline_status = "configured" if self._baseline_scores else "not_configured"
            self._baseline_model_version = None
            self._baseline_source_kind = None

    def record(self, score: float, label: str) -> None:
        """Record an inference event's calibrated probability score and predicted label."""
        with self._lock:
            self._scores.append(float(score))
            self._labels.append(str(label))

            # Bound the cost of background drift calculations.
            self._events_since_check += 1
            if len(self._scores) >= 50 and self._baseline_scores and self._events_since_check >= 50:
                self._events_since_check = 0
                psi = compute_psi(self._baseline_scores, list(self._scores))
                if psi >= PSI_SIGNIFICANT_DRIFT:
                    now = datetime.now(UTC)
                    if self._last_alert_time is None or (now - self._last_alert_time).total_seconds() > 300:
                        self._last_alert_time = now
                        logger.warning(
                            "Model score distribution drift detected: PSI=%.4f (threshold=%.2f)",
                            psi,
                            PSI_SIGNIFICANT_DRIFT,
                        )

    def get_metrics(self) -> dict[str, Any]:
        """Generate current distribution summary, spam ratio, and drift metrics."""
        with self._lock:
            scores = list(self._scores)
            labels = list(self._labels)
            baseline = list(self._baseline_scores)
            baseline_status = self._baseline_status
            baseline_model_version = self._baseline_model_version
            baseline_source_kind = self._baseline_source_kind

        summary = compute_distribution_summary(scores)
        spam_count = labels.count("spam")
        total = len(labels)
        spam_ratio = round(spam_count / total, 4) if total > 0 else 0.0

        metrics: dict[str, Any] = {
            "window_size": self.window_size,
            "samples_in_window": total,
            "spam_ratio": spam_ratio,
            "score_distribution": summary,
            "baseline_status": baseline_status,
            "baseline_model_version": baseline_model_version,
            "baseline_source_kind": baseline_source_kind,
        }

        if baseline:
            drift_scores = [] if baseline_source_kind and len(scores) < MIN_BASELINE_SCORES else scores
            metrics["drift"] = compute_drift(baseline, drift_scores)
            metrics["baseline_samples"] = len(baseline)
        else:
            metrics["drift"] = {
                "psi": 0.0,
                "drift_status": "no_baseline_configured" if baseline_status == "not_configured" else baseline_status,
                "ks_statistic": 0.0,
                "ks_pvalue": 1.0,
                "ks_drift_detected": False,
            }

        return metrics

    def clear(self) -> None:
        """Clear recorded events in the rolling buffer."""
        with self._lock:
            self._scores.clear()
            self._labels.clear()
            self._events_since_check = 0
            self._last_alert_time = None


# Default singleton monitor
default_monitor = PredictionMonitor()
