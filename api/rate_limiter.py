"""Shared sliding-window rate limit backends.

Redis is loaded only when ``SMSD_REDIS_URL`` is set. Counter keys contain a
hash of the direct client identity rather than the address itself, and never
contain request bodies or message-derived values.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, Protocol

logger = logging.getLogger("api.rate_limiter")

_SLIDING_WINDOW_SCRIPT = """
local current_time = redis.call('TIME')
local now_ms = tonumber(current_time[1]) * 1000 + math.floor(tonumber(current_time[2]) / 1000)
local window_ms = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local member = ARGV[3]
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms - window_ms)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry_after = math.ceil((tonumber(oldest[2]) + window_ms - now_ms) / 1000)
    if retry_after < 1 then retry_after = 1 end
    return {0, retry_after}
end
redis.call('ZADD', KEYS[1], now_ms, member)
redis.call('PEXPIRE', KEYS[1], window_ms)
return {1, 0}
"""


class RateLimiterUnavailable(RuntimeError):
    """The configured shared rate-limiting backend cannot enforce limits."""


class UnavailableRateLimiter:
    """Protect traffic if a required Redis backend failed at startup."""

    def check(
        self, endpoint: str, identity: str, limit: int, window_seconds: int, now: float | None = None
    ) -> tuple[bool, int]:
        del endpoint, identity, limit, window_seconds, now
        raise RateLimiterUnavailable("Rate limiting backend unavailable")

    def reset(self) -> None:
        """No counters to clear. Restart to reconnect to Redis."""


class RateLimiter(Protocol):
    """Interface shared by process-local and Redis-backed sliding windows."""

    def check(
        self,
        endpoint: str,
        identity: str,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> tuple[bool, int]: ...

    def reset(self) -> None: ...


class InMemoryRateLimiter:
    """Thread-safe sliding-window limiter for one process."""

    def __init__(self, *, max_identities: int = 10_000) -> None:
        if max_identities <= 0:
            raise ValueError("max_identities must be positive")
        self._max_identities = max_identities
        self._records: dict[tuple[str, str], tuple[int, list[float]]] = {}
        self._lock = threading.Lock()
        self._checks = 0
        self._last_prune: float | None = None

    def check(
        self,
        endpoint: str,
        identity: str,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> tuple[bool, int]:
        if limit <= 0:
            return True, 0

        current_time = time.time() if now is None else now
        window = max(1, int(window_seconds))
        cutoff = current_time - window
        key = (endpoint, identity)
        with self._lock:
            if key not in self._records and len(self._records) >= self._max_identities:
                # Never evict a live counter to admit a new identity. At capacity,
                # bound full-table pruning to once per second.
                if self._last_prune is None or current_time - self._last_prune >= 1:
                    self._prune(current_time)
                if len(self._records) >= self._max_identities:
                    return False, 1
            _, stored_timestamps = self._records.get(key, (window, []))
            timestamps = [timestamp for timestamp in stored_timestamps if timestamp > cutoff]
            if len(timestamps) >= limit:
                retry_after = max(1, math.ceil(timestamps[0] + window - current_time))
                self._records[key] = (window, timestamps)
                return False, retry_after

            timestamps.append(current_time)
            self._records[key] = (window, timestamps)
            self._checks += 1
            if self._checks % 1024 == 0:
                self._prune(current_time)
            return True, 0

    def _prune(self, now: float) -> None:
        self._last_prune = now
        for key, (window, timestamps) in list(self._records.items()):
            active = [timestamp for timestamp in timestamps if timestamp > now - window]
            if active:
                self._records[key] = (window, active)
            else:
                self._records.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self._checks = 0
            self._last_prune = None


class RedisRateLimiter:
    """Atomic sliding-window limiter shared by workers through Redis."""

    def __init__(self, client: Any, *, fail_closed: bool = False) -> None:
        self._client = client
        self._fail_closed = fail_closed
        self._failure_lock = threading.Lock()
        self.failure_count = 0

    def check(
        self,
        endpoint: str,
        identity: str,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> tuple[bool, int]:
        del now  # Redis TIME keeps workers on one clock.
        if limit <= 0:
            return True, 0
        normalized_endpoint = re.sub(r"[^A-Za-z0-9_-]", "_", endpoint)
        identity_digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        redis_key = f"smsd:rl:{normalized_endpoint}:{identity_digest}"
        window_ms = max(1, int(window_seconds)) * 1000
        member = f"{time.time_ns()}:{uuid.uuid4().hex}"
        try:
            result = self._client.eval(
                _SLIDING_WINDOW_SCRIPT,
                1,
                redis_key,
                window_ms,
                int(limit),
                member,
            )
            allowed = bool(int(result[0]))
            retry_after = max(0, int(result[1]))
            return allowed, retry_after
        except Exception as exc:
            with self._failure_lock:
                self.failure_count += 1
                failure_count = self.failure_count
            policy = "closed" if self._fail_closed else "open"
            event = "rate_limiter_fail_closed" if self._fail_closed else "rate_limiter_fail_open"
            logger.warning(
                '{"event":"%s","policy":"%s","failure_count":%d,"error_type":"%s"}',
                event,
                policy,
                failure_count,
                type(exc).__name__,
            )
            if self._fail_closed:
                raise RateLimiterUnavailable("Rate limiting backend unavailable") from None
            return True, 0

    def ensure_available(self) -> None:
        """A strict shared backend must answer the readiness probe."""
        if not self._fail_closed:
            return
        try:
            if not self._client.ping():
                raise RuntimeError("Redis readiness probe failed")
        except Exception:
            raise RateLimiterUnavailable("Rate limiting backend unavailable") from None

    def reset(self) -> None:
        """Redis counters expire naturally; never flush shared application keys."""


def _create_redis_client(redis_url: str) -> Any:
    """Import redis-py lazily and bound connection failures during startup."""
    import redis

    return redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )


def create_rate_limiter(
    redis_url: str | None = None,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> RateLimiter:
    """Create the rate limiter with a configurable Redis outage policy."""
    resolved_url = os.environ.get("SMSD_REDIS_URL", "").strip() if redis_url is None else redis_url.strip()
    if not resolved_url:
        return InMemoryRateLimiter()

    default_mode = "closed" if os.environ.get("SMSD_ENV", "development").strip().lower() == "production" else "open"
    mode = os.environ.get("SMSD_RATE_LIMIT_FAILURE_MODE", default_mode).strip().lower()
    if mode not in {"open", "closed"}:
        raise ValueError("SMSD_RATE_LIMIT_FAILURE_MODE must be 'open' or 'closed'")
    fail_closed = mode == "closed"
    factory = client_factory or _create_redis_client
    client = None
    try:
        client = factory(resolved_url)
        if not client.ping():
            raise RuntimeError("Redis startup probe failed")
    except Exception as exc:
        if fail_closed:
            fallback = "redis_retry" if client is not None else "unavailable"
        else:
            fallback = "memory"
        logger.warning(
            '{"event":"rate_limiter_startup_fallback","backend":"redis","fallback":"%s","error_type":"%s"}',
            fallback,
            type(exc).__name__,
        )
        if not fail_closed:
            return InMemoryRateLimiter()
        if client is None:
            return UnavailableRateLimiter()
        # Retain the shared client after a failed connectivity probe. Subsequent
        # checks remain fail-closed and can reconnect without a process restart.
    return RedisRateLimiter(client, fail_closed=fail_closed)
