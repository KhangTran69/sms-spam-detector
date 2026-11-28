# Long-Term Improvement Roadmap

Created: 2026-11-27 · Horizon: ~4 quarters · Review cadence: quarterly, or immediately after any evidence-state change (new dataset, frozen-test opening, owner decision).

This roadmap is the forward-looking view. It complements, and does not
replace:

- [`PLAN.md`](../PLAN.md) — original goal-level phases (still accurate).
- [`IMPROVEMENT_EXECUTION.md`](IMPROVEMENT_EXECUTION.md) — dated execution
  record; update it when a roadmap item lands, not vice versa.
- [`evaluation.md`](evaluation.md) — evaluation methods, gates, data status.
- [`MODEL_CARD.md §4`](MODEL_CARD.md) — canonical limitations statement.

**One-line strategy:** the engineering is ahead of the evidence. Every track
below either (a) unblocks real Philippine evidence, (b) runs safely in
parallel without weakening claims, or (c) is explicitly gated until evidence
exists.

---

## 0. Where we are (2026-11-27)

| Evidence source | Status | What it can support |
|---|---|---|
| Tracked synthetic PH supplements + holdout (513 + 264 rows, one author) | In Git, used in CI gates | Pipeline correctness only |
| Verified UCI English corpus (CC BY 4.0) | CI quality gate, F1 ≥ 0.90 | English-corpus diagnostics |
| Public PH inbox (Kaggle, CC BY 4.0, one contributor) | Local-only; group-isolated internal diagnostic (1,664 rows, **10 ham** in test) | Diagnostic only — extreme class imbalance |
| Tagalog-SMS (CC0 per Kaggle metadata) | Downloader built, **never fetched or evaluated** | Nothing yet |
| Consented PH messages | **Zero collected.** Donation intake is built and operator-gated | Nothing yet |

Engineering state: CI (pytest 352+, coverage floor 78%, ruff, mypy, browser
smoke, container smoke, wheel smoke, UCI gate) green; donation intake, PII
scrubbing, Redis rate limiting, artifact attestation, release-provenance
workflow, and a local transformer spike all implemented. Primary model is now
sigmoid-calibrated TF-IDF (word + char) with CV-selected
LogisticRegression/LinearSVC.

Known debts: local checkout is 24 commits behind `origin/main`; the 2026-11-08
docs commit lives on `codex/reviewer-map-sms-2026-11-08`; `docs/superpowers/`
is untracked; the local API demo still serves legacy `spam_detector_v1`
(uncalibrated, no provenance); local venv is Python 3.13 while CI tests
3.11/3.12; provisional release criteria are still unapproved.

---

## T0 — Hygiene and baseline reset (week 1; agent-executable)

Small, unglamorous, and it unblocks everything else.

1. **Fast-forward local `main` to `origin/main`** (verified clean merge-tree;
   no local commits to lose). Refresh `.venv` against
   `constraints/py3.12.txt` (the CI-supported floor) and re-run
   `make lint typecheck test` + `npm run test:modules` locally.
2. **Merge or close the 2026-11-08 docs commit** (`codex/reviewer-map-sms-2026-11-08`,
   1 commit, docs-only route→test map). Low risk; it is the only ref ahead of
   origin/main.
