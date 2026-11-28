# Roadmap Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record the owner's ratified D1–D6 decisions, run the Tagalog-SMS public-corpus diagnostic (or its honest blocked record), convert the human-only tasks into ready-to-run kits, and execute the T5 release/coverage items.

**Architecture:** Documentation-and-governance work with one operational release flow. Ratified values are recorded in three places (OWNER_DECISIONS.md, the evaluation-plan template, the readiness doc) so the one-shot sealed-test validator can never meet an unfilled field. The Tagalog-SMS attempt is time-boxed to its honest outcome. The release task retrains the canonical artifact, tags `v2.0.0`, and uses the existing provenance workflow; the rollback drill measures and records recovery time against the demo artifact.

**Tech Stack:** Markdown governance docs, pytest contract/hygiene tests, Make targets (`make train`, `make datasets`, `make rehearse-consented`), GitHub release-provenance workflow, Playwright smoke (unchanged).

**Spec:** `docs/superpowers/specs/2026-11-28-roadmap-completion-design.md` (ratified values live there; this plan argues from it — executors read both).

## Global Constraints

- No real SMS in Git, logs, reports, or CI; Kaggle-sourced corpora are provenance `public`/`public_licensed` with license + single-inbox caveats on every report.
- No model, threshold, calibration, or feature changes from synthetic or public-corpus diagnostics; no real-world accuracy claims anywhere (`scripts/check_headline_claims.py` + hygiene tests enforce).
- Floor tests, smoke pins, and stamp/cache lockstep stay green; this plan touches no UI files, so no stamp bump is required.
- The sealed-test evaluator (`src/public_evaluation.py`) and its template schema are **not** modified; registration-time requirements are satisfied by pre-filling values only.
- D1/D3 are recorded "decided 2026-11-28, pending qualified-reviewer countersign"; the countersign is a plan-recorded human task and a precondition for sealed-test setup or pilot start.
- All new markdown passes `scripts/check_headline_claims.py` and the repo-hygiene tests.

## Review Focus

- **Null template field at registration:** a pre-filled plan missing any of the five `maximum_cluster_interval_width` floats or a `minimum_coverage` code fails the one-shot gate at sealed-test setup → Task 1 asserts every field non-null and in (0,1).
- **Governance fabrication:** OWNER_DECISIONS.md marking D1/D3 "decided" without the countersign condition → Task 1 asserts the exact "pending qualified-reviewer countersign" phrase for both.
- **Coverage floor bump above actual coverage:** `--cov-fail-under=80` with measured coverage under 80 fails CI → Task 4 verification asserts the measured number first.
- **Release attestation shape:** the provenance workflow requires exactly one `.pkl` + one `.metadata.json` asset per release → Task 4 verification counts release assets.
- **Corpus text leaking into committed records:** the Tagalog attempt record must contain counts/hashes only → Task 2 asserts the record cites no CSV content and hygiene tests pass.

---

### Task 1: Record ratification — OWNER_DECISIONS, template pre-fill, readiness registration

**Files:**
- Modify: `docs/OWNER_DECISIONS.md`
- Modify: `docs/templates/consented-evaluation-plan.json`
- Modify: `docs/PH_FIELD_EVALUATION_READINESS.md`
- Test: `tests/test_repo_hygiene.py` (append)

**Interfaces:**
- Produces: template pre-filled with `maximum_cluster_interval_width` = `{"precision": 0.10, "recall": 0.15, "f1": 0.12, "false_positive_rate": 0.10, "false_negative_rate": 0.15}`, `minimum_campaign_groups`: `12`, `minimum_coverage.language` = `{"en": 100, "tl": 100, "tl-en": 100}`, `minimum_coverage.category` = `{"otp": 150, "bank_alert": 150, "delivery": 150, "spam_top3": 300}`; `registered_at`/hash fields stay null/empty (corpus-dependent).
- Produces: OWNER_DECISIONS.md D1–D6 rows updated to "Decided 2026-11-28" with D1/D3 carrying the literal phrase "pending qualified-reviewer countersign" and a Decision column citing `docs/superpowers/specs/2026-11-28-roadmap-completion-design.md`.

- [ ] **Step 1: Write the failing hygiene assertions**

