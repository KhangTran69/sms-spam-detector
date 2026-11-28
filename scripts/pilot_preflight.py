"""Dry-run the donation intake flow end-to-end with synthetic fixtures only.

``make pilot-preflight`` starts the API in-process (TestClient, no socket, no
model artifact) and exercises the real donation handlers: gating by
``SMSD_DONATIONS_ENABLED`` / ``SMSD_DONATIONS_OPERATOR_CONTACT`` plus the
local-request restriction, the explicit-consent gate, PII rejection, intake,
withdrawal, and message-free logging. Every message in the run is a generated
fixture, the temporary donation database is deleted afterwards, and the JSON
report contains check names, outcomes, and timings only -- never message text
or PII patterns. This dry run is not an accuracy, release-readiness, or
safety assessment.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import api.main as api_main
from api.donations import donation_summary
from src.privacy.scrub import detect_pii
from src.privacy.storage import ensure_private_directory

ROOT = Path(__file__).resolve().parents[1]

# The rehearsal runs the enabled donation flow with a synthetic operator
# contact on a reserved TLD. Direct invocations may override it with
# --operator-contact or SMSD_DONATIONS_OPERATOR_CONTACT.
DEFAULT_OPERATOR_CONTACT = "pilot-preflight@example.test"
PREFLIGHT_ENVIRONMENT = "development"
PREFLIGHT_DONATION_RATE_LIMIT = 60
TRUTHY_FLAGS = {"1", "true", "yes"}

# Synthetic fixtures only: reserved example domains and placeholder tokens in
# the style of the tracked test fixtures. Nothing here is real message data.
PII_FIXTURE_MESSAGE = "Synthetic preflight fixture: reply to pilot-preflight@example.com or call 09171234567."
DONATION_FIXTURE_MESSAGE = "Synthetic preflight fixture: review template [CODE] with placeholder [AMOUNT] only."
FIXTURE_MESSAGES = (PII_FIXTURE_MESSAGE, DONATION_FIXTURE_MESSAGE)
PII_FIXTURE_VALUES = ("09171234567", "pilot-preflight@example.com")
FORBIDDEN_REPORT_STRINGS = FIXTURE_MESSAGES + PII_FIXTURE_VALUES

# Server-generated request ids are random hex, not personal data. They are
# removed before pattern scanning so an accidental long digit run inside a
# random id cannot produce a false positive.
REQUEST_ID_RE = re.compile(r"\b[0-9a-f]{32}\b")
RECORD_ID_RE = re.compile(r"[0-9a-f]{32}")


def _donations_enabled_from_environment() -> bool:
    """Mirror api.main's flag parsing; unset defaults to rehearsing the enabled flow."""
    raw = os.environ.get("SMSD_DONATIONS_ENABLED", "").strip().lower()
    if not raw:
        return True
    return raw in TRUTHY_FLAGS


def _operator_contact(explicit: str | None) -> str:
    if explicit is not None:
        return explicit
    from_environment = os.environ.get("SMSD_DONATIONS_OPERATOR_CONTACT", "").strip()
    return from_environment or DEFAULT_OPERATOR_CONTACT


def _content_violations(lines: Iterable[str], forbidden: tuple[str, ...]) -> int:
    """Count lines that carry fixture text or PII patterns; never return the content."""
    violations = 0
    for line in lines:
        if any(item in line for item in forbidden):
            violations += 1
            continue
        if detect_pii(REQUEST_ID_RE.sub("", line), strict=True):
            violations += 1
    return violations


def _validate_output_path(output: str | os.PathLike[str]) -> Path:
    destination = Path(output).expanduser().resolve()
    repository = ROOT.resolve()
    private_root = (repository / "data" / "donations").resolve()
    if repository in destination.parents and private_root not in destination.parents:
        raise ValueError("Preflight reports must be outside the repository or under ignored data/donations/ storage.")
    return destination


