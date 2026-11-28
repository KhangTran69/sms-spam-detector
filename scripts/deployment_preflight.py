"""Offline configuration review for a proposed gateway-backed deployment.

This checks an operator-supplied environment, not a deployed gateway. It does
not connect to endpoints, inspect credentials, launch services, or grant
authorization to expose a local-only project.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections.abc import Mapping
from urllib.parse import urlsplit


def review(env: Mapping[str, str], *, workers: int, gateway_confirmed: bool) -> list[str]:
    findings = []
    if env.get("SMSD_ENV", "").strip().lower() != "production":
        findings.append("production_mode_required")
    for flag, finding in (
        ("SMSD_DONATIONS_ENABLED", "donations_must_be_disabled"),
        ("SMSD_FEEDBACK_ENABLED", "feedback_must_be_disabled"),
        ("SMSD_ALLOW_LEGACY_MODEL", "legacy_model_override_forbidden"),
    ):
        if env.get(flag, "").strip().lower() not in {"", "0", "false", "no"}:
            findings.append(finding)
    if not re.fullmatch(r"[a-fA-F0-9]{64}", env.get("SMSD_MODEL_SHA256", "")):
        findings.append("independent_model_digest_required")
    token = env.get("SMSD_METRICS_TOKEN", "")
    if len(token) < 32 or not token.isascii() or any(char.isspace() for char in token):
        findings.append("operator_metrics_token_required")
    if workers < 1:
        findings.append("invalid_worker_count")
    try:
        redis = urlsplit(env.get("SMSD_REDIS_URL", ""))
        if redis.scheme not in {"redis", "rediss"} or not redis.hostname or redis.port == 0 or redis.fragment:
            findings.append("shared_rate_limiter_required")
    except ValueError:
        findings.append("shared_rate_limiter_required")
    if env.get("SMSD_RATE_LIMIT_FAILURE_MODE", "closed").strip().lower() != "closed":
        findings.append("fail_closed_rate_limiting_required")
    if not gateway_confirmed:
        findings.append("gateway_attestation_required")
    for name, default in (("SMSD_MAX_IN_FLIGHT_WRITES", "16"), ("SMSD_RATE_LIMIT_PER_MINUTE", "60")):
        try:
            if int(env.get(name, default)) <= 0:
                raise ValueError
        except ValueError:
            findings.append("invalid_" + name.lower())
    try:
        deadline = float(env.get("SMSD_BODY_TIMEOUT_SECONDS", "10"))
        if not math.isfinite(deadline) or deadline <= 0:
            raise ValueError
    except ValueError:
        findings.append("invalid_body_deadline")
    for value in filter(None, (part.strip() for part in env.get("SMSD_CORS_ORIGINS", "").split(","))):
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.port == 0
                or "*" in value
                or any(char.isspace() for char in value)
            ):
                raise ValueError
        except ValueError:
            findings.append("invalid_public_cors_origin")
            break
    return sorted(set(findings))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument(
        "--gateway-confirmed",
        action="store_true",
        help="Operator attests TLS, per-client limits, no access-body logs, direct-peer identity and isolated origin.",
    )
    args = parser.parse_args(argv)
    findings = review(os.environ, workers=args.workers, gateway_confirmed=args.gateway_confirmed)
    print(json.dumps({"configuration_findings": findings, "gateway_verified": False, "deployment_authorized": False}))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
