# Design: Roadmap completion — ratification, public-corpus diagnostic, and readiness execution

Date: 2026-11-28 · Owner ratified approach A ("ratify now"), the public-Kaggle
provenance ruling, and — in the 2026-11-28 builder-check round — the four
resolutions below ("confirmed as proposed"). Spec carries the ratified values;
`docs/OWNER_DECISIONS.md` is updated to record them by the plan's first task.

## Intent and why

The long-term roadmap ([ROADMAP.md](../../ROADMAP.md)) has executed everything
agent-executable. What remains is blocked by three kinds of inputs: owner
decisions (D1–D6), Kaggle credentials, and human-only activities. This work
collapses the owner's role into one conversation (done — ratified below),
executes the credential-feasible diagnostic, and converts every human-only
activity into a ready-to-run artifact so nothing is waiting on blank pages.

## Goals

- G1: D1–D6 ratified and recorded (this spec §Ratified decisions + OWNER_DECISIONS.md update).
- G2: T2.1 executed — Tagalog-SMS downloaded if reachable, normalized, and
  diagnosed with a message-free report; blocked path documented honestly if
  credentials are required.
- G3: T5 execution — coverage floor ratcheted to 80%, a tagged release with
  provenance attestation, a timed rollback drill recorded, quarterly ritual
  scheduled with dated checklist.
- G4: Human-only tasks converted to ready-to-run kits: comprehension-session
  script (fixtures + probes per HUMAN_REVIEW), labeling worksheet from the
  donation export schema, recruitment message draft.
- G5: Consented-rehearsal dry-run (`make rehearse-consented`) re-verified
  end-to-end and the sealed-test registration template pre-filled except the
  corpus-dependent hashes (which cannot exist before data).

## Non-goals

- No real-message collection in this work (D3 authorizes a *future* pilot;
  recruitment starts only after the pilot kits pass owner review).
- No public deployment.
- No model, threshold, calibration, or feature changes from synthetic or
  public-corpus diagnostics.
- No sealed-test opening (no consented corpus exists).
- No claims of real-world Philippine accuracy anywhere.

## Anti-goals (failure even if it "works")

- Fabricating participants, labels, or metrics.
- Treating public-corpus diagnostics as field accuracy in any headline.
- Auto-training on user corrections or donation label hints.

## Constraints

- No real SMS in Git, logs, reports, or CI.
- Floor tests and smoke pins stay green; stamp/cache lockstep preserved on any
  UI-adjacent change.
- Kaggle-sourced corpora are ruled **public data** (owner, 2026-11-28):
  provenance class `public`/`public_licensed`, never `consented`; license and
  single-inbox caveats stay on every report.
- One-shot sealed-test discipline: the attempt marker is consumed even on
  failure (existing evaluator behavior).

## Approaches considered

- **A. Ratification-ready (chosen):** pre-draft all D1–D6 values for owner
  ratification in conversation, then execute everything executable around
  them, and stage human-only work as kits. Rationale: the bottleneck was
  decision *friction*, not decision *substance* — the project's own
  provisional numbers existed and only needed an owner yes.
- **B. Execute-only, decisions deferred:** ship credential-free items only.
  Rejected: leaves T1 blocked and guarantees a second planning round with no
  new information.
- **C. Full simulated field study on synthetic data:** rejected — it would
  manufacture exactly the evidence-shaped artifacts the honesty gates exist to
  prevent.

## Ratified decisions (owner, 2026-11-28, effective on plan execution)

- **D1 release gates** (registered into `templates/consented-evaluation-plan.json`
  at sealed-test setup; numbers from the project's own provisional proposal,
  IMPROVEMENT_EXECUTION §2):
  - Provenance/consent: 100% of evaluated records consent-eligible.
  - Leakage: zero accepted train/test campaign or template-family overlap.
  - False-positive rate ≤ **5%** in each critical legitimate category (OTP,
    bank/e-wallet alert, delivery), 95% Wilson **upper bound ≤ 8%**.
  - Overall spam recall ≥ **80%**, 95% Wilson **lower bound ≥ 75%**.
  - Calibration reported (Brier + ECE); calibrated-probability UI wording only
    if ECE ≤ **0.05** on the frozen test with ≥ 30 samples per populated bin.
  - Coverage: ≥ **10** independent campaign/donor groups per reported slice;
    any language×category cell under **100** consented rows is reported
    insufficient, not estimated.
  - Uncertainty: registered maximum cluster-interval widths — precision ≤ **10
    percentage points**, F1 ≤ **12 percentage points**, FNR ≤ **15 percentage
    points**, FPR ≤ **10 percentage points**, recall ≤ **15 percentage points**;
    wider intervals mean *insufficient evidence*, not a pass.
  - Floors: spam precision ≥ **0.90**, F1 ≥ **0.80** on the frozen test.
  - Coverage minimums: ≥ **300 consented spam** rows; ≥ **150 consented ham**
    per critical legitimate category (OTP, bank/e-wallet alert, delivery);
    ≥ **100 consented ham** per reported language (en, tl, tl-en); **12**
    minimum independent campaign groups globally (the per-slice ≥ 10 rule is
    carried in the registered coverage rationale; the one-shot validator's
    schema is deliberately left unmodified).
  - Builder-check resolution (owner-confirmed): D1/D3 are recorded **decided
    2026-11-28, pending qualified-reviewer countersign** before sealed-test
    setup or pilot start; obtaining the countersign is a plan task.
