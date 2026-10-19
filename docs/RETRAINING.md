# Retraining, Monitoring, and Rollback

The model is only as current as its data and artifact. This runbook covers when
to retrain, which gates a new artifact must pass, how to version and deploy it,
what to monitor, and how to respond when something goes wrong.

> Current evidence is synthetic/UCI only. Real-world performance has not been
> measured; do not treat a green run as real-world validation. See
> [MODEL_CARD.md](MODEL_CARD.md).

## 1. Retraining cadence and triggers

**Scheduled:** at least monthly while the service is actively used, even if no
errors are reported — scam templates rotate. Also retrain after any dependency
upgrade that changes scikit-learn/pandas numeric behavior.

**Trigger-based (retrain sooner):**

- New scam campaign reported by users or surfaced in error analysis.
- False-positive cluster on legitimate messages (bank alerts, OTPs, delivery,
  promos) — this is the highest-priority trigger.
- Evaluation/metric drift beyond threshold (see §6).
- A material data change: new supplement/holdout, corrected labels, withdrawal of
  consented data.
- Artifact/API contract change (schema version bump) or Python/dependency major
  upgrade.
- Security/privacy incident involving data or artifact provenance.

**Do not** retrain on unlabeled or unmasked production messages. New data goes
through [DATA_COLLECTION.md](DATA_COLLECTION.md) first.

## 2. Data refresh and validation gates

1. **Freeze the current artifact and split metadata** (version, data hashes) for
   reproducibility.
2. Add/replace data in a staging copy. Mask, label, group by template family /
   campaign, and record provenance.
3. Run the **data gate** before training:
   - required columns, labels map to `ham`/`spam`, both classes present;
   - no blank messages, no duplicate messages after merge;
   - supplement and holdout(s) remain disjoint (the test suite enforces this);
   - the three diagnostic brief examples remain absent from all data files;
   - runtime feature schema matches what the model expects;
   - class balance and per-category counts are recorded; large shifts are
     justified (not silently accepted);
   - group labels exist for every row; no group straddles splits.
4. Freeze the **validation split** and **holdout** before touching thresholds.
5. Train with a fixed seed and record the exact command, dependency versions
   (see `constraints.txt`), data hashes, and artifact version.

If any gate fails, stop. Do not hand-tune the split until metrics improve.

## 3. Validation gates for a candidate artifact

A candidate may be promoted only if **all** hold:

- [ ] Training/evaluation complete with recorded seed, config, data hashes, and
      code revision.
- [ ] Leakage checks pass: no exact-duplicate, template-family, donor, or
      supplement/holdout overlap between train/validation/holdout.
- [ ] Held-out threshold sweep shows the selected precision-first operating point;
      the `decision_threshold` stored in the bundle matches what `predict`, the
      API, and the UI use (one source of truth in the artifact).
- [ ] The synthetic Philippine holdout is reported **separately** and labeled
      synthetic-only; no claim of real-world performance.
- [ ] Calibration diagnostics are within the agreed tolerance (or the limitation
      is documented and user-facing copy avoids precise probabilities).
- [ ] Critical legitimate-message categories (OTP, bank transaction alerts,
      delivery, personal Taglish) are checked for false positives; any regression
      vs. the incumbent artifact is flagged and released only with explicit
      sign-off.
- [ ] Failed candidate examples are reviewed and categorized.
- [ ] Artifact loads under the target Python/dependency runtime; `/ready`
      returns 200 with the new artifact.
- [ ] README metrics and the artifact sidecar metadata are updated together.
- [ ] PR review by someone other than the author; privacy check (no message
      bodies, no PII, no secrets in the diff).

Prefer a **shadow/canary** run (log-only or a small traffic slice) before a full
switch when real users are involved. Never A/B test by showing scam warnings to
a subset without review.

## 4. Artifact versioning and reproducibility

- The artifact is a joblib bundle containing: schema version, fitted pipeline,
  decision threshold, suspicious threshold, label mapping, training config,
  data-source hashes, version/timestamp, and metrics. A human-readable
  `models/spam_detector_v1.metadata.json` sidecar is written next to it.
- **Immutable releases:** store each promoted bundle as
  `models/releases/smsd-<version>.pkl` plus its sidecar, never overwrite a
  released artifact. Include the code revision and dependency lock in the
  release notes.
- Version scheme: `MAJOR.MINOR.PATCH` or date-based, recorded in
  `model_version`. Bump schema version when the bundle layout or feature schema
  changes; the API refuses an incompatible artifact (`/ready` → 503).
- Reproducibility: fixed `random_state`/seed, stratified + grouped splits,
  deterministic ordering before dedupe/splits, recorded data hashes. A rerun on
  the same inputs/versions must produce the same metrics (document any
  nondeterminism, e.g. BLAS/thread scheduling).
- Keep the **previous known-good** artifact mounted or readily available for
  rollback (§7).

## 5. Evaluation on a separate holdout

- Train/validation/holdout are disjoint by row **and** by group (template
  family, campaign, donor). A random row split is not sufficient for
  generalization claims.
