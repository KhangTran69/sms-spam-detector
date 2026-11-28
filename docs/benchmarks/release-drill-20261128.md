# Timed rollback drill — 2026-11-28

Message-free operational record: no SMS content is quoted here. This drill
exercised the rollback procedure from [RETRAINING.md §7](../RETRAINING.md#7-rollback-procedure)
against the local service — re-pointing `SMSD_MODEL_PATH`, restarting, and
verifying `/ready` and `/model-info` — and measured the wall-clock time of
each direction. It is a rehearsal on a development machine, not a production
rollback, and it establishes no accuracy or performance claim.

## Release context

The drill followed the attested canonical release:

- Release: <https://github.com/KhangTran69/sms-spam-detector/releases/tag/v2.0.0>
  (tag `v2.0.0` at source revision `deedcb863a7d28352c31899963623a52cd4dd25d`),
  published 2026-11-28 with exactly `models/spam_detector_v1.pkl` +
  `models/spam_detector_v1.metadata.json` attached.
- Release-provenance workflow run (passed):
  <https://github.com/KhangTran69/sms-spam-detector/actions/runs/46125116202>.
  Its SLSA provenance attestation names `spam_detector_v1.pkl` at
  `sha256:daa8a7c192bf9e02a068f5c60b15bec1cba0db6522b4bf68d69b5b9633815daf`,
  which equals the sidecar's `artifact_sha256`;
  `gh attestation verify models/spam_detector_v1.pkl` exited 0 against the
  local bytes.
- Canonical artifact: `models/spam_detector_v1.pkl`, `model_version`
  `spam_detector_v1-2026-11-28` (the `v2.0.0` release asset).
- Previous known-good baseline: `models/demo_synthetic.pkl`, `model_version`
  `synthetic-demo` (the tracked-demo artifact produced by `make demo`; its
  sidecar `demo_synthetic.metadata.json` was copied byte-identical from the
  operator's main checkout into this worktree's ignored `models/`).

The drill service ran on port 8001 because the operator's live local server
was already serving on port 8000; the 8000 server was not stopped or touched.

## Measured durations

| Direction | Duration | `GET /ready` | `GET /model-info` `model_version` |
|---|---:|---|---|
| 1. Roll back to previous known-good (`SMSD_MODEL_PATH=models/demo_synthetic.pkl`, service start → verified) | **3.250 s** | `ready` | `synthetic-demo` |
| 2. Restore canonical (`SMSD_MODEL_PATH=models/spam_detector_v1.pkl`, service restart → verified) | **2.801 s** | `ready` | `spam_detector_v1-2026-11-28` |
| Whole drill (start of direction 1 through direction 2 verification, including the 0.228 s teardown gap) | 6.279 s | — | — |

Timing method: wall-clock timestamps (`time.time()`, 6 decimal places) taken
at four points — drill start `t0` (2026-11-28T08:20:09.400846Z), direction-1
verification complete `t1`, direction-2 restart start `t2`, direction-2
verification complete `t3` (2026-11-28T08:20:15.679377Z). Direction 1 = `t1-t0`,
direction 2 = `t3-t2`, total = `t3-t0`. Readiness was polled with
`curl /ready` every 0.2 s, so each duration includes process start, artifact
load + digest verification, readiness, and the verification requests; the 0.2 s
poll interval is the measurement granularity.

## Commands

Run as one script from the repository root of the `chore/roadmap-t0-hygiene`
worktree (`/Users/khangtran/smsd-worktrees/roadmap-completion`):

```sh
#!/bin/zsh
# Timed rollback drill 2026-11-28 — port 8001 (8000 is the operator's live server).
set -u
cd /Users/khangtran/smsd-worktrees/roadmap-completion || exit 1
PY=/Users/khangtran/Documents/sms-spam-detector/.venv/bin/python
now() { $PY -I -c 'import time; print(f"{time.time():.6f}")'; }
BASE=http://127.0.0.1:8001

T0=$(now)

# --- Direction 1: previous known-good (demo) artifact ---
export SMSD_MODEL_PATH=models/demo_synthetic.pkl
$PY -m api.cli --host 127.0.0.1 --port 8001 >/tmp/drill-serve-demo.log 2>&1 &
PID=$!
until curl -sf "$BASE/ready" >/dev/null 2>&1; do sleep 0.2; done
READY1=$($PY -I -c "import json,urllib.request; print(json.load(urllib.request.urlopen('$BASE/ready'))['status'])")
MODEL1=$($PY -I -c "import json,urllib.request; print(json.load(urllib.request.urlopen('$BASE/model-info'))['model_version'])")
T1=$(now)
kill "$PID" 2>/dev/null
wait "$PID" 2>/dev/null

T2=$(now)

# --- Direction 2: canonical artifact ---
export SMSD_MODEL_PATH=models/spam_detector_v1.pkl
$PY -m api.cli --host 127.0.0.1 --port 8001 >/tmp/drill-serve-canonical.log 2>&1 &
PID=$!
until curl -sf "$BASE/ready" >/dev/null 2>&1; do sleep 0.2; done
READY2=$($PY -I -c "import json,urllib.request; print(json.load(urllib.request.urlopen('$BASE/ready'))['status'])")
MODEL2=$($PY -I -c "import json,urllib.request; print(json.load(urllib.request.urlopen('$BASE/model-info'))['model_version'])")
T3=$(now)
kill "$PID" 2>/dev/null
wait "$PID" 2>/dev/null

$PY -I - "$T0" "$T1" "$T2" "$T3" "$READY1" "$MODEL1" "$READY2" "$MODEL2" <<'EOF'
import sys
t0, t1, t2, t3, r1, m1, r2, m2 = sys.argv[1:9]
f = lambda x: float(x)
print(f"drill_start_t0={t0}")
print(f"demo_verified_t1={t1}  direction1_seconds={f(t1)-f(t0):.3f}  ready1={r1}  model1={m1}")
print(f"canonical_restart_t2={t2}  switch_gap_seconds={f(t2)-f(t1):.3f}")
print(f"canonical_verified_t3={t3}  direction2_seconds={f(t3)-f(t2):.3f}  ready2={r2}  model2={m2}")
print(f"total_drill_seconds={f(t3)-f(t0):.3f}")
EOF
```

Script output (verbatim):

```
drill_start_t0=1795854009.400846
demo_verified_t1=1795854012.650449  direction1_seconds=3.250  ready1=ready  model1=synthetic-demo
canonical_restart_t2=1795854012.878008  switch_gap_seconds=0.228
canonical_verified_t3=1795854015.679377  direction2_seconds=2.801  ready2=ready  model2=spam_detector_v1-2026-11-28
total_drill_seconds=6.279
```

Both service processes exited cleanly after verification (uvicorn shutdown
logged, no errors in either service log); port 8001 was released at the end.

## Verification after the drill

`make doctor` ran immediately after the drill. The drill-relevant check
passed:

```
OK    served-model: server reports 'synthetic-demo', which has a metadata sidecar in models/
```

This check queries the operator's pre-existing server on port 8000 (which
serves the `synthetic-demo` artifact) against the sidecars present in
`models/`; the drill service itself ran on 8001 and served both artifacts as
recorded above. The same doctor run reports one failure unrelated to this
drill: the `plan-archive` check, because this branch still tracks
`docs/superpowers/` (the in-progress plan and spec, committed in `ca8f938`);
doctor expects executed plans under `docs/history/`. That relocation is not
part of this drill.

## Standing caveats

Durations are from one local run on the operator's machine (Apple silicon,
CPython 3.13.3, uvicorn started without `--reload`) and are not reproducibility
or performance guarantees. The drill verified artifact re-pointing, digest
verification at load, and readiness reporting only — it did not test data
restoration, container redeployment, or proxy failover, and it says nothing
about model quality: a served artifact's scores remain assistive and are not a
probability that a message is a scam.
