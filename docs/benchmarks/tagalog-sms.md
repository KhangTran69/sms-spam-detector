# Evaluation: tagalog-sms

> **PUBLIC DATASET** — this result describes only this dataset and does not establish representative real-world Philippine performance.

- Model: `spam_detector_v1-2026-11-28` (SHA-256 `daa8a7c192bf9e02a068f5c60b15bec1cba0db6522b4bf68d69b5b9633815daf`)
- Dataset SHA-256: `cc7506627eec4de0018bd8ede7d22ffbc2febde428c5d72138e0d0f85134fee8`
- Source revision: `7d154cc3b8dba827eecae46856601021cbf6e0ca` (working tree dirty: `True`)
- Evaluated rows: 2739 (1995 ham, 744 spam)

Scores are model outputs, not calibrated fraud probabilities or guarantees that a message is safe.

## Metrics at the model's stored decision threshold

| Metric | Result |
| --- | ---: |
| Decision threshold | 0.5000 |
| Precision | 0.3478 |
| Recall | 0.5591 |
| F1 | 0.4289 |
| ROC-AUC | 0.6355 |
| PR-AUC | 0.3314 |
| False-negative rate | 0.4409 |
| Confusion counts (TP / FP / TN / FN) | 416 / 780 / 1215 / 328 |

Wilson intervals are row-level marginal intervals. Campaign bootstrap intervals resample whole campaign groups; either interval may be unavailable or too wide for a decision. Calibration diagnostics do not establish calibration on future or representative Philippine messages.

## Operating-threshold diagnostic

Configured empirical false-positive-rate bound: 5.0%.
Status: `available_empirical_only`; selected threshold: 0.9997313474501786.
Threshold diagnostics on public/synthetic datasets are descriptive and are not production recommendations.

## Coverage

- Sources: tagalog_sms (2739)
- Languages: unknown (2739)
- Categories: ads (159), gov (52), notifs (1439), otp (504), spam (585)

## PII screening

- Disabled; message text was evaluated as provided in the validated local file.

Verify suspicious requests through trusted official channels. Do not use a low spam score as proof that a message is safe.