```python
def test_owner_decisions_record_ratification():
    text = (ROOT / "docs" / "OWNER_DECISIONS.md").read_text(encoding="utf-8")
    assert text.count("Decided 2026-11-28") == 6
    assert "pending qualified-reviewer countersign" in text
    assert text.count("Pending") == 0, "no decision row may remain Pending"


def test_evaluation_plan_template_prefills_registration_fields():
    import json

    template = json.loads((ROOT / "docs" / "templates" / "consented-evaluation-plan.json").read_text(encoding="utf-8"))
    widths = template["maximum_cluster_interval_width"]
    assert widths == {
        "precision": 0.10,
        "recall": 0.15,
        "f1": 0.12,
        "false_positive_rate": 0.10,
        "false_negative_rate": 0.15,
    }
    assert template["minimum_campaign_groups"] == 12
    assert template["minimum_coverage"]["language"] == {"en": 100, "tl": 100, "tl-en": 100}
    assert template["minimum_coverage"]["category"]["otp"] == 150
    assert template["registered_at"] is None, "registration happens at sealed-test setup, not before"
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_repo_hygiene.py -k "ratification or prefills" -v`
Expected: FAIL (rows read "Pending", template widths are null)

- [ ] **Step 3: Apply the ratified values**

OWNER_DECISIONS.md: set each D1–D6 row Status to "Decided 2026-11-28", Decision column citing the spec path; D1 and D3 rows append "pending qualified-reviewer countersign"; D2 notes the recruited-reviewer prerequisite and the dated, expiring owner-adjudication exception (amend `docs/HUMAN_REVIEW.md` and `docs/DATA_COLLECTION.md` with that one-line dated exception). Template: fill the fields per Interfaces; leave `registered_at`, `*_sha256`, `intended_use` as-is. Readiness doc: append a dated line under the acceptance-gates table — "Ratified 2026-11-28, see OWNER_DECISIONS.md; countersign pending."

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_repo_hygiene.py -v`
Expected: PASS (all, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add docs/OWNER_DECISIONS.md docs/templates/consented-evaluation-plan.json \
        docs/PH_FIELD_EVALUATION_READINESS.md docs/HUMAN_REVIEW.md \
        docs/DATA_COLLECTION.md tests/test_repo_hygiene.py
git commit -m "docs(governance): record ratified D1-D6 and pre-fill the evaluation plan"
```

---

### Task 2: Tagalog-SMS download attempt and honest record

**Files:**
- Modify: `docs/DATASET_INVENTORY.md` (Tagalog-SMS row)
- Modify: `data/external/README.md`
- Create: `docs/benchmarks/tagalog-sms-attempt-20261128.md`
- Test: `tests/test_repo_hygiene.py` (append)

**Interfaces:**
- Consumes: `make datasets DATASET=tagalog-sms` (errors without credentials: "Kaggle credentials are required").
- Produces: a dated attempt record citing the command, exit status, and the exact error class — counts and hashes only, never message text. If credentials were exported by the operator before this task runs, the branch instead produces the normalized CSV + a `make eval` report and updates DATASET_INVENTORY to "fetched"; the record then cites row counts and the normalized-CSV SHA-256 only.

- [ ] **Step 1: Write the failing docs assertion**

```python
def test_tagalog_sms_attempt_is_recorded():
    record = (ROOT / "docs" / "benchmarks" / "tagalog-sms-attempt-20261128.md").read_text(encoding="utf-8")
    assert "make datasets DATASET=tagalog-sms" in record
    assert "2026-11-28" in record
    assert "Kaggle credentials are required" in record or "normalized" in record.lower()
    inventory = (ROOT / "docs" / "DATASET_INVENTORY.md").read_text(encoding="utf-8")
    assert "download attempt recorded 2026-11-28" in inventory
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_repo_hygiene.py -k tagalog -v`
Expected: FAIL (no attempt record exists)

- [ ] **Step 3: Attempt the download and write the record**