def write_report(report: dict[str, Any], output: str | os.PathLike[str]) -> Path:
    """Write the message-free report outside the repository or under data/donations/."""
    destination = _validate_output_path(output)
    payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if _content_violations([payload], FORBIDDEN_REPORT_STRINGS):
        raise ValueError("Refusing to write a preflight report that contains message text or PII patterns.")
    ensure_private_directory(destination.parent)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(destination, 0o600)
    return destination


@contextmanager
def _captured_logs() -> Iterator[list[str]]:
    """Collect formatted log lines from every logger without persisting them.

    The HTTP client transport loggers are quieted for the duration of the run:
    their lines carry only the in-process ``testserver`` URL of the TestClient,
    not service log output, and their URL pattern would otherwise trip the
    message-free scan.
    """
    lines: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                lines.append(record.getMessage())
            except Exception:  # pragma: no cover - defensive only
                lines.append("<unformattable log record>")

    collector = _Collector(level=logging.DEBUG)
    root = logging.getLogger()
    api_logger = logging.getLogger("api.main")
    previous_root_level = root.level
    previous_api_level = api_logger.level
    transport_loggers = [(name, logging.getLogger(name).level) for name in ("httpx", "httpcore")]
    root.addHandler(collector)
    root.setLevel(logging.DEBUG)
    api_logger.setLevel(logging.DEBUG)
    for name, _level in transport_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        yield lines
    finally:
        root.removeHandler(collector)
        root.setLevel(previous_root_level)
        api_logger.setLevel(previous_api_level)
        for name, level in transport_loggers:
            logging.getLogger(name).setLevel(level)


@contextmanager
def _patched_donation_state(*, enabled: bool, contact: str, database: Path) -> Iterator[None]:
    """Point the in-process app at a disposable synthetic database and config.

    ``DONATION_NOTICE_VERSION`` is intentionally untouched: the run only reads it.
    """
    original = {
        "enabled": api_main.DONATIONS_ENABLED,
        "contact": api_main.DONATIONS_OPERATOR_CONTACT,
        "database": api_main.DONATION_DB_PATH,
        "limit": api_main.DONATION_RATE_LIMIT_PER_MINUTE,
        "environment": api_main.SMSD_ENV,
    }
    api_main.DONATIONS_ENABLED = bool(enabled)
    api_main.DONATIONS_OPERATOR_CONTACT = contact
    api_main.DONATION_DB_PATH = database
    api_main.DONATION_RATE_LIMIT_PER_MINUTE = PREFLIGHT_DONATION_RATE_LIMIT
    api_main.SMSD_ENV = PREFLIGHT_ENVIRONMENT
    try:
        yield
    finally:
        api_main.DONATIONS_ENABLED = original["enabled"]
        api_main.DONATIONS_OPERATOR_CONTACT = original["contact"]
        api_main.DONATION_DB_PATH = original["database"]
        api_main.DONATION_RATE_LIMIT_PER_MINUTE = original["limit"]
        api_main.SMSD_ENV = original["environment"]
        api_main._reset_rate_limits()


@contextmanager
def _donation_client(host: str, *, enabled: bool, contact: str) -> Iterator[Any]:
    """Yield an in-process client; ``host`` selects the local-only gate branch."""
    original_enabled = api_main.DONATIONS_ENABLED
    original_contact = api_main.DONATIONS_OPERATOR_CONTACT
    api_main.DONATIONS_ENABLED = bool(enabled)
    api_main.DONATIONS_OPERATOR_CONTACT = contact
    api_main._reset_rate_limits()
    try:
        with TestClient(api_main.app, base_url="http://127.0.0.1:8000", client=(host, 12345)) as client:
            yield client
    finally:
        api_main.DONATIONS_ENABLED = original_enabled
        api_main.DONATIONS_OPERATOR_CONTACT = original_contact
        api_main._reset_rate_limits()


def _local_client(*, enabled: bool, contact: str) -> Iterator[Any]:
    return _donation_client("127.0.0.1", enabled=enabled, contact=contact)


