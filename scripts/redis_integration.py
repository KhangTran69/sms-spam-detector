"""Exercise the existing shared limiter against a disposable CI Redis service only."""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import redis

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.rate_limiter import RedisRateLimiter  # noqa: E402


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
    finally:
        first.close()
        second.close()
    print("redis-integration: shared counters, endpoint isolation and expiration passed")


if __name__ == "__main__":
    main()
