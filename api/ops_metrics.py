"""Content-free, bounded operational telemetry for one server process."""

from __future__ import annotations

import math
import threading
from collections import Counter, deque
from typing import Any


def _route_group(path: str) -> str:
    canonical = path.removeprefix("/v1") if path.startswith("/v1/") else path
    if canonical in {"/predict", "/analyze", "/analyze/batch"}:
        return "prediction"
    if canonical == "/feedback":
        return "feedback"
    if canonical == "/donate" or canonical.startswith("/donate/"):
        return "donation"
    if canonical.startswith("/metrics/"):
        return "metrics"
    if canonical in {"/health", "/ready", "/model-info"}:
        return "status"
    if canonical.startswith("/static/") or canonical in {"/", "/sw.js", "/manifest.webmanifest"}:
        return "static"
    return "other"


class OperationsMonitor:
    """Thread-safe counts and a bounded latency window, never user content."""

    def __init__(self, window_size: int = 512) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        self.window_size = window_size
        self._lock = threading.Lock()
        self._latencies: deque[float] = deque(maxlen=window_size)
        self._status: Counter[str] = Counter()
        self._groups: Counter[str] = Counter()
        self._total = 0
        self._outcomes: Counter[str] = Counter()
        self._active_writes = 0
        self._peak_writes = 0

    def write_started(self) -> None:
        with self._lock:
            self._active_writes += 1
            self._peak_writes = max(self._peak_writes, self._active_writes)

    def write_finished(self) -> None:
        with self._lock:
            self._active_writes -= 1

    def record(self, method: str, path: str, status: int, latency_ms: float, outcome: str = "") -> None:
        del method
        category = f"{status // 100}xx" if 100 <= status < 600 else "other"
        duration = float(latency_ms)
        if not math.isfinite(duration) or duration < 0:
            duration = 0.0
        if outcome not in {"service_busy", "rate_limiter_unavailable", "rate_limited", "request_timeout"}:
            outcome = "other"
        with self._lock:
            self._outcomes[outcome] += 1
            self._total += 1
            self._status[category] += 1
            self._groups[_route_group(path)] += 1
            self._latencies.append(duration)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            values = sorted(self._latencies)
            total = self._total
            statuses = dict(self._status)
            groups = dict(self._groups)
            outcomes = dict(self._outcomes)
            active_writes = self._active_writes
            peak_writes = self._peak_writes

        def percentile(p: float) -> float | None:
            if not values:
                return None
            rank = (len(values) - 1) * p
            low = int(rank)
            high = min(low + 1, len(values) - 1)
            return round(values[low] + (values[high] - values[low]) * (rank - low), 2)

        return {
            "scope": "one_process_since_start",
            "request_count": total,
            "status_classes": statuses,
            "route_groups": groups,
            "outcomes": outcomes,
            "active_writes": active_writes,
            "peak_active_writes": peak_writes,
            "latency_window_samples": len(values),
            "latency_p50_ms": percentile(0.5),
            "latency_p95_ms": percentile(0.95),
        }

    def clear(self) -> None:
        with self._lock:
            self._total = 0
            self._status.clear()
            self._groups.clear()
            self._latencies.clear()
            self._outcomes.clear()
            self._peak_writes = self._active_writes


operations_monitor = OperationsMonitor()
