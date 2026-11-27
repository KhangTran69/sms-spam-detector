# Operational and accessibility release review

**Status:** documented verification plan, not a claim of a production pilot or
manual accessibility approval. Engineering CI uses fictional data.

## Operator scope and threat model

Before public exposure, name the trusted TLS gateway, expected number of
workers, request rate and concurrency envelope, deployment host, recovery
owner, monitoring token custodian, incident contact, and retained model version.
The API uses the *direct peer address* and intentionally does not trust
user-controlled forwarding headers. Under a proxy all clients may share one
application-level identity: enforce per-client rate limits at the trusted
gateway. A process-local limiter is not adequate as a sole public multiworker
control.

Review the following in an approved non-public environment:

| Case | Expected safe behavior |
|---|---|
| Ordinary fictional SMS or batch | Valid request; no server-side message persistence |
| Repeated client request over configured limit | 429 and positive Retry-After; no content in logs |
| Missing, invalid and malformed JSON | 422/4xx safe schema with no SMS echo |
| Oversized declared or streamed input | 413; no unbounded buffering or text logging |
| Redis unavailable at production startup | /health liveness 200, /ready 503, prediction 503 |
| Redis outage after successful initialization | Safe 503 rate_limiter_unavailable; no backend secrets exposed |
| Redis disabled and multiple workers | Gateway handles shared per-client limits; no false shared-counter claim |
| Missing/incompatible model | /ready 503; UI describes unavailable analysis without fake result |
| Unauthorized operational metrics in production | 404 even for guessed token; operator token access through TLS only |
| Reverse-proxy/application logs | No body, direct IP or arbitrary user-supplied path in application logs; proxy must independently suppress bodies |
| Browser API unreachable or slow | Clear retry state; no false offline claim when only API is unavailable |
| Rollback | Previous code+artifact version restores expected /ready and model-info metadata |

The process-local operations metrics expose only fixed low-cardinality route
groups, status classes, counts, and rolling latency. They are not aggregated
across instances or persisted. Operators should establish a baseline from the
target hardware before choosing alert thresholds, and compare model-drift
scores only when model/version/calibration and semantics match. Changes in
aggregate drift do not establish a change in real-world accuracy.

## Accessibility review

**Automated:** CI's browser behavior smoke test checks responsive layout,
keyboard tabs, focus visibility, touch target sizes and overflow; it now also
checks unique DOM IDs, visible field labels, a valid skip target and inline
script CSP. These are useful regressions, **not** complete WCAG conformance
or a manual screen-reader test.

**Manual review still required:** On a supported Mac run VoiceOver with Safari,
and where available test NVDA with Chrome/Firefox and TalkBack or VoiceOver on
a mobile handset. Verify the following on the **fictional fixture UI**, not
participant SMS:

- Navigate to main content by skip link; traverse all view tabs with
  arrows, Home/End and keyboard focus. Confirm selected state is announced.
- Check that message labels, field hints, privacy preview choices, result
  verdicts, risk-meter caveats, help text, and action controls have understandable
  accessible names and programmatic relationships in English and Taglish.
- Verify assertive error alerts and polite progress/readiness updates are
  announced once without repeatedly interrupting input; test offline,
  timeout, 429, 413, 422, and rate-limiter/model 503 presentations.
- Use 200% and 400% zoom, narrow landscape mobile, reduced-motion and
  high-contrast settings, dark theme, keyboard-only navigation and touch.
- Confirm consent/donation review screens, where separately enabled locally,
  are keyboard accessible and never encourage submitting private live codes.
- Record test device/browser/AT version, steps, expected/actual behavior,
  severity, owner, and retest evidence. Resolve critical barriers before any
  broader release. A qualified accessibility reviewer signs off separately.

**Human comprehension review** is a distinct, consented activity governed by
[HUMAN_REVIEW.md](HUMAN_REVIEW.md). No participant research is authorized by
these engineering tests.

## Recovery gates

Keep a previously verified compatible model artifact and metadata sidecar.
For deployment failures, disable gateway traffic, restore the previous image
and model artifact together, check /health, /ready and /model-info, and record
the incident. Never switch to a synthetic or unapproved model as an outage
fallback. Stop if any SMS content leaks into logs/telemetry or if critical
legitimate categories suffer unreviewed regressions.