Run `make datasets DATASET=tagalog-sms` from the repo root without credentials; capture the exit status and error. Write `docs/benchmarks/tagalog-sms-attempt-20261128.md`: date, command, exact error, the credential requirement, and the two unblock paths (operator exports `KAGGLE_USERNAME`/`KAGGLE_KEY`, or the corpus is re-hosted credential-free after license verification). Update the DATASET_INVENTORY Tagalog-SMS row's status to "download attempt recorded 2026-11-28; blocked on Kaggle credentials". If the operator exported credentials before this step and the download succeeded instead: run the normalizer, keep the CSV in ignored `data/external/`, record row counts + SHA-256 + the single-inbox caveat, and run `make eval DATA=... MODEL=models/demo_synthetic.pkl` — the report goes to the worktree's ignored output path, never Git.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_repo_hygiene.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/benchmarks/tagalog-sms-attempt-20261128.md docs/DATASET_INVENTORY.md data/external/README.md tests/test_repo_hygiene.py
git commit -m "docs(data): record the tagalog-sms download attempt and unblock paths"
```

---

### Task 3: Human-task kits — comprehension script, labeling worksheet, recruitment draft

**Files:**
- Create: `docs/templates/comprehension-session-script.md`
- Create: `docs/templates/labeling-worksheet.md`
- Create: `docs/templates/pilot-recruitment-draft.md`
- Test: `tests/test_repo_hygiene.py` (append)

**Interfaces:**
- Consumes: HUMAN_REVIEW.md session rules (fictional fixtures only; guarantee-probe question); the donation export schema (columns `record_id`, `message`, `label_hint`, `language`, `labeling_confidence`, plus empty reviewer columns).
- Produces: three ready-to-run templates. The comprehension script embeds 12 fictional fixtures (3 per band × 4 message kinds) with the three probes and the pass criterion "no participant reads a low score as a guarantee". The worksheet's review columns are exactly `labeler_1_label`, `labeler_2_label`, `adjudicated_label`, `adjudicator`.

- [ ] **Step 1: Write the failing docs assertions**

```python
def test_human_task_kits_exist_and_are_ready_to_run():
    script = (ROOT / "docs" / "templates" / "comprehension-session-script.md").read_text(encoding="utf-8")
    assert script.count("| ") >= 12, "fixture table with 12 rows"
    assert "low score" in script and "guarantee" in script, "guarantee probe required"
    worksheet = (ROOT / "docs" / "templates" / "labeling-worksheet.md").read_text(encoding="utf-8")
    for column in ("record_id", "labeler_1_label", "labeler_2_label", "adjudicated_label", "adjudicator"):
        assert column in worksheet
    draft = (ROOT / "docs" / "templates" / "pilot-recruitment-draft.md").read_text(encoding="utf-8")
    assert "2026-11-01-v4" in draft and "withdraw" in draft
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_repo_hygiene.py -k kits -v`
Expected: FAIL (templates missing)

- [ ] **Step 3: Write the three templates**

Comprehension script: session rules from HUMAN_REVIEW (fictional only), a 12-row fixture table — per band (likely-scam / suspicious / looks-safe) one OTP, one bank/e-wallet alert, one delivery notice, one personal Taglish message drawn from tracked synthetic fixtures — the three probes ("what is this message?", "what part of the UI influenced you?", "what would you do next?"), the pre-details guarantee probe, and the pass criterion verbatim. Worksheet: header row per Interfaces, one worked fictional example row, adjudication rules referencing the dated owner-adjudication exception. Recruitment draft: short personal-network message stating purpose, the notice link and version, 90-day retention, withdrawal-ID mechanics, and the never-submit list (live OTPs, credentials, third-party conversations).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_repo_hygiene.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/templates/comprehension-session-script.md docs/templates/labeling-worksheet.md docs/templates/pilot-recruitment-draft.md tests/test_repo_hygiene.py
git commit -m "docs(governance): comprehension script, labeling worksheet, and pilot recruitment draft"
```

---

### Task 4: Coverage ratchet, attested v2.0.0 release, timed rollback drill

**Files:**
- Modify: `pyproject.toml` (`--cov-fail-under=78` → `80`)
- Modify: `README.md` (metrics table), `docs/MODEL_CARD.md` (last-reviewed + metrics), `docs/DEPLOYMENT.md` (dated drill line), `docs/RETRAINING.md` (drill duration)
- Create: `docs/benchmarks/release-drill-20261128.md`
- Test: none new (existing suite is the gate); verification is command output recorded in the drill doc