def _remote_client(*, enabled: bool, contact: str) -> Iterator[Any]:
    return _donation_client("203.0.113.20", enabled=enabled, contact=contact)


@contextmanager
def _check(checks: list[dict[str, Any]], name: str) -> Iterator[Callable[[bool, str], None]]:
    """Run one check, timing it and reducing any exception to a type name only."""
    entry: dict[str, Any] = {"name": name, "passed": False, "detail": "check_did_not_complete", "duration_ms": 0.0}
    started = time.perf_counter()

    def done(passed: bool, detail: str) -> None:
        entry["passed"] = bool(passed)
        entry["detail"] = detail

    try:
        yield done
    except Exception as exc:
        done(False, f"unexpected_{type(exc).__name__}")
    finally:
        entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        checks.append(entry)


def _donation_payload() -> dict[str, Any]:
    return {
        "message": DONATION_FIXTURE_MESSAGE,
        "label_hint": "spam",
        "language": "en",
        "consent": True,
        "authorized_to_share": True,
        "model_research_consent": False,
        "notice_version": api_main.DONATION_NOTICE_VERSION,
    }


def _error_code(response: Any) -> str:
    try:
        body = response.json()
    except ValueError:
        return "unparsable_body"
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("code", "missing_code"))
    return "no_error_object"


