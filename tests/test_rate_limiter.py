from __future__ import annotations

import hashlib
import json
import logging

from api.rate_limiter import InMemoryRateLimiter, RedisRateLimiter, create_rate_limiter


class RedisStub:
    def __init__(self, result: tuple[int, int] = (1, 0), error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, int, str, int, int, str]] = []

    def ping(self) -> bool:
        return True

    def eval(self, script: str, key_count: int, key: str, window_ms: int, limit: int, member: str):
        self.calls.append((script, key_count, key, window_ms, limit, member))
        if self.error:
            raise self.error
        return self.result


def test_in_memory_limiter_uses_sliding_window_and_exact_expiry_boundary() -> None:
    limiter = InMemoryRateLimiter()

    assert limiter.check("prediction", "192.0.2.10", 2, 60, now=100) == (True, 0)
    assert limiter.check("prediction", "192.0.2.10", 2, 60, now=105) == (True, 0)
    assert limiter.check("prediction", "192.0.2.10", 2, 60, now=109) == (False, 51)
    # Timestamp 100 is outside the window when current time is 160.
    assert limiter.check("prediction", "192.0.2.10", 2, 60, now=160) == (True, 0)


def test_in_memory_limiter_bounds_identity_table_without_evicting_live_counters() -> None:
    limiter = InMemoryRateLimiter(max_identities=2)
    assert limiter.check("prediction", "fixture-a", 1, 60, now=100) == (True, 0)
    assert limiter.check("prediction", "fixture-b", 1, 60, now=101) == (True, 0)
    for index in range(20):
        assert limiter.check("prediction", f"fixture-new-{index}", 1, 60, now=102) == (False, 1)
    assert len(limiter._records) == 2
    assert limiter.check("prediction", "fixture-a", 1, 60, now=103) == (False, 57)
    assert limiter.check("prediction", "fixture-c", 1, 60, now=160) == (True, 0)
    assert len(limiter._records) == 2
    limiter.reset()
    assert limiter.check("prediction", "fixture-d", 1, 60, now=161) == (True, 0)


def test_in_memory_limiter_namespaces_endpoints() -> None:
    limiter = InMemoryRateLimiter()

    assert limiter.check("prediction", "192.0.2.10", 1, 60, now=100) == (True, 0)
    assert limiter.check("donation", "192.0.2.10", 1, 60, now=100) == (True, 0)
    assert limiter.check("prediction", "192.0.2.10", 1, 60, now=101) == (False, 59)


def test_in_memory_retry_after_rounds_up_fractional_seconds() -> None:
    limiter = InMemoryRateLimiter()

    assert limiter.check("prediction", "192.0.2.10", 1, 60, now=100) == (True, 0)
    assert limiter.check("prediction", "192.0.2.10", 1, 60, now=100.2) == (False, 60)
    assert limiter.check("prediction", "192.0.2.10", 1, 60, now=159.2) == (False, 1)
    assert limiter.check("prediction", "192.0.2.10", 1, 60, now=160.2) == (True, 0)


def test_redis_limiter_calls_atomic_script_with_namespaced_hashed_key() -> None:
    client = RedisStub()
    limiter = RedisRateLimiter(client)
    identity = "203.0.113.45"

    assert limiter.check("prediction", identity, 60, 60) == (True, 0)

    script, key_count, key, window_ms, limit, _member = client.calls[0]
    expected_digest = hashlib.sha256(identity.encode()).hexdigest()
    assert key_count == 1
    assert key == f"smsd:rl:prediction:{expected_digest}"
    assert window_ms == 60_000 and limit == 60
    assert "ZREMRANGEBYSCORE" in script and "ZADD" in script and "TIME" in script


def test_redis_limiter_fails_open_and_emits_content_free_warning(caplog) -> None:
    client = RedisStub(error=RuntimeError("redis password must never be logged"))
    limiter = RedisRateLimiter(client)

    with caplog.at_level(logging.WARNING, logger="api.rate_limiter"):
        assert limiter.check("donation", "203.0.113.45", 1, 60) == (True, 0)

    assert limiter.failure_count == 1
    assert "rate_limiter_fail_open" in caplog.text
    warning_record = next(record.message for record in caplog.records if "rate_limiter_fail_open" in record.message)
    warning = json.loads(warning_record)
    assert warning["failure_count"] == 1
    assert "redis password" not in caplog.text
    assert "203.0.113.45" not in caplog.text


def test_unset_redis_url_uses_in_memory_limiter(monkeypatch) -> None:
    monkeypatch.delenv("SMSD_REDIS_URL", raising=False)

    assert isinstance(create_rate_limiter(), InMemoryRateLimiter)


def test_configured_redis_is_selected_after_successful_ping() -> None:
    client = RedisStub()

    limiter = create_rate_limiter("redis://cache.example.test/0", client_factory=lambda _url: client)

    assert isinstance(limiter, RedisRateLimiter)
    assert limiter.check("prediction", "192.0.2.2", 1, 60) == (True, 0)
    assert len(client.calls) == 1