**Interfaces:**
- Consumes: `make train`, `make doctor`, the release-provenance workflow (triggers on a published GitHub release; requires exactly one `.pkl` + one `.metadata.json` asset), `demo_synthetic.pkl` as the rollback baseline.
- Produces: tag `v2.0.0` with an attested canonical artifact; a recorded drill duration.

- [ ] **Step 1: Bump the coverage floor and verify measured coverage**

Run: `python - <<'EOF'  # edit pyproject: --cov-fail-under=78 → 80` then `pytest -q`
Expected: PASS with "Total coverage: 81.4x%" ≥ 80. Commit: `test: enforce 80 percent coverage floor`.

- [ ] **Step 2: Fresh canonical retrain with the base corpus**

The execution worktree lacks the git-ignored base corpus — copy `data/raw/spam.csv` from the main checkout first (counts only; the file itself stays ignored). Run: `make train`. Expected: `models/spam_detector_v1.pkl` + sidecar written; note the printed spam precision/recall, then update the README metrics table and MODEL_CARD "Last reviewed" to match the new sidecar values.

- [ ] **Step 3: Tag and publish the release**

Run: `git tag v2.0.0 && git push origin v2.0.0`, then publish the GitHub release for the tag attaching exactly `models/spam_detector_v1.pkl` + `models/spam_detector_v1.metadata.json`. Wait for the release-provenance workflow; verify it passes and the attestation names the artifact hash. Record the run URL in the drill doc.

- [ ] **Step 4: Timed rollback drill**

Start the timer; point `SMSD_MODEL_PATH` at `models/demo_synthetic.pkl`, restart the local service, verify `/ready` = ready and `/model-info` reports `synthetic-demo`; restore `SMSD_MODEL_PATH` to the canonical artifact, restart, verify `/model-info` reports the canonical version; stop the timer. Write `docs/benchmarks/release-drill-20261128.md`: the two durations, the commands, and the verified `/model-info` versions. Run `make doctor` — the served-model check must pass against the restored canonical sidecar.

- [ ] **Step 5: Update docs and commit**

Record the drill duration in `docs/RETRAINING.md` and a dated line in `docs/DEPLOYMENT.md`'s rollback section. Commit: `docs(release): attest v2.0.0 and record the timed rollback drill`.

---

### Task 5: Claims sweep, quarterly ritual scheduling, final ROADMAP log

**Files:**
- Modify: `docs/ROADMAP.md` (quarterly ritual dates + progress log)
- Test: existing `scripts/check_headline_claims.py` + `tests/test_repo_hygiene.py` (no new tests)

**Interfaces:**
- Consumes: all tasks above; `scripts/check_headline_claims.py` over the repo's README/docs set.

- [ ] **Step 1: Run the claims sweep and hygiene suite**

Run: `python scripts/check_headline_claims.py` and `pytest tests/test_repo_hygiene.py tests/test_web_contract.py -q`
Expected: PASS — any failure is fixed by editing the offending sentence, never by weakening a check.

- [ ] **Step 1b: Re-verify the consented rehearsal end-to-end (spec G5)**

Run: `make rehearse-consented`
Expected: the disposable synthetic rehearsal passes — consent, review-stage export, withdrawal, and message-free reports. Any failure is investigated before the release task is considered done.

- [ ] **Step 2: Schedule the quarterly ritual**

Append to ROADMAP's progress log the dated Q1-2027 checklist: re-run the dated benchmark, refresh DATASET_INVENTORY counts, update IMPROVEMENT_EXECUTION, review the roadmap — with target dates.

- [ ] **Step 3: Final ROADMAP progress log line**

One line: plan executed, PR number, drills and artifacts produced, countersign + pilot kit pending on humans.

- [ ] **Step 4: Verify and commit**

Run: `pytest -q` (full suite) and `make doctor`.
Expected: PASS. Commit: `docs(roadmap): claims sweep, quarterly ritual dates, and completion log`.

---

## Post-plan (outside this plan's scope)

Countersign acquisition and pilot recruitment are human tasks enabled by Task 1/Task 3 artifacts. The sealed test itself opens only when a consented corpus exists and the countersign is recorded.
