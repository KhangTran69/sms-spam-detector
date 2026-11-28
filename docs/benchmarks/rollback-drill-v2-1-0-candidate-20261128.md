# Timed rollback drill #2 — candidate artifact vs v2.0.0 immutable copies (2026-11-28)

Message-free operational record: no SMS content is quoted here. This drill
exercised the rollback procedure from [RETRAINING.md §7](../RETRAINING.md#7-rollback-procedure)
against the local service on port 8001 — re-pointing `SMSD_MODEL_PATH`,
restarting, and verifying `/ready` and `/model-info` — between the
v2.1.0-candidate artifact and the immutable v2.0.0 release copies under
`models/releases/v2.0.0/` (sha256-verified against the release sidecar and
`gh attestation verify` in the v2.0.0 flow). It is a rehearsal on a
development machine, not a production rollback, and establishes no accuracy
or performance claim.

## Artifacts involved

| Direction | Artifact | `model_version` reported |
|---|---|---|
| 1 (candidate up) | `models/spam_detector_v2_1_candidate.pkl` | `spam_detector_v1-2026-11-28-v2.1.0-candidate` |
| 2 (rollback) | `models/releases/v2.0.0/spam_detector_v1.pkl` | `spam_detector_v1-2026-11-28` |

The candidate is the gates-not-met artifact from
[v2-1-0-gates-not-met-20261128.md](v2-1-0-gates-not-met-20261128.md) — it was
**not released**, and this drill changes nothing about that decision.

## Measured durations

| Direction | Duration | `GET /ready` | `GET /model-info` `model_version` |
|---|---:|---|---|
| 1. Serve the candidate (`SMSD_MODEL_PATH=models/spam_detector_v2_1_candidate.pkl`, service start → verified) | **2.725 s** | `ready` | `spam_detector_v1-2026-11-28-v2.1.0-candidate` |
| 2. Roll back to the v2.0.0 immutable copy (`SMSD_MODEL_PATH=models/releases/v2.0.0/spam_detector_v1.pkl`, service restart → verified) | **2.444 s** | `ready` | `spam_detector_v1-2026-11-28` |
| Whole drill (start of direction 1 through direction 2 verification, including the 0.142 s teardown gap) | 5.311 s | — | — |

Timing method: wall-clock `time.time()` (6 decimal places) at four points —
drill start `t0`, direction-1 verification complete `t1`, direction-2 restart
start `t2`, direction-2 verification complete `t3`. Readiness was polled with
`curl /ready` every 0.2 s, so each duration includes process start, artifact
load + sidecar digest verification, readiness, and the verification requests;
the 0.2 s poll interval is the measurement granularity. The first
[rollback drill](release-drill-20261128.md) measured 3.250 s / 2.801 s /
6.279 s total for the demo→canonical pair; both drills are of the same order.

## Reading

Rolling back from the new candidate to the attested v2.0.0 copies takes about
2.4 seconds on this machine — the same order as the v2.0.0 drill. The
`models/releases/v2.0.0/` copies behave exactly like the attested release
bytes (version string and digest verification included). No release or
promotion decision is implied by this drill.