def _error_categories(response: Any) -> set[str]:
    try:
        body = response.json()
    except ValueError:
        return set()
    error = body.get("error") if isinstance(body, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    if not isinstance(details, list):
        return set()
    return {str(detail.get("category")) for detail in details if isinstance(detail, dict)}


def _run_gating_checks(checks: list[dict[str, Any]], contact: str, enabled: bool, database: Path) -> None:
    with (
        _check(checks, "donation_page_and_intake_gated_when_disabled") as done,
        _local_client(enabled=False, contact=contact) as gated,
    ):
        form = gated.get("/donate")
        intake = gated.post("/donate", json=_donation_payload())
        done(
            form.status_code == 404 and intake.status_code == 404 and not database.exists(),
            f"form_http_{form.status_code}_intake_http_{intake.status_code}",
        )
    with (
        _check(checks, "donation_page_gated_without_operator_contact") as done,
        _local_client(enabled=True, contact="") as uncontacted,
    ):
        response = uncontacted.get("/donate")
        done(response.status_code == 404, f"http_{response.status_code}")
    with (
        _check(checks, "donation_page_rejects_remote_clients") as done,
        _remote_client(enabled=enabled, contact=contact) as remote,
    ):
        response = remote.get("/donate")
        done(response.status_code == 404, f"http_{response.status_code}")


def _run_flow_checks(checks: list[dict[str, Any]], client: Any, database: Path, state: dict[str, Any]) -> None:
    with _check(checks, "donation_page_available_locally_when_enabled") as done:
        response = client.get("/donate")
        done(response.status_code == 200, f"http_{response.status_code}")

    with _check(checks, "consent_gate_requires_explicit_opt_in") as done:
        response = client.post("/donate", json={**_donation_payload(), "consent": False})
        code = _error_code(response)
        records = donation_summary(database)["records"]
        done(
            response.status_code == 400 and code == "consent_required" and records == 0,
            f"http_{response.status_code}_code_{code}_records_{records}",
        )

    with _check(checks, "pii_intake_rejection_enforced") as done:
        response = client.post("/donate", json={**_donation_payload(), "message": PII_FIXTURE_MESSAGE})
        code = _error_code(response)
        records = donation_summary(database)["records"]
        categories = _error_categories(response)
        done(
            response.status_code == 422
            and code == "pii_detected"
            and {"email", "phone"} <= categories
            and records == 0,
            f"http_{response.status_code}_code_{code}_records_{records}",
        )

    with _check(checks, "donation_intake_accepts_consented_synthetic_record") as done:
        response = client.post("/donate", json=_donation_payload())
        body = response.json() if response.status_code == 201 else {}
        record_id = str(body.get("record_id", ""))
        state["record_id"] = record_id
        done(
            response.status_code == 201
            and body.get("status") == "received"
            and RECORD_ID_RE.fullmatch(record_id) is not None
            and body.get("notice_version") == api_main.DONATION_NOTICE_VERSION,
            f"http_{response.status_code}",
        )

    with _check(checks, "withdrawal_erases_the_synthetic_record") as done:
        record_id = str(state.get("record_id", ""))
        if RECORD_ID_RE.fullmatch(record_id):
            response = client.request("DELETE", "/donate", json={"record_id": record_id})
            summary = donation_summary(database)
            done(
                response.status_code == 200
                and response.json() == {"status": "withdrawn"}
                and summary == {"records": 1, "withdrawn": 1, "active": 0},
                f"http_{response.status_code}_records_{summary['records']}_active_{summary['active']}",
            )
        else:
            done(False, "not_run_without_accepted_record")


def _run_log_check(checks: list[dict[str, Any]], log_lines: list[str], state: dict[str, Any]) -> None:
    with _check(checks, "run_logs_are_message_free") as done:
        forbidden = FORBIDDEN_REPORT_STRINGS
        record_id = str(state.get("record_id", ""))
        if RECORD_ID_RE.fullmatch(record_id):
            forbidden = forbidden + (record_id,)
        violations = _content_violations(log_lines, forbidden)
        message_free = bool(log_lines) and violations == 0
        state["logs_captured"] = len(log_lines)
        state["logs_message_free"] = message_free
        done(message_free, f"lines_{len(log_lines)}_violations_{violations}")


def run_preflight(*, donations_enabled: bool | None = None, operator_contact: str | None = None) -> dict[str, Any]:
    """Exercise the donation flow with synthetic fixtures and return a message-free report."""
    enabled = _donations_enabled_from_environment() if donations_enabled is None else bool(donations_enabled)
    contact = _operator_contact(operator_contact)
    checks: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    run_started = time.perf_counter()

    with _captured_logs() as log_lines, tempfile.TemporaryDirectory(prefix="smsd-pilot-preflight-") as workspace:
        database = Path(workspace) / "donations.sqlite3"
        with _patched_donation_state(enabled=enabled, contact=contact, database=database):
            _run_gating_checks(checks, contact, enabled, database)
            with _local_client(enabled=enabled, contact=contact) as client:
                _run_flow_checks(checks, client, database, state)
            _run_log_check(checks, log_lines, state)
    workspace_removed = not Path(workspace).exists()

    return {
        "status": "passed" if all(entry["passed"] for entry in checks) and workspace_removed else "failed",
        "fixture_class": "synthetic",
        "environment": {
            "donations_enabled": enabled,
            "operator_contact_configured": bool(contact.strip()),
            "smsd_env": PREFLIGHT_ENVIRONMENT,
        },
        "checks": checks,
        "logs": {
            "records_captured": int(state.get("logs_captured", 0)),
            "message_free": bool(state.get("logs_message_free", False)),
        },
        "timings": {
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "total_ms": round((time.perf_counter() - run_started) * 1000, 2),
        },
        "cleanup": {"temporary_workspace_removed": workspace_removed},
        "limitations": [
            "Every message in this dry run is a generated synthetic fixture.",
            "The report lists which checks passed; it is not an accuracy, release-readiness, or safety assessment.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run the donation intake flow end-to-end with synthetic fixtures only."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="JSON destination outside the repository or under ignored data/donations/ storage.",
    )
    parser.add_argument(
        "--operator-contact",
        default=None,
        help="Synthetic operator contact to rehearse with (defaults to the built-in fixture contact).",
    )
    args = parser.parse_args(argv)
    try:
        report = run_preflight(operator_contact=args.operator_contact)
        destination = write_report(report, args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    except Exception as exc:
        # Keep unexpected failures content-free: only the exception type name.
        print(f"Pilot preflight aborted with an unexpected error ({type(exc).__name__}).", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    print(f"Report written to {destination}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
