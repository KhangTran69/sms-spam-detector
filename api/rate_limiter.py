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

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], tuple[int, list[float]]] = {}
        self._lock = threading.Lock()
        self._checks = 0

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
            _, stored_timestamps = self._records.get(key, (window, []))
            timestamps = [timestamp for timestamp in stored_timestamps if timestamp > cutoff]
            if len(timestamps) >= limit:
                retry_after = max(1, math.ceil(timestamps[0] + window - current_time))
                self._records[key] = (window, timestamps)
                return False, retry_after

            timestamps.append(current_time)
            self._records[key] = (window, timestamps)
            self._checks += 1
            if self._checks % 1024 == 0 or len(self._records) > 10_000:
                self._prune(current_time)
            return True, 0

    def _prune(self, now: float) -> None:
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


class RedisRateLimiter:
    """Atomic sliding-window limiter shared by workers through Redis."""

    def __init__(self, client: Any) -> None:
        self._client = client
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
            logger.warning(
                '{"event":"rate_limiter_fail_open","failure_count":%d,"error_type":"%s"}',
                failure_count,
                type(exc).__name__,
            )
            return True, 0

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
    """Create the configured backend, falling back to memory if Redis is unavailable."""
    resolved_url = os.environ.get("SMSD_REDIS_URL", "").strip() if redis_url is None else redis_url.strip()
    if not resolved_url:
        return InMemoryRateLimiter()

    factory = client_factory or _create_redis_client
    try:
        client = factory(resolved_url)
        client.ping()
    except Exception as exc:
        logger.warning(
            '{"event":"rate_limiter_startup_fallback","backend":"redis","fallback":"memory","error_type":"%s"}',
            type(exc).__name__,
        )
        return InMemoryRateLimiter()
    return RedisRateLimiter(client)