- Use validation to choose thresholds and hyperparameters; touch the holdout
  once per candidate. Do not iterate against the holdout.
- Report separately and clearly: base+supplement split metrics, synthetic PH
  holdout metrics (labeled synthetic), and — once it exists — real PH holdout
  metrics with sample sizes and per-category breakdowns.
- For the real holdout (future): keep it private, refresh only through the
  consent workflow, and never mix it into synthetic reporting.
- Reference numbers live in the README; do not copy them into other docs without
  the artifact version and a date.

## 6. Monitoring (once deployed)

Instrument the **service**, not the messages. Logs must not contain message text
(see [PRIVACY.md](PRIVACY.md)).

| Metric | Why | Example alert |
|---|---|---|
| Request volume | Traffic baseline; detect abuse/outage | 5xx rate > 1% or volume drop/ spike > 3× baseline |
| Latency (p50/p95) | UX and capacity | p95 > 1 s (local) |
| Error rate | Artifact/validation/API issues | 503/500 rate > 0.5% for 10 min |
| `/ready` status | Artifact availability | Not ready > 2 min |
| Verdict distribution (spam rate) | Drift indicator; no message content needed | spam rate shifts > 10 points week-over-week |
| **User-reported false positives** (opt-in feedback) | Costliest error | any cluster on the same legitimate category |
| False-negative reports / missed scams | Coverage gap | rising reports per 1,000 checks |
| Signal/flag rates (URL, phone, money, urgency, brand) | Feature drift | > 2× baseline on any flag |
| Threshold/margin distribution | Calibration drift | margin distribution shifts materially |
| Artifact version in use | Audit/rollback | unexpected version after deploy |
| Model load failures | Ops | any 503 `model_unavailable` |

The anonymous `/feedback` queue is disabled by default and stores only an
explicitly selected expected label, broad category, and model version. Treat
these as unverified triage counts, not labels or training data. Reviewers must
obtain consent and receive a separately redacted sample before adding any
message to a dataset; feedback never triggers automatic retraining.

Use `python -m src.feedback --path data/feedback/reports.jsonl` to print
aggregate correction/category/model-version counts. The summarizer rejects
unknown or free-text fields and omits report IDs and timestamps. For Docker
Compose, copy the report file from the `smsd_feedback` volume into an approved
secure review area before summarizing; never add it to the training corpus.

Drift evaluation:

- Compare weekly feature/label-proxy distributions against the training window;
  alert on material shift.
- Periodically sample **masked** real messages through the data workflow to
  measure precision/recall on real traffic; this is the only way to validate
  real-world performance. Until then, state clearly that it is unmeasured.
- Keep dashboards message-free. Aggregate counts only; no per-user tracking.

## 7. Rollback procedure

1. Identify the issue and current version from `GET /model-info`; record time,
   symptom, and impact.
2. Re-point `SMSD_MODEL_PATH` to the previous known-good immutable bundle (or
   redeploy the previous image tag/digest if code changed too). Restart/recreate
   the container.
3. Wait for `GET /ready` to return 200 and `/model-info` to report the expected
   `model_version`; verify a known-good sample message and `/health`.
4. Announce the rollback in the team channel and create an incident record.
5. Preserve the failed artifact and relevant (message-free) logs for root cause;
   do **not** delete them before the postmortem.
6. Postmortem: categorize (data/labeling, training, threshold, dependency,
   deployment), add a regression test/fixture, update gates, and only then plan a
   re-release.
7. If the incident involved PII exposure, follow the privacy incident path in
   [PRIVACY.md](PRIVACY.md) in addition to the model rollback.

## 8. Incident response

| Severity | Examples | Immediate action |
|---|---|---|
| Sev 1 | Service down; artifact unloadable; PII/secret exposure | Roll back/disable, notify owner, privacy/security process, preserve evidence |
| Sev 2 | Clear false-positive cluster on legit bank/OTP messages; major drift | Roll back to previous artifact, freeze retraining, start postmortem |
| Sev 3 | Single wrong verdict report; UI bug | Triage, reproduce with a masked fixture, fix, test, release |
| Sev 4 | Metric anomaly with no user impact | Monitor, schedule investigation |

Rules: never "fix" an incident by retraining on unconsented data; never deploy a
hotfix artifact without the §3 gates (a rollback to a known-good artifact is
preferred and faster).

## 9. Audit trail

Keep an append-only log (outside Git for anything sensitive) with:

- release id/version, artifact hash, code revision, dependency lock reference;
- training data manifest + hashes, split/group definitions, seed, command;
- evaluation report and threshold decision (who, when, why);
- approval/reviewer identity and sign-off;
- deployment time, environment, operator, `/ready` verification;
- rollback events and postmortems;
- data changes: additions, corrections, deletions/withdrawals, retention actions;
- monitoring alerts and follow-ups.

Retain audit records for at least the life of the deployment plus one year, and
never include raw message text in them. Quarterly: review the audit log,
retention, and this runbook; update as the deployment evolves.