3. **Archive `docs/superpowers/`**: these plans produced merged PRs (#21–#23).
   Move the three files under `docs/history/` with a one-line status note
   each ("implemented in PR #…"), or delete them; do not leave untracked
   plan files that future agents may re-execute.
4. **Retire the legacy model path**: rebuild a current synthetic-demo artifact
   (`make demo`), point local serving at it, and delete stale artifacts
   (`spam_detector_v1.pkl`, candidate artifacts) after confirming nothing
   references them. An uncalibrated legacy model behind the demo endpoint
   contradicts the docs.
5. **Add a repo-state doctor**: extend `scripts/demo_smoke.py` or add
   `make doctor` that asserts (venv Python matches a constraint file, no
   untracked plan files, served model version == newest artifact metadata,
   no unmerged docs commits). Keep it under a minute.

Exit criteria: local == origin; every doc referenced from `docs/README.md`
exists on the checked-out tree; served model matches a current metadata
sidecar.

---

## T1 — Evidence track: consented Philippine data (the critical path)

**Everything headline-worthy is blocked here.** The build already exists
(donation intake, consented-data workflow, sealed-test gates in
`evaluation.md`, consented split in `src/consented_split.py`). What is missing
is owner authorization, participants, and labels. Sequence:

1. **Owner decision pack (week 1–2, human).** Assemble one document that asks
   for exactly the decisions the docs keep deferring: approve/replace the
   provisional release criteria, approve the consent notice version and
   retention period, name data steward + two labelers + adjudicator,
   authorize (or decline) the first collection round. Nothing in T1 starts
   before this exists.
2. **Dry-run the intake loop without participants (week 2–3, agent).** Use
   `src/consented_rehearsal.py` end-to-end: enable `SMSD_DONATIONS_ENABLED`,
   submit synthetic donations, label-hint review, export, withdrawal, and
   deletion; verify the message-free logs/reports claim with the existing
   hygiene tests. Target: the operator can run a collection day from one
   page of runbook.
3. **First consented collection round (weeks 4–10, human-led).** Small and
   honest: 10–30 donors via the documented consent process; expect a few
   hundred messages, not thousands. Every submission keeps notice version +
   consent timestamp; label hints are staging only. Track coverage against
   the matrix in `IMPROVEMENT_EXECUTION.md §3` (OTP / bank-alert / delivery /
   bills / promo / personal × English / Filipino / Taglish).
4. **Two-labeler labeling + adjudication (overlaps weeks 6–12).** Use the
   donation export → review-stage CSV flow. Preserve the ambiguous-label
   state; unresolved rows never enter training or evaluation.
5. **Freeze the sealed evaluation set (week 12+, owner+steward).** Disjoint
   donors/campaigns from development; later-period final set when timestamps
   allow. Register the approved criteria *before* opening it
   (`docs/templates/consented-evaluation-plan.json` exists for this).
6. **First real evaluation, once (after freeze).** Run the consented
   evaluation path; report per-category/language metrics with Wilson
   intervals and cluster-aware uncertainty. Whatever the numbers are, they
   become the first genuine PH performance statement — or the documented
   reason the gate is unmet.

Exit criteria (T1 exit = project's core goal): ≥ 2 independent donors per
reported category×language cell, sealed test opened exactly once, criteria
met or blockers published. Anti-goal: headline numbers before this point.

**Fallback if recruitment stalls:** keep scope honestly reduced — public-corpus
diagnostics (T2) + synthetic engineering gates — and say so on the README
evidence banner rather than relaxing the criteria.

---

## T2 — Public-corpus expansion (parallel; diagnostic-only, agent-executable)

1. **Fetch and evaluate Tagalog-SMS** (CC0 per Kaggle metadata) via the built
   `make datasets DATASET=tagalog-sms` path. Publish a
   `ph-tagalog-sms-diagnostic-<date>.json` in the same message-free format.
   Document the sender-metadata handling and single-inbox caveat.
2. **Imbalance handling study on the PH inbox corpus.** 65 ham vs 1,599 spam
   makes every ham-side number fragile. Evaluate class-weighting /
   threshold-per-dataset effects on *diagnostic* splits only; no model change
   without T1's dev set.
3. **Near-duplicate audits between all public corpora and tracked synthetic
   templates** (the `clean-main…near-duplicate-audit.json` pattern) so style
   overlap between synthetic and public data stays quantified, not assumed.
4. **License/provenance watch:** keep the Hugging Face merged corpus blocked
   until every constituent source's terms are verified; record the check
   date in `data/external/README.md` even when the answer is "still blocked".

Exit criteria: two public PH corpora evaluated with published message-free
reports; no report merges public+synthetic+consented into one headline.

---

## T3 — Model capability (gated on T1's development set)

Ordered by expected value per risk:

1. **Calibration verification on real data** — the pipeline now fits sigmoid
   calibration; validate Brier/ECE on the frozen set, and only then flip the
   UI's `probability_calibrated` copy for the deployed artifact. Until then
   the "uncalibrated model score" wording stays.
2. **Transformer ensemble promotion decision.** The XLM-R spike is
   local-only and deliberately not promoted. With a real dev set: compare
   against the incumbent on identical grouped splits, using the real-holdout
   promotion gate. Expected outcome is a *decision* (promote as optional
   extra / archive with rationale) either way — do not leave it in limbo past
   one quarter after T1's dev set exists.
3. **Robustness/obfuscation suite:** extend `src/patterns.py` tests with
   systematic zero-width/leetspeak/mixed-script/masked-number variants of
   *both* classes; publish FP/FN deltas per family. Robustness work is
   legitimate on synthetic+public data as long as claims stay diagnostic.
4. **Threshold policy review:** the cv-robust rule kept 0.50 over a 0.93
   validation candidate. Revisit with real validation data; document the
   chosen operating point and its measured FP cost per legitimate category.

---

## T4 — Product and human factors (parallel; no evidence dependency)

1. **Comprehension study** per `docs/HUMAN_REVIEW.md`: 5–8 volunteers,
   fictional fixtures, approved script; success = no participant reads a low
   score as a guarantee. Currently the most user-visible open item.
2. **Manual assistive-tech review** (VoiceOver/NVDA) of the result page,
   disclosure pattern, and donation flow — the browser smoke covers
   keyboard/mouse only.
3. **Filipino copy review** by a native speaker (the `fil` dictionary ships
   but was author-written); fix register/terminology, keep API signal terms
   (`url`, `phone`, `money`, `urgency`, `brand`) consistent.
4. **Activate the feedback loop in the pilot**: enable
   `SMSD_FEEDBACK_ENABLED` during T4.1, cluster corrections via
   `src/monitor.py` + `src/active_learning.py`, and treat them strictly as
   review-priority signals (never auto-training data — already enforced).
5. **Donation flow UX check**: include the donate page in the comprehension
   study; verify the consent notice is actually read (short comprehension
   question), not just clicked.

Exit criteria: comprehension criteria met on the approved script; a11y review
findings filed and P1s fixed; no copy change ships without re-running the
affected UI tests.

---

## T5 — Operations, release, and maintenance (parallel; continuous)

1. **First attested release:** tag a version, run the release-provenance
   workflow, verify artifact hash + `/model-info` agreement, and do one
   *timed* rollback drill (the local one took minutes; record actual time in
   RETRAINING.md).
2. **Monitoring counters** (message-free only): request counts, p50/p95
   latency, status/error codes by endpoint, model version, correction counts
   — wired into `/health`-adjacent metrics or a scrape endpoint, with
   request-body logging hard-off. Required before any T1 field pilot.
3. **Coverage ratchet:** 78% → 85% floor, prioritizing `public_evaluation`,
   `donations`, `consented_split` paths; add the floor bump to each PR that
   touches them.
4. **Dependency automation:** enable Dependabot/Renovate against the
   constraint files with a monthly window; keep the three constraint tiers
   (py3.11/3.12/3.13 + transform-*) regenerating in the same PR.
5. **Docs drift guard:** extend `scripts/check_headline_claims.py` and repo
   hygiene tests to fail on (a) accuracy claims outside allowed docs, (b)
   `docs/README.md` entries pointing at missing files, (c) served-model
   version ≠ MODEL_CARD "last reviewed" model.
6. **Quarterly ritual:** re-run the dated benchmark, refresh
   DATASET_INVENTORY counts, update IMPROVEMENT_EXECUTION.md, and review this
   roadmap. One PR, one afternoon.

---

## Sequencing at a glance

```
T0 hygiene ──► T1 evidence ──(dev set)──► T3 model capability
   │              │
   │              └──(frozen set)──► first real claim (once)
   ├──► T2 public corpora (parallel, diagnostic-only)
   ├──► T4 product/human factors (parallel)
   └──► T5 ops/release (parallel, continuous)
```

Hard dependency: T3.1–T3.3 wait for T1's development set. T2/T4/T5 never
block on it.

## Owner-decision register (things an agent must not decide)

| # | Decision | Blocks | Where recorded |
|---|---|---|---|
| D1 | Approve/replace provisional release criteria | T1.5, T3 | `evaluation.md` + IMPROVEMENT_EXECUTION |
| D2 | Consent notice version + retention period | T1.3 | `privacy-notice.md` |
| D3 | Authorize first collection round; name steward/labelers/adjudicator | T1.3–T1.4 | DATA_COLLECTION |
| D4 | Transformer spike: promote/archive | T3.2 | MODEL_CARD + BENCHMARKING |
| D5 | Public deployment target (if any) | T5.2 beyond local | DEPLOYMENT |
| D6 | Coverage-floor targets | T5.3 | pyproject/CI |

## Guardrails (unchanged by this roadmap)

- No real SMS in Git, logs, reports, caches, or CI.
- No headline performance claims from synthetic or single-inbox public data;
  `check_headline_claims.py` keeps enforcing this in CI.
- Corrections are investigation signals, never automatic training data.
- The Hugging Face merged corpus stays blocked until constituent licenses are
  verified.
- Prediction schema stays stable; UI stays no-build vanilla JS.
- Scores are assistive hints — never blocking/reporting/penalty inputs.

## How we will know this roadmap failed

- One year out: still only synthetic data, still "no real-world claim
  supported", and the gap was *not* an owner decision that was formally
  declined. (A declined D1–D3 with a documented reason is a legitimate
  outcome; silent drift is not.)
- Public-corpus diagnostics quietly start being cited as accuracy.
- The transformer spike remains permanently "pending a decision".
- Coverage floor, doc drift checks, and the quarterly ritual stop being
  exercised.

---

## Quarterly ritual (dated checklist)

Quarterly from 2026-11-28: **next: 2027-02-28**, then 2027-05-28,
2027-08-28, 2027-11-28. One PR, one afternoon; if a date slips, the item
moves to the following week — the ritual is never silently skipped. Actions
only, no claims: record dated, message-free outputs under `docs/benchmarks/`
(or the progress log below) in the same PR. This checklist folds the
artifact/provenance workflow into the T5.6 ritual; the benchmark /
DATASET_INVENTORY / IMPROVEMENT_EXECUTION / roadmap-review items of T5.6 keep
their already-scheduled dates (2027-01-15 → 2027-03-31, see the progress log).

- [ ] **Verify the immutable release copies** (next: 2027-02-28): compare
      `models/releases/v2.0.0/spam_detector_v1.pkl` (sha256) against the
      `artifact_sha256` recorded in
      `models/releases/v2.0.0/spam_detector_v1.metadata.json` and against the
      current canonical `models/spam_detector_v1.pkl` sidecar when it exists;
      record the comparison in the progress log.
- [ ] **Re-run the timed rollback drill** per
      [RETRAINING.md §7](RETRAINING.md#7-rollback-procedure) (next: 2027-02-28)
      and record the measured per-direction durations in a dated,
      message-free report under `docs/benchmarks/` (precedents:
      [release-drill-20261128.md](benchmarks/release-drill-20261128.md),
      [rollback-drill-v2-1-0-candidate-20261128.md](benchmarks/rollback-drill-v2-1-0-candidate-20261128.md)).
- [ ] **Re-run `gh attestation verify`** on the release artifact —
      `gh attestation verify models/releases/v2.0.0/spam_detector_v1.pkl` —
      and record the workflow/run reference (next: 2027-02-28).
- [ ] **Review D1/D3 countersign status** in
      [OWNER_DECISIONS.md](OWNER_DECISIONS.md) (next: 2027-02-28): if a
      qualified-reviewer countersign landed during the quarter, update the
      register rows; if still pending, date this review in the progress log.
- [ ] **Run `python scripts/pilot_status.py <private intake CSVs>`** against
      the private intake CSVs (next: 2027-02-28) and compare the reported
      coverage gaps with the ratified minimums in
      [templates/consented-evaluation-plan.json](templates/consented-evaluation-plan.json);
      keep the counts in the progress log — the CSVs themselves stay private.
- [ ] **Re-run `make pilot-preflight`** (synthetic fixtures only) and confirm
      the preflight output stays message-free (next: 2027-02-28).

## Progress log

### 2026-11-28 — Transfer-gap experiment: adding real training data closes the gap

- Candidate trained on the canonical recipe + 2,738 Tagalog-SMS rows (group-isolated;
  1 cross-source label conflict excluded - a bare 'Ok' text labeled spam in the corpus,
  ham in the UCI base; base label kept).
- On the identical 372 held-out Tagalog rows (out-of-sample for both): incumbent
  precision 0.546 / recall 0.696 / FPR 0.219 -> candidate precision 0.890 / recall 0.951
  / FPR 0.044. Critical-category FPs: notifs 43 -> 7, otp 11 -> 4, gov 5 -> 1.
- Record (aggregates only): docs/benchmarks/tagalog-transfer-experiment-20261128.json.
  Honest caveats in the record: directional evidence on 372 rows; same-domain training;
  matched 0.50 threshold; no real-world accuracy claim. The experiment is diagnostic -
  the attested v2.0.0 release artifact is unchanged (still trained without real data).

### 2026-11-28 — T2.1 executed: Tagalog-SMS fetched, normalized, and diagnosed

- Kaggle credentials installed by the owner (token file outside the repo; never committed).
- `make datasets DATASET=tagalog-sms`: 3,455 raw rows → 2,739 normalized (715 duplicates excluded;
  0 blank/redacted). The archive ships one .xlsx workbook — the downloader now converts a
  one-xlsx archive via a new `datasets` extra (openpyxl) with a focused conversion test.
- Diagnostic (message-free, committed): `docs/benchmarks/tagalog-sms_spam_detector_v1-2026-11-28.json`.
  At threshold 0.50: precision 0.348, recall 0.559 — **the transfer gap to real Tagalog traffic is
  now empirically established**: 669 of 1,439 notifications false-flagged, 91 of 504 OTPs flagged,
  257 of 585 scam texts missed. ROC-AUC 0.635; Brier 0.346 / ECE 0.307 (badly miscalibrated here).
- T2 exit criterion met: two public PH corpora now have published message-free diagnostic reports
  (PH-inbox 2026-11-06; Tagalog-SMS 2026-11-28). License CC0 verified via the Kaggle API.
- New bwandowando corpus identified: license verified CC BY-NC-SA 4.0 (non-commercial OK for this
  project's diagnostic; corpus stays local-only). Fetch deferred until the owner requests it.
- Consequence for T3: model work now has a real-corpus evidence base — the UCI+synthetic pipeline
  does not transfer as-is; any model improvement must train/validate on real Philippine data.

### 2026-11-27 — T0 executed

- **T0.1 done.** Local `main` fast-forwarded to `origin/main` at `acec960`
  (which now includes PRs up to #42 — newer than the snapshot this roadmap was
  drafted against: ops-metrics module, Nov-17/21 benchmark reports,
  `PH_FIELD_EVALUATION_READINESS.md`, `OPERATIONAL_AND_ACCESSIBILITY_REVIEW.md`).
  venv synced against `constraints/py3.13.txt`; suite green (549 passed,
  coverage 81.6%).
- **T0.2 closed without action.** The 2026-11-08 docs commit
  (`codex/reviewer-map-sms-2026-11-08`) is already contained in `origin/main`.
- **T0.3 done.** `docs/superpowers/` moved to `docs/history/` with a status
  README mapping each plan to the PRs that implemented it.
- **T0.4 done with a correction to this roadmap's assumption.** On the current
  tree `spam_detector_v1` is the *canonical `make train` output name*, not a
  legacy path — so nothing was renamed. Instead: stale local artifacts deleted
  (`spam_detector_v1.pkl`, 2026-10-20 candidate set), `make demo` rebuilt and
  smoke-passed (`synthetic-demo`, validation-tuned threshold), and local
  serving pointed at `models/demo_synthetic.pkl`. `sms_spam_model.*` and
  `spam_detector_v2_1.*` kept (referenced by ARCHITECTURE/DEPLOYMENT docs).
  DATASET_INVENTORY's stale "running local API reports spam_detector_v1"
  observation updated with a dated correction.
- **T0.5 done.** `scripts/doctor.py` + `make doctor`: constraint/venv pairing,
  git ff/unpushed state, plan-archive sentinel, referenced-artifact existence
  (WARN + regeneration hint for not-yet-trained outputs), served-model vs
  metadata sidecars, docs-index completeness.
- **T1.1 partially pre-empted upstream.** `PH_FIELD_EVALUATION_READINESS.md`
  already defines the D1–D3 decision content. Added
  `docs/OWNER_DECISIONS.md` as the D1–D6 *register* pointing at authoritative
  docs rather than duplicating them. **D1–D6 all remain undecided — this is
  now the single blocker for T1.**
- **T5.2 largely satisfied upstream** for single-process telemetry
  (`api/ops_metrics.py`, token-gated); gateway/shared aggregation remains open.
- **T5.4 done.** `.github/dependabot.yml` (github-actions/pip/npm, monthly).
- **T5.5 partially done.** Docs-index rows added for ROADMAP/OWNER_DECISIONS/
  history; index-completeness check lives in `make doctor` (CI addition still
  open).
- 2026-11-28: Editorial polish pass executed on the untracked plan's successor prompt
  (docs/UI_UX_DESIGN_PLAN.md follow-up): tokens.css extracted and shared with the
  donation page (donate-v6), short meter labels, marker settle via transform,
  result reveal, WCAG token-pair audit test (16 pairs x 2 dials), 200%/400% zoom
  smoke checks, aria-current on tabs. Shell smsd-shell-v27 / ui22-editorial-polish.
  Word-budget copy trimming remains deferred to the comprehension re-review round.
- Queued next: T2.1 Tagalog-SMS fetch+eval (attempted 2026-11-28 — done as far
  as the workspace can go, blocked on Kaggle credentials from the operator;
  see the 2026-11-28 completion entry below), T4.1 comprehension study +
  qualified-reviewer countersign + pilot kits (pending on humans), T5.3
  coverage ratchet and T5.6 quarterly ritual scheduling (done — see the
  2026-11-28 completion entry below: floor at 80 with the 85% checkpoint
  dated 2027-03-31, Q1-2027 ritual dates scheduled).

### 2026-11-28 — Roadmap-completion plan executed (PR #45)

- Plan executed 2026-11-28 in PR #45: D1–D6 ratified and recorded
  (OWNER_DECISIONS.md register + pre-filled consented-evaluation-plan
  template); Tagalog-SMS download attempt honestly recorded as blocked on
  Kaggle credentials (0 rows fetched); three human-task kits drafted
  (comprehension-session script, labeling worksheet, pilot-recruitment
  draft); coverage floor raised 78 → 80; release `v2.0.0` published with
  provenance attestation (workflow run 46125116202) and the timed rollback
  drill recorded at 6.279 s total (`docs/benchmarks/release-drill-20261128.md`);
  headline-claims sweep exit 0; consented rehearsal re-verified PASS
  (`make rehearse-consented`, spec exit criterion G5: consent gates, blind
  two-reviewer review-stage export, withdrawal blocking, message-free
  reports). **Still pending on humans: the qualified-reviewer countersign on
  D1/D3 and the owner review of the pilot-recruitment kit.**

### 2026-11-28 — Q1-2027 quarterly ritual scheduled (T5.6)

- Checklist with target dates (one PR, one afternoon; if a target slips, the
  item moves to the following week — the ritual is never silently skipped):
  - **2027-01-15:** re-run the dated benchmark (`python -m src.benchmark` per
    `docs/BENCHMARKING.md`; dated message-free report under `docs/benchmarks/`).
  - **2027-02-01:** refresh `docs/DATASET_INVENTORY.md` row counts and
    per-source status, including anything fetched or blocked since 2026-11-28.
  - **2027-02-15:** update `docs/IMPROVEMENT_EXECUTION.md` with everything
    that landed during the quarter.
  - **2027-03-31:** review this roadmap (evidence-state changes, the
    owner-decision register, sequencing; this is also the D6 checkpoint for
    the 85% coverage-floor target).

### 2026-11-29 — Roadmap continuation: privacy, audit tooling and pilot review

- T2.3: aggregate-only cross-corpus overlap command in `src/corpus_audit.py`
  with bounded comparison work, source fingerprints and synthetic regression
  tests. Approved local snapshots still need a real execution; no new
  cross-corpus measurements are claimed.
- T2.2: fixed-threshold class-prior sensitivity calculated from the existing
  public aggregate report, [public-prior-shift-diagnostic-20261129.md](benchmarks/public-prior-shift-diagnostic-20261129.md).
  Separate class-weighted training study requires approved development inputs.
- T4/T5: donation loopback Host and browser Origin validation, PII correction
  focus and ARIA relationships, and expanded browser checks. The bilingual
  facilitator draft avoids coaching before the recorded comprehension probes.
  Human review, native-speaker review and the signed pilot prerequisites remain
  outstanding.
- T5: doctor supports operator metrics authentication with bounded JSON,
  redirect refusal and HTTPS/loopback transport; distinguishes denied metrics
  requests from connection failure. The prior pilot status hardening and docs
  index link regression checks remain in PR #60.
- No consented collection, sealed-test interaction, model release, or public
  deployment occurred. D5 remains local-only; coverage target remains 85%.

- T3: paired synthetic formatting robustness diagnostic with fixed artifact
  threshold, aggregate error transitions and regression tests. CI exercises it
  using the synthetic smoke model; field robustness remains unmeasured.

### 2026-11-29 — Consent boundary, storage availability and leakage regression follow-up

- Tighten explicit JSON consent types, refuse duplicate-key/nonfinite JSON,
  ambiguous local authorities and duplicate operator token headers; preserve
  local-only donation policy and the existing withdrawal non-enumeration rule.
- Offload blocking SQLite operations while retaining admission through
  completion. Add failure/recovery and concurrent liveness regressions.
- Expand overlap diagnostics with within-corpus label conflicts and distinct
  row participation; keep both historical similarity cutoffs at 0.90.
- Exercise individual malformed preregistration fields, blocked CLI reporting,
  missing split inputs and dependency discovery. No release gates changed.


- Reject malformed classifier probability matrices before generating a verdict;
  maintain the stored threshold. Correct calibration calculation for one-shot
  score iterables. Exercise real synthetic training/evaluation CLI output,
  plots and artifact verification; test malformed Redis reply recovery.
- Add the native assistive-technology evidence worksheet. It remains unfilled
  until actual qualified review; no accessibility acceptance is asserted.

### 2026-11-29 — Coverage ratchet reaches the D6 target

On commit `720496bf90f4bb0cb0c24cfd4c6caa2b096bae0f`, CI run
[46170305718](https://github.com/KhangTran69/sms-spam-detector/actions/runs/46170305718)
reported identical results on Python 3.11, 3.12 and 3.13: 825 passed,
4 skipped, 87.03% coverage. The UCI diagnostic quality gate passed at
F1 0.9425. Raise the enforced per-PR coverage floor from 82% to the ratified
85% in pyproject and its hygiene regression together. This is an engineering
coverage milestone only, not a field accuracy or model acceptance result.
Retain the unchanged OTP, bank-alert, delivery and calibration release gates.

### Donation reliability and optional spreadsheet coverage

Persist opaque retry keys transactionally with the original donation; preserve consent and expiration on replay, refuse conflicting or withdrawn keys, and test concurrent calls. Retain local-only controls and message-free logging. The browser only retries at the user's explicit request while its unchanged pending form remains in memory.

### Development-only model-quality and deployment review

Add a fingerprint-bound, group-isolated class-weight and formatting experiment that refuses known frozen inputs and cross-fold duplicates. Exercise it with fictional data; approved Philippine development snapshots and qualified independent review remain necessary. Add an offline gateway configuration reviewer with value-free findings, which cannot grant deployment authorization. Keep all production feature semantics, existing acceptance gates and historical evidence unchanged.

### Independent review and coverage readiness

Require actual separate review outcomes and independent disagreement resolution. Reject default-derived agreement and prevent duplicate or incomplete message checks from reporting minimums-met status. Keep native-language and qualified-reviewer approval outstanding.

### Local retention and recovery follow-up

Separate committed erasure from optional compaction, publish private exports exclusively, reject shared database files, and add explicit existing-store retention maintenance plus a disposable stale-backup withdrawal reconciliation rehearsal. No actual operator backup or participant store is accessed.

### Consented intake integrity follow-up

Bound private CSV/JSON reads, reject ambiguous headers and duplicate sidecar keys, constrain import destinations, enforce ratified-notice retention and chronology, and refuse category-hidden template leakage or campaign aliases. Preserve explicit worksheet chronology for later independently sealed evaluation.

### Development experiment and Redis configuration follow-up

Union declared campaign groups with template families before development cross-validation; enforce complete disjoint membership and report paired class-specific error transitions. Reject Redis URL options that can override bounded connection settings or TLS verification, consistently in runtime and offline preflight. No deployed model or real-data acceptance criteria changed.
