#!/usr/bin/env python
"""Group-isolated recalibration experiment on the CC0 Tagalog corpus.

Message-free record: outputs aggregate calibration statistics only.

Design (contamination-free):
- The corpus is split group-isolated (template-family group keys, seed 43).
  The *incumbent* artifact never trained on any row of this corpus, so both
  the calibration-fit portion and the held-out portion are fully
  out-of-domain for it.
- Sigmoid (Platt) and isotonic calibrators are fitted on the train portion's
  incumbent scores, then applied to the held-out portion. Raw vs calibrated
  Brier/ECE are reported on the identical held-out rows.
- The candidate artifact DID train on ~85% of this corpus (fingerprint-matched
  split), so for the candidate we report calibration only on its truly
  held-out rows (the test-split rows of its training fingerprint) and apply
  the UI-wording rule (ECE <= 0.05 AND >= 30 samples per populated bin).

Run from the repository root:
  python scripts/calibration_experiment.py \
      --incumbent models/releases/v2.0.0/spam_detector_v1.pkl \
      --candidate models/spam_detector_v2_1_candidate.pkl \
      --output docs/benchmarks/v2-1-0-calibration-experiment-20261128.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from src.dataset_loading import load_training_dataset  # noqa: E402
from src.dataset_schema import make_group_key  # noqa: E402
from src.dataset_splits import grouped_splits  # noqa: E402
from src.metrics import calibration_metrics  # noqa: E402
from src.predict import load_model, spam_probabilities  # noqa: E402


def logit(scores: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    clipped = np.clip(scores, eps, 1.0 - eps)
    return np.log(clipped / (1.0 - clipped))


def fit_platt(train_scores: np.ndarray, train_labels: np.ndarray) -> LogisticRegression:
    model = LogisticRegression()
    model.fit(logit(train_scores).reshape(-1, 1), train_labels)
    return model


def apply_platt(model: LogisticRegression, scores: np.ndarray) -> np.ndarray:
    return model.predict_proba(logit(scores).reshape(-1, 1))[:, 1]


def fit_isotonic(train_scores: np.ndarray, train_labels: np.ndarray) -> IsotonicRegression:
    model = IsotonicRegression(out_of_bounds="clip")
    model.fit(train_scores, train_labels)
    return model


def read_corpus(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def calibration_summary(labels: np.ndarray, probabilities: np.ndarray) -> dict:
    label_strings = ["spam" if value else "ham" for value in labels]
    metrics = (
        calibration_metrics(label_strings, probabilities)["calibration"]
        if False
        else calibration_metrics(label_strings, probabilities)
    )
    bins = metrics["bins"]
    populated = [b["count"] for b in bins if b["count"]]
    return {
        "brier": metrics["brier_score"],
        "log_loss": metrics["log_loss"],
        "ece": metrics["expected_calibration_error"],
        "mce": metrics["max_calibration_error"],
        "bins_populated": len(populated),
        "min_bin_n": min(populated) if populated else 0,
        "bin_counts": populated,
    }


def per_category(rows: list[dict], probabilities: np.ndarray, labels: np.ndarray) -> dict:
    """Per-category recall/FPR/calibration error (aggregate counts only)."""
    categories: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        categories.setdefault(row.get("category") or "unknown", []).append(index)
    out = {}
    for cat, indices in sorted(categories.items()):
        cat_labels = labels[indices]
        cat_probs = probabilities[indices]
        n_spam = int((cat_labels == 1).sum())
        n_ham = int((cat_labels == 0).sum())
        entry: dict = {"n": len(indices), "ham": n_ham, "spam": n_spam}
        if n_spam:
            entry["recall"] = float(((cat_probs >= 0.5) & (cat_labels == 1)).sum() / n_spam)
        if n_ham:
            entry["fpr"] = float(((cat_probs >= 0.5) & (cat_labels == 0)).sum() / n_ham)
        if len(indices) >= 10:
            entry["ece"] = calibration_summary(cat_labels, cat_probs)["ece"]
        else:
            entry["ece"] = None
            entry["note"] = "ece omitted below 10 rows"
        out[cat] = entry
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Group-isolated recalibration experiment (message-free).")
    parser.add_argument("--incumbent", default="models/releases/v2.0.0/spam_detector_v1.pkl")
    parser.add_argument("--candidate", default="models/spam_detector_v2_1_candidate.pkl")
    parser.add_argument("--corpus", default="data/external/tagalog-sms.csv")
    parser.add_argument(
        "--candidate-training-supplements",
        nargs="+",
        default=[
            "data/raw/ph_supplement.csv",
            "data/raw/ph_supplement_2.csv",
            "data/raw/ph_supplement_3.csv",
            "data/raw/ph_supplement_4.csv",
            "data/raw/ph_supplement_5.csv",
            "data/external/tagalog-sms.train-excl-conflict.csv",
        ],
    )
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--output", default="docs/benchmarks/v2-1-0-calibration-experiment-20261128.json")
    args = parser.parse_args()

    corpus_rows = read_corpus(ROOT / args.corpus)
    incumbent = load_model(args.incumbent)
    candidate = load_model(args.candidate)

    report: dict = {
        "record": "group-isolated recalibration experiment on the CC0 Tagalog corpus",
        "corpus": {"path": args.corpus, "sha256": sha256(ROOT / args.corpus), "rows": len(corpus_rows)},
        "note": "Aggregate calibration statistics only; no message text.",
        "incumbent_recalibration": {},
        "candidate_heldout_calibration": {},
    }

    # --- Arm 1: incumbent recalibration (fully out-of-domain, no contamination) ---
    messages = [row["message"] for row in corpus_rows]
    labels = np.array([1.0 if row["label"] == "spam" else 0.0 for row in corpus_rows])
    incumbent_scores = np.array(spam_probabilities(incumbent, messages))

    groups = np.array([make_group_key(row["message"], category=str(row.get("category") or "")) for row in corpus_rows])
    unique_groups = sorted(set(groups.tolist()))
    rng = np.random.default_rng(args.seed)
    shuffled = rng.permutation(len(unique_groups))
    holdout_count = max(1, int(round(0.15 * len(unique_groups))))
    heldout_groups = {unique_groups[i] for i in shuffled[:holdout_count]}
    test_mask = np.array([g in heldout_groups for g in groups])
    train_mask = ~test_mask
    if not (
        labels[train_mask].min() == 0
        and labels[train_mask].max() == 1
        and labels[test_mask].min() == 0
        and labels[test_mask].max() == 1
    ):
        report["incumbent_recalibration"] = {
            "status": "degenerate_split",
            "detail": "a class is missing from a portion; rerun with another seed",
        }
    else:
        train_scores, train_labels = incumbent_scores[train_mask], labels[train_mask]
        held_scores, held_labels = incumbent_scores[test_mask], labels[test_mask]
        platt = fit_platt(train_scores, train_labels)
        iso = fit_isotonic(train_scores, train_labels)
        raw = calibration_summary(held_labels, held_scores)
        post_platt = calibration_summary(held_labels, apply_platt(platt, held_scores))
        post_iso = calibration_summary(held_labels, np.asarray(iso.predict(held_scores)))
        held_indices = np.where(test_mask)[0]
        train_indices = np.where(train_mask)[0]
        report["incumbent_recalibration"] = {
            "design": (
                "group-isolated split of the CC0 corpus (template-family keys, seed "
                f"{args.seed}, ~15% of groups held out); calibrators fitted on the train "
                "portion's incumbent scores only, applied to the held-out portion"
            ),
            "train_rows": int(train_mask.sum()),
            "heldout_rows": int(test_mask.sum()),
            "train_group_count": int(len(unique_groups) - holdout_count),
            "heldout_group_count": int(holdout_count),
            "raw": raw,
            "post_platt": post_platt,
            "post_isotonic": post_iso,
            "per_category_raw_heldout": per_category([corpus_rows[i] for i in held_indices], held_scores, held_labels),
            "per_category_train": per_category([corpus_rows[i] for i in train_indices], train_scores, train_labels),
        }

    # --- Arm 2: candidate raw calibration on its truly held-out rows ---
    full_dataset = load_training_dataset("data/raw/spam.csv", args.candidate_training_supplements)
    split = grouped_splits(full_dataset, val_size=0.15, test_size=0.15, seed=42, split_by="group")
    fingerprint = split.group_fingerprint(full_dataset.groups)
    test_frame = full_dataset.frame.iloc[split.test_idx]
    tagalog = test_frame[test_frame["source"].astype(str).str.contains("tagalog", case=False)]
    cand_rows = tagalog.to_dict("records")
    cand_labels = np.array([1.0 if row["label"] == "spam" else 0.0 for row in cand_rows])
    cand_scores = np.array(spam_probabilities(candidate, [row["message"] for row in cand_rows]))
    cand_summary = calibration_summary(cand_labels, cand_scores)
    ui_rule = {
        "ece_le_0.05": bool(cand_summary["ece"] <= 0.05),
        "min_populated_bin_ge_30": bool(cand_summary["min_bin_n"] >= 30),
        "keep_uncalibrated_wording": not (cand_summary["ece"] <= 0.05 and cand_summary["min_bin_n"] >= 30),
    }
    report["candidate_heldout_calibration"] = {
        "heldout_rows": len(cand_rows),
        "labels": {"ham": int((cand_labels == 0).sum()), "spam": int((cand_labels == 1).sum())},
        "group_fingerprint": fingerprint,
        "fingerprint_matches_recorded_benchmark": fingerprint
        == "8c4b3a3344a75cf36e1ed74c07c8aaaeda077c72c9f9a713dc6ac35c020dec2c",
        "raw": cand_summary,
        "per_category": per_category(cand_rows, cand_scores, cand_labels),
        "ui_wording_rule": ui_rule,
        "contamination_note": (
            "No clean calibration-fit data exists for the candidate beyond its held-out "
            "rows, so no post-hoc calibrator is fitted for it here; fitting one on the "
            "candidate's own training rows would not be held-out evidence."
        ),
    }

    out = ROOT / args.output
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report written: {out}")
    print(
        json.dumps({k: report[k] for k in ("incumbent_recalibration", "candidate_heldout_calibration")}, indent=1)[
            :2600
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
