# v2.1.0 candidate — gates NOT met — no release (2026-11-28)

Message-free record: no SMS content, sender metadata, or corpus text is quoted
here. Machine-readable numbers: [v2-1-0-gates-20261128.json](v2-1-0-gates-20261128.json).

## What was run

The winning recipe from the transfer experiment
([tagalog-transfer-experiment-20261128.json](tagalog-transfer-experiment-20261128.json))
was reproduced exactly and turned into a candidate artifact:

- **Benchmark reproduction**: `make benchmark` with the canonical recipe
  (UCI base + 5 synthetic supplements + 2,738 Tagalog-SMS rows, 1 cross-source
  label conflict excluded, base label wins). Group-isolated split fingerprint
  `8c4b3a33…` matches the recorded benchmark; test-split precision 0.934 /
  recall 0.899 / F1 0.916 — identical to the recorded run.
- **Candidate artifact**: fresh `make train` (same supplements, seed 42,
  val 0.15 / test 0.15, group-isolated, `cv-robust` threshold policy,
  target precision 0.95 / min recall 0.8). The cv-robust check rejected the
  validation fallback threshold (fold gains negative), so the served threshold
  is **0.50**. `model_version` `spam_detector_v1-2026-11-28-v2.1.0-candidate`.
  Split fingerprint matches the benchmark (`group_leakage 0`), so the held-out
  evaluation below never touches the candidate's training rows.
- **Incumbent**: the attested v2.0.0 release artifact
  (`spam_detector_v1-2026-11-28`, sha256 `daa8a7c1…`, threshold 0.50).

Both artifacts were scored on the same three frozen evaluation sets at their
own decision thresholds (0.50 for both). The incumbent's real-corpus
diagnostic was first reproduced bit-identically
(fp 780 / tp 416 / ECE 0.307) against the same corpus snapshot
(sha256 `cc750662…`), verifying the harness before any comparison.

## The preregistered gate set and verdict

Gate (from PH_FIELD_EVALUATION_READINESS, applied here per the gap-closure
brief): each critical legitimate category on **held-out real data** must show
false-positive rate ≤ 5% **and** Wilson 95% upper bound ≤ 8%.

| Gate (new artifact, real data) | Support | FP | FPR | Wilson 95% | Verdict |
|---|---:|---:|---:|---|---|
| OTP (Tagalog held-out groups) | 57 ham | 4 | **7.0%** | [2.8%, **16.7%**] | **not_met** |
| bank_alert (real data) | — | — | — | — | **insufficient_evidence** (0 real rows in any real frozen set) |
| delivery (real data) | — | — | — | — | **insufficient_evidence** (0 real rows) |
| OTP (synthetic holdout, diagnostic only) | 11 ham | 0 | 0% | [0%, 26.5%] | not evidence |

**Gates are NOT met. No release. No version bump. No readiness claim.**

## Measured comparison, old vs new (same frozen rows)

| Frozen set | Model | Precision | Recall | FPR | FNR | ECE | Brier |
|---|---|---:|---:|---:|---:|---:|---:|
| Tagalog held-out groups (372 rows, real) | v2.0.0 incumbent | 0.546 | 0.696 | 21.9% | 30.4% | 0.173 | 0.208 |
| | **v2.1.0 candidate** | **0.890** | **0.951** | **4.4%** | **4.9%** | **0.031** | **0.038** |
| PH-inbox (1,664 rows, real, different domain) | v2.0.0 incumbent | 0.977 | 43.0% | 24.6% | 57.0% | 0.495 | 0.416 |
| | **v2.1.0 candidate** | **0.991** | **57.1%** | **12.3%** | **42.9%** | **0.404** | **0.326** |
| Synthetic PH holdout (264 rows, diagnostic) | v2.0.0 incumbent | 0.969 | 89.3% | 3.2% | 10.7% | 0.048 | 0.061 |
| | **v2.1.0 candidate** | 0.991 | 82.1% | **0.8%** | 17.9% | 0.103 | 0.076 |

Reading, stated plainly:

1. **On the candidate's own domain (Tagalog held-out), the recipe improvement
   is large and replicated**: precision +0.34, FPR 21.9% → 4.4%, OTP false
   positives 11 → 4 of 57. The transfer-experiment numbers reproduce exactly
   (tp 97 / fp 12 / fn 5).