- **D2 consent/retention:** privacy notice `2026-11-01-v4` ratified as-is;
  retention **90 days** (as implemented); data steward = repository owner
  (acting); labeling = owner + one recruited independent reviewer, owner
  adjudicates until a third reviewer is named.
- **D3 collection authorization:** **one** pilot round authorized contingent on
  (a) rehearsed donation flow, (b) ratified notice, (c) owner-reviewed
  recruitment kit. Scope: 10–30 donors, personal network, no public
  recruitment. HUMAN_REVIEW/DATA_COLLECTION stop conditions apply.
- **D4 transformer spike:** remains archived/local-only; revisited only after a
  consented development set exists.
- **D5 deployment:** local-only this cycle; no public deployment; the macOS
  service remains personal tooling.
- **D6 coverage floor:** ratchet to **80% immediately** (current 81.5%), **85%**
  by end of the next quarter, enforced per-PR thereafter.
- **Public Kaggle corpora:** provenance `public`/`public_licensed`; diagnostic
  value only; excluded from consent workflows; license + single-inbox caveats
  mandatory on every report.

## Workstreams (shape for the plan; the plan owns task detail)

- **W1 Ratification recording:** update OWNER_DECISIONS.md (D1–D6 → decided,
  citing this spec), pre-fill the evaluation-plan template's non-corpus fields,
  register the D1 gates in the readiness doc.
- **W2 T2.1 Tagalog-SMS:** attempt download without credentials; on success,
  normalize + run the public-corpus diagnostic with a message-free report; on
  credential failure (the expected outcome unless the owner exports
  KAGGLE_USERNAME/KAGGLE_KEY beforehand), record the deterministic block
  honestly and ship the attempt report. Diagnostic shape decided at fetch
  time: prefer the PH-inbox internal-split precedent if the CSV carries
  grouping/timestamp evidence, else fall back to the `make eval` path.
  PH-inbox re-evaluation is out of scope (diagnostic already recorded).
- **W3 Human-task kits:** comprehension-session script with a balanced
  fictional fixture set; labeling worksheet bound to the donation export
  schema; recruitment message draft for the pilot round. Pilot labeling starts
  only after the recruited independent reviewer is onboarded; the
  owner-adjudication arrangement is recorded as a dated, expiring exception in
  HUMAN_REVIEW/DATA_COLLECTION.
- **W4 T5 execution:** coverage floor 78 → 80 with ratchet note; fresh canonical
  retrain (`make train` → `spam_detector_v1` + sidecar + README metrics
  lockstep), tagged `v2.0.0` and attested through the provenance workflow;
  timed rollback drill with the current `demo_synthetic` artifact as the
  previous known-good baseline, duration recorded; quarterly ritual dates
  written into ROADMAP.
- **W5 Claims sweep:** run `check_headline_claims.py` + repo hygiene tests over
  all new docs; confirm no accuracy language anywhere.

## What's left to the builder

Task ordering, exact file placement for kits, how to structure the coverage
ratchet commits, and the smoke/test wiring for any new checks — all within the
constraints above.

## Exit criteria

- OWNER_DECISIONS.md shows D1–D6 decided with this spec as the record.
- A Tagalog-SMS diagnostic report exists, or an honest blocked-attempt record.
- Release tag + attestation + timed rollback drill recorded in RETRAINING/DEPLOYMENT docs.
- Comprehension kit, labeling worksheet, and recruitment draft exist and pass
  the claims sweep.
- All gates green; no honesty-string pins changed.
