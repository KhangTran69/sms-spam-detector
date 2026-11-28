# Public-corpus prior-shift sensitivity (2026-11-29)

This is an aggregate-only calculation from
[v2-1-0-gates-20261128.json](v2-1-0-gates-20261128.json), Git blob
`8e9518711ebf06152f304d6f861fa3908f4b2374`. The two public diagnostic sets
are kept separate. No underlying message corpus, model artifact, or sealed
test was opened. Both stored thresholds remain 0.50.

```bash
python -m src.prior_shift
```

The command returns a source SHA-256, observed confusion counts, and
hypothetical scenarios for spam prevalences of 1%, 5%, 10%, 25% and 50%.
For prevalence p, observed true-positive rate r, and observed false-positive
rate f, expected true positives per 1,000 are 1,000 × p × r, expected false
positives are 1,000 × (1 − p) × f, and expected precision is their ratio
TP / (TP + FP). Expected false negatives are 1,000 × p × (1 − r).

## Illustrative 5% prevalence scenario

The following values are calculated from the published confusion counts,
rounded for display. They are conditional expectations, not observed field
results.

| Public diagnostic set | Artifact | Observed ham / spam | Projected precision | Expected FP / 1,000 | Expected FN / 1,000 |
|---|---|---:|---:|---:|---:|
| Held-out Tagalog groups | Incumbent | 270 / 102 | 14.4% | 207.59 | 15.20 |
| Held-out Tagalog groups | Candidate | 270 / 102 | 53.0% | 42.22 | 2.45 |
| PH inbox | Incumbent | 65 / 1,599 | 8.4% | 233.85 | 28.52 |
| PH inbox | Candidate | 65 / 1,599 | 19.6% | 116.92 | 21.45 |

The two sources have substantially different observed class mixes. Precision
depends on class prevalence even if the within-class error rates remain fixed.
The PH inbox has only 65 ham examples; the measured false-positive rate is
fragile. Neither these assumptions nor the hypothetical prevalence are
validated for the Philippines. Campaign/donor dependence and interval
uncertainty are not propagated by this simple sensitivity calculation.

The candidate's OTP and coverage gates remain unmet. This analysis does not
recommend a threshold, establish field performance, or support promotion.
A diagnostic class-weighted training experiment remains separate: use only
approved public development data, group-isolated splits, predeclared metrics
and fixed test membership. Do not optimize against previously reported frozen
sets; no consented test may be opened for exploratory work.
