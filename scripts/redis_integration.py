"""Exercise the existing shared limiter against a disposable CI Redis service only."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import redis

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.rate_limiter import RateLimiterUnavailable, RedisRateLimiter, create_rate_limiter  # noqa: E402


def assert_unavailable(limiter, identity: str) -> None:
    try:
        limiter.check("prediction", identity, 60, 60)
    except RateLimiterUnavailable:
        return
    raise AssertionError("strict limiter admitted a request during dependency failure")


def exercise_disposable_service(url, client, limiter, container_id: str) -> None:
    """Only the CI-owned disposable service may be paused or reconfigured."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or not re.fullmatch(r"[a-f0-9]{64}", container_id):
        raise ValueError("Expected a disposable GitHub Actions Redis service container")
    old_limit = client.config_get("maxmemory")["maxmemory"]
    old_policy = client.config_get("maxmemory-policy")["maxmemory-policy"]
    retained = f"fictional-ci-retained-{uuid.uuid4().hex}"
    try:
        client.config_set("maxmemory-policy", "noeviction")
        client.config_set("maxmemory", 64 * 1024 * 1024)
        assert int(client.config_get("maxmemory")["maxmemory"]) == 64 * 1024 * 1024
        assert client.config_get("maxmemory-policy")["maxmemory-policy"] == "noeviction"
        assert limiter.check("prediction", retained, 1, 60) == (True, 0)
        # Simulate exhausted memory without allocating arbitrary amounts of RAM.
        client.config_set("maxmemory", 1)
        assert_unavailable(limiter, f"fictional-pressure-{uuid.uuid4().hex}")
        client.config_set("maxmemory", 64 * 1024 * 1024)
        assert limiter.check("prediction", retained, 1, 60)[0] is False
        assert limiter.check("prediction", f"fictional-recovered-{uuid.uuid4().hex}", 1, 60) == (True, 0)

        subprocess.run(["docker", "pause", container_id], check=True, timeout=15)
        try:
            assert_unavailable(limiter, f"fictional-outage-{uuid.uuid4().hex}")
            os.environ["SMSD_RATE_LIMIT_FAILURE_MODE"] = "closed"
            recovering = create_rate_limiter(url)
            assert isinstance(recovering, RedisRateLimiter)
            assert_unavailable(recovering, f"fictional-startup-{uuid.uuid4().hex}")
        finally:
            subprocess.run(["docker", "unpause", container_id], check=True, timeout=15)
        recovering.ensure_available()
        assert recovering.check("prediction", retained, 1, 60)[0] is False
        assert recovering.check("prediction", f"fictional-recovered-{uuid.uuid4().hex}", 1, 60) == (True, 0)
        print("redis-integration: strict memory pressure and paused-service startup/runtime recovery passed")
    finally:
        client.config_set("maxmemory", old_limit)
        client.config_set("maxmemory-policy", old_policy)


def main() -> None:
    url = os.environ["SMSD_TEST_REDIS_URL"]
    parsed = urlparse(url)
    if parsed.scheme != "redis" or parsed.hostname != "127.0.0.1":
        raise ValueError("Integration requires a disposable loopback Redis service")
    first = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
    second = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
    identity = f"fictional-ci-{uuid.uuid4().hex}"
    try:
        a = RedisRateLimiter(first, fail_closed=True)
        b = RedisRateLimiter(second, fail_closed=True)
        a.ensure_available()
        b.ensure_available()
        assert a.check("prediction", identity, 2, 2) == (True, 0)
        assert b.check("prediction", identity, 2, 2) == (True, 0)
        allowed, retry = a.check("prediction", identity, 2, 2)
        assert not allowed and 1 <= retry <= 2
        assert b.check("donation", identity, 2, 2) == (True, 0)
        time.sleep(2.1)
        assert b.check("prediction", identity, 2, 2) == (True, 0)

        # Concurrent clients must share a single admission budget.
        concurrent_identity = f"fictional-ci-{uuid.uuid4().hex}"
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda index: (a if index % 2 else b).check("prediction", concurrent_identity, 5, 60),
                    range(24),
                )
            )
        assert sum(allowed for allowed, _retry in results) == 5
        assert all(retry == 0 if allowed else 1 <= retry <= 60 for allowed, retry in results)

        # Multiple bounded waves exercise a full default per-client budget
        # with both Redis clients and 16 concurrent workers.
        identities = [f"fictional-wave-{uuid.uuid4().hex}" for _ in range(4)]
        started = time.monotonic()
        admitted = [0] * len(identities)
        with ThreadPoolExecutor(max_workers=16) as pool:
            for _wave in range(4):
                wave = list(
                    pool.map(
                        lambda index: (a if index % 2 else b).check("prediction", identities[index // 20], 60, 60),
                        range(80),
                    )
                )
                for index, (allowed, _retry) in enumerate(wave):
                    admitted[index // 20] += int(allowed)
        assert admitted == [60] * 4
        print(f"redis-integration: 320 bounded admissions in {time.monotonic() - started:.3f}s; 240 admitted")
        container_id = os.environ.get("SMSD_TEST_REDIS_CONTAINER_ID", "")
        if container_id:
            exercise_disposable_service(url, first, a, container_id)
    finally:
        first.close()
        second.close()
    print("redis-integration: shared counters, endpoint isolation, expiration and concurrent admission passed")


if __name__ == "__main__":
    main()