2. **Real-data transfer across corpora is only partial**: on the PH-inbox
   corpus — a different publisher's inbox, 1,599 spam / 65 ham — the candidate
   misses 42.9% of spam (686 of 1,599). Same-domain training data does not
   fully transfer to a different single-inbox distribution.
3. **A synthetic-only regression is flagged** (RETRAINING §3): candidate
   bank_phishing false-negative rate 54.2% (13/24) vs incumbent 0% on the
   synthetic holdout; synthetic recall drops 89.3% → 82.1%. Synthetic numbers
   are diagnostic, but this regression is real in the artifact and must be
   resolved before any future promotion. Candidate OTP-theft misses are the
   other main synthetic recall loss.
4. **Notifs (legitimate notifications) is the one critical-adjacent category
   that certifies on real data**: 7 FP / 202 ham = 3.5% FPR, Wilson upper 7.0%
   ≤ 8% (incumbent: 44 FP / 202 = 21.8%).

## Supplementary per-category detail (new artifact, real sets)

| Category | Set | n ham | FP | FPR | Wilson 95% | Gate-level reading |
|---|---|---:|---:|---:|---|---|
| otp | Tagalog held-out | 57 | 4 | 7.0% | [2.8%, 16.7%] | not_met |
| notifs | Tagalog held-out | 202 | 7 | 3.5% | [1.7%, 7.0%] | met |
| gov | Tagalog held-out | 11 | 1 | 9.1% | [1.6%, 37.7%] | insufficient support |
| gov | PH-inbox | 55 | 7 | 12.7% | [6.3%, 24.0%] | not_met |
| notifs | PH-inbox | 10 | 1 | 10.0% | [1.8%, 40.4%] | insufficient support |

## Power calculation — what WOULD be needed (pilot recruitment target)

Method: smallest per-category legitimate support n such that the Wilson 95%
**upper bound** certifies ≤ 8% while the point estimate stays at the stated
rate (z = 1.96; FP count fixed at the stated rate of n).

| Observed point FPR | Rows needed per category | FP budget |
|---|---:|---:|
| 5% (gate ceiling) | **320** | ≤ 16 |
| 4% | **200** | ≤ 8 |
| 3% | **200** | ≤ 6 |
| 1% | **100** | ≤ 1 |
| 0% | 45 | 0 |

Specific consequences, using the measured rates:

- **OTP**: at the observed 7.0% (4/57), **no sample size passes** — a 7% point
  estimate can never satisfy a ≤5% point gate. The model must first reduce
  real-data OTP false positives below 5%; then **≥200 OTP rows (≤8 FP)**, and
  **≥320 rows (≤16 FP)** if the rate sits exactly at 5%. This is the pilot's
  quantified OTP recruitment target.
- **bank_alert / delivery**: zero real rows today. The pilot needs **≥200 rows
  per category** if the model holds a ≤4% rate on them, and the ratified
  150-row coverage minimum
  (docs/templates/consented-evaluation-plan.json) is **not by itself
  sufficient** to certify the ≤8% Wilson upper bound at a 5% observed rate
  (needs ≥320). Coverage minimums certify interval width (FPR width 0.10 at
  n≈150), not the upper-bound gate.
- **notifs**: already certified at 202 rows — the pilot only needs to sustain
  this rate.
- **gov**: 12.7% on 55 PH-inbox rows would need a model-side improvement
  before sample size matters (a 12.7% rate never passes).

## What was NOT done, on purpose

- No version bump, no tag, no GitHub release: the gates failed on held-out
  real data.
- No threshold retuning to chase the gates: the candidate's threshold comes
  from validation data only (cv-robust, adopted=False, 0.50) — unchanged.
- No sealed-test interaction: the one-shot discipline is untouched.

## Next action (highest leverage)

Pilot recruitment with the quantified targets above (OTP ≥200, bank_alert
≥200, delivery ≥200 legitimate rows each, plus ≥300 spam_top3 per the
registered coverage minimums), **combined with** a model-side reduction of
real-data OTP and gov false positives and the bank_phishing synthetic
regression, re-run through this same gate set.
