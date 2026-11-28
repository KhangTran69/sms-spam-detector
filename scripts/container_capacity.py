"""Bounded HTTP integration against the two disposable CI containers only."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

PORTS = (8003, 8004)
BODY = json.dumps({"message": "Fictional capacity fixture only."}).encode("utf-8")
METRICS_HEADERS = {"X-SMSD-Metrics-Token": "fictional-ci-metrics-token"}


def request(port: int, path: str, *, post: bool = False, identity: int = 1):
    headers = METRICS_HEADERS.copy() if path == "/metrics/operations" else {}
    if post:
        headers.update({"Content-Type": "application/json", "X-Forwarded-For": f"192.0.2.{identity}"})
    query = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=BODY if post else None,
        headers=headers,
    )
    try:
        response = urllib.request.urlopen(query, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, dict(response.headers), json.load(response)


def wait_ready(port: int) -> None:
    for _ in range(40):
        try:
            if request(port, "/ready")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.25)
    raise AssertionError("Disposable API never became ready")


def hold_upload(port: int, stack: ExitStack):
    connection = stack.enter_context(socket.create_connection(("127.0.0.1", port), timeout=15))
    header = (
        f"POST /predict HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(BODY)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    connection.sendall(header + BODY[:1])
    return connection


def read_upload(connection: socket.socket) -> tuple[int, dict]:
    response = http.client.HTTPResponse(connection)
    response.begin()
    try:
        return response.status, json.loads(response.read())
    finally:
        response.close()


def verify_capacity() -> None:
    port = PORTS[0]
    with ExitStack() as stack:
        held = [hold_upload(port, stack) for _ in range(16)]
        for _ in range(50):
            metrics = request(port, "/metrics/operations")[2]
            if metrics["active_writes"] == 16:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("Default write capacity was not reached")
        with ThreadPoolExecutor(max_workers=8) as pool:
            excess = list(pool.map(lambda i: request(port, "/predict", post=True, identity=i + 1), range(8)))
        assert all(status == 503 and body["error"]["code"] == "service_busy" for status, _, body in excess)
        assert request(port, "/health")[0] == 200
        for connection in held:
            connection.sendall(BODY[1:])
        assert all(read_upload(connection)[0] == 200 for connection in held)
    metrics = request(port, "/metrics/operations")[2]
    assert metrics["active_writes"] == 0
    assert metrics["peak_active_writes"] == 16
    assert metrics["outcomes"]["service_busy"] == 8
    print("container-capacity: default 16 admitted, 8 overload rejections, liveness and drainage passed")

    started = time.monotonic()
    with ExitStack() as stack:
        connection = hold_upload(port, stack)
        status, body = read_upload(connection)
    elapsed = time.monotonic() - started
    assert status == 408 and body["error"]["code"] == "request_timeout"
    assert 9.0 <= elapsed <= 15.0
    print(f"container-capacity: default upload deadline observed at {elapsed:.2f}s")


def verify_shared_budget() -> None:
    # 17 requests have consumed the first worker's shared client budget.
    # Eight excess writes were rejected before contacting Redis.
    started = time.monotonic()

    def check(index: int):
        port = PORTS[index % 2]
        path = "/predict" if index % 3 else "/v1/predict"
        return request(port, path, post=True, identity=index + 1)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, range(51)))
    counts = Counter(status for status, _, _ in results)
    assert counts == {200: 43, 429: 8}, counts
    assert all(body["error"]["code"] == "rate_limited" for status, _, body in results if status == 429)
    print(f"container-capacity: two API processes shared 60 admissions in {time.monotonic() - started:.2f}s")


def verify_restart() -> None:
    name = "smsd-ci-redis-restart"
    subprocess.run(["docker", "stop", "--time", "5", name], check=True, timeout=15)
    for port in PORTS:
        assert request(port, "/health")[0] == 200
        assert request(port, "/ready")[2]["error"]["code"] == "rate_limiter_unavailable"
        status, _, body = request(port, "/predict", post=True)
        assert status == 503 and body["error"]["code"] == "rate_limiter_unavailable"
    subprocess.run(["docker", "start", name], check=True, timeout=15)
    for port in PORTS:
        wait_ready(port)
        assert request(port, "/predict", post=True)[0] == 429
    print("container-capacity: durable disposable Redis restart retained the live shared budget")


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("This integration is restricted to the isolated GitHub Actions job")
    for port in PORTS:
        wait_ready(port)
    verify_capacity()
    verify_shared_budget()
    verify_restart()


if __name__ == "__main__":
    main()
