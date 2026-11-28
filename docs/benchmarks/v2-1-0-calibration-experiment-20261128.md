# Recalibration experiment on the CC0 Tagalog corpus — 2026-11-28

Message-free record: no SMS content or corpus text is quoted here.
Machine-readable numbers:
[v2-1-0-calibration-experiment-20261128.json](v2-1-0-calibration-experiment-20261128.json).

## Question

The incumbent's displayed probability is close to meaningless on real Tagalog
traffic (full-corpus diagnostic ECE 0.307). Can post-hoc calibration fix it on
held-out real rows, and is the v2.1.0 candidate's calibration good enough to
change the "uncalibrated model score" UI wording?

## Design (contamination-controlled)

- **Incumbent arm**: the CC0 corpus (2,739 rows, sha256 `cc750662…`) is split
  group-isolated by template-family keys (seed 43): 2,380 rows / 1,325 groups
  for calibration fitting, 359 rows / 234 groups held out. The incumbent never
  trained on any row of this corpus, so both portions are fully out-of-domain.
  Platt (logit + logistic regression) and isotonic calibrators are fitted on
  train-portion incumbent scores only, then applied to held-out scores.
- **Candidate arm**: the candidate trained on ~85% of this corpus, so no
  post-hoc calibrator is fitted for it (fitting on its own training rows would
  not be held-out evidence). Its calibration is reported on its 372 truly
  held-out rows (fingerprint `8c4b3a33…` — matches the recorded benchmark).

## Result: incumbent (359 held-out rows)

| Variant | Brier | ECE | Max cal. error | Populated bins | Min bin n |
|---|---:|---:|---:|---:|---:|
| Raw incumbent scores | 0.304 | **0.287** | 0.572 | 10 | 2 |
| Post-Platt | 0.211 | 0.090 | 0.209 | 3 | 21 |
| Post-isotonic | **0.198** | **0.082** | **0.108** | 3 | 35 |

- Recalibration **helps materially** (ECE 0.287 → 0.082, Brier 0.304 → 0.198)
  but **does not reach the registered ≤ 0.05 bar**. Even after post-hoc
  calibration, the incumbent's displayed percentage would still not be
  trustworthy on real data.
- Post-calibration scores collapse into 3 bins: ranking within the middle of
  the scale is coarse; the calibrated output would be quantized, not a
  smooth probability.

## Result: v2.1.0 candidate (372 truly held-out rows)

- Raw Brier **0.038**, ECE **0.031**, 10 populated bins, min bin n = **3**.
- **UI-wording rule** (held-out ECE ≤ 0.05 AND ≥ 30 samples per populated
  bin): ECE passes, bin support fails (3 << 30) → **the "uncalibrated model
  score" UI wording stays**. No claim of calibrated probabilities is made.

## Per-category breakdown (worst spots)

Incumbent, raw scores, held-out portion (rows ≥ 10 only; smaller rows carry
wide intervals and are listed in the JSON without ECE):

| Category | n | ham/spam | FPR or recall | ECE |
|---|---:|---|---|---:|
| notifs | 165 | 165/0 | FPR 47.9% | **0.500** |
| spam | 95 | 0/95 | recall 64.2% | **0.323** |
| ads | 23 | 0/23 | recall 82.6% | 0.205 |
| otp | 70 | 70/0 | FPR 10.0% | 0.141 |

Worst-calibrated and worst-recall both sit on the same two categories:
legitimate notifications (over-flagged and over-confident) and the generic
spam category (missed and over-confident the other way).

Candidate, raw scores, 372 held-out rows:

| Category | n | ham/spam | FPR or recall | ECE |
|---|---:|---|---|---:|
| ads | 22 | 0/22 | recall 86.4% | 0.192 |
| otp | 57 | 57/0 | FPR 7.0% | 0.084 |
| spam | 80 | 0/80 | recall 97.5% | 0.057 |
| notifs | 202 | 202/0 | FPR 3.5% | 0.051 |
| gov | 11 | 11/0 | FPR 9.1% | 0.163 (small support) |

## Conclusions (no claims beyond the data)

1. The incumbent's real-data miscalibration is structural, not cosmetic:
   post-hoc calibration on 2,380 real rows only halves ECE (0.287 → 0.082),
   remaining above the registered bar.
2. Real training data — not recalibration — is what moved calibration:
   the candidate's raw held-out ECE (0.031) beats the recalibrated incumbent
   (0.082) with no calibrator at all.
3. Neither artifact meets the registered bar for presenting percentages as
   calibrated probabilities (candidate fails the ≥30/bin support clause).
   The user-facing wording stays "uncalibrated model score" everywhere.
4. If a future artifact ever meets both clauses on held-out rows, the wording
   change must go through the claims-sweep tests and the UI contract tests —
   not a copy edit.