def test_unavailable_redis_uses_in_memory_fallback_and_warns_once(monkeypatch, caplog) -> None:
    def unavailable(_url: str):
        raise OSError("connection details must not be logged")

    monkeypatch.setattr("api.rate_limiter._create_redis_client", unavailable)
    with caplog.at_level(logging.WARNING, logger="api.rate_limiter"):
        limiter = create_rate_limiter("redis://secret@example.test/0")

    assert isinstance(limiter, InMemoryRateLimiter)
    assert caplog.text.count("rate_limiter_startup_fallback") == 1
    assert "secret@example.test" not in caplog.text
    assert "connection details" not in caplog.text


def test_redis_failure_closes_in_production_without_leaking_details(monkeypatch, caplog) -> None:
    import pytest

    from api.rate_limiter import RateLimiterUnavailable

    monkeypatch.setenv("SMSD_ENV", "production")
    monkeypatch.delenv("SMSD_RATE_LIMIT_FAILURE_MODE", raising=False)
    client = RedisStub(error=RuntimeError("private Redis credential"))
    limiter = create_rate_limiter("redis://cache.example.test/0", client_factory=lambda _url: client)
    with caplog.at_level("WARNING", logger="api.rate_limiter"), pytest.raises(RateLimiterUnavailable):
        limiter.check("prediction", "192.0.2.44", 3, 60)
    assert "private Redis credential" not in caplog.text
    assert "192.0.2.44" not in caplog.text
    assert "closed" in caplog.text


def test_redis_startup_failure_closes_in_production(monkeypatch) -> None:
    import pytest

    from api.rate_limiter import RateLimiterUnavailable, UnavailableRateLimiter

    monkeypatch.setenv("SMSD_ENV", "production")
    monkeypatch.delenv("SMSD_RATE_LIMIT_FAILURE_MODE", raising=False)

    def cannot_connect(_url):
        raise OSError("credential must not be logged")

    limiter = create_rate_limiter("redis://cache.example.test/0", client_factory=cannot_connect)
    assert isinstance(limiter, UnavailableRateLimiter)
    with pytest.raises(RateLimiterUnavailable):
        limiter.check("prediction", "192.0.2.44", 3, 60)


def test_redis_outage_policy_override_is_validated(monkeypatch) -> None:
    import pytest

    monkeypatch.setenv("SMSD_ENV", "production")
    monkeypatch.setenv("SMSD_RATE_LIMIT_FAILURE_MODE", "open")
    client = RedisStub(error=RuntimeError("offline"))
    limiter = create_rate_limiter("redis://cache.example.test/0", client_factory=lambda _url: client)
    assert limiter.check("prediction", "192.0.2.44", 3, 60) == (True, 0)

    monkeypatch.setenv("SMSD_RATE_LIMIT_FAILURE_MODE", "invalid")
    with pytest.raises(ValueError, match="SMSD_RATE_LIMIT_FAILURE_MODE"):
        create_rate_limiter("redis://cache.example.test/0", client_factory=lambda _url: client)


def test_closed_redis_readiness_detects_failed_ping_and_recovers() -> None:
    import pytest

    from api.rate_limiter import RateLimiterUnavailable

    class ProbeStub(RedisStub):
        available = True

        def ping(self) -> bool:
            if not self.available:
                raise OSError("private Redis connection details")
            return True

    client = ProbeStub()
    limiter = RedisRateLimiter(client, fail_closed=True)
    limiter.ensure_available()
    client.available = False
    with pytest.raises(RateLimiterUnavailable, match="Rate limiting backend unavailable"):
        limiter.ensure_available()
    RedisRateLimiter(client).ensure_available()
    client.available = True
    limiter.ensure_available()


def test_strict_redis_recovers_from_startup_probe_failure(monkeypatch, caplog) -> None:
    import pytest

    from api.rate_limiter import RateLimiterUnavailable

    class RecoveringRedis(RedisStub):
        available = False

        def ping(self) -> bool:
            return self.available

        def eval(self, script, key_count, key, window_ms, limit, member):
            if not self.available:
                raise OSError("private connection details")
            return super().eval(script, key_count, key, window_ms, limit, member)

    monkeypatch.setenv("SMSD_ENV", "production")
    monkeypatch.delenv("SMSD_RATE_LIMIT_FAILURE_MODE", raising=False)
    client = RecoveringRedis()
    limiter = create_rate_limiter("redis://cache.example.test/0", client_factory=lambda _url: client)
    assert isinstance(limiter, RedisRateLimiter)
    assert "redis_retry" in caplog.text
    with pytest.raises(RateLimiterUnavailable):
        limiter.ensure_available()
    with pytest.raises(RateLimiterUnavailable):
        limiter.check("prediction", "fixture-client", 2, 60)
    assert "private connection details" not in caplog.text

    client.available = True
    limiter.ensure_available()
    assert limiter.check("prediction", "fixture-client", 2, 60) == (True, 0)
    client.result = (0, 42)
    assert limiter.check("prediction", "fixture-client", 2, 60) == (False, 42)


def test_strict_redis_rejects_invalid_backend_reply():
    import pytest

    from api.rate_limiter import RateLimiterUnavailable

    for invalid in ((2, 0), (0, 0), (1, 1), (0, 61), ("1", 0)):
        client = RedisStub()
        client.result = invalid
        with pytest.raises(RateLimiterUnavailable):
            RedisRateLimiter(client, fail_closed=True).check("prediction", "fixture", 1, 60)
