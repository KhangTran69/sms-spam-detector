#!/usr/bin/env python
"""Score two model artifacts on frozen evaluation sets and report gates.

Message-free by construction: outputs aggregate counts, rates, and Wilson
intervals only — never message text. Data files are referenced by SHA-256, not
embedded. Run from the repository root:

  python scripts/evaluate_frozen_gates.py \
      --old-model models/releases/v2.0.0/spam_detector_v1.pkl \
      --new-model models/spam_detector_v2_1_candidate.pkl \
      --output docs/benchmarks/v2-1-0-gates-20261128.json

The Tagalog held-out set is reconstructed from the fingerprint-matched
group-isolated split of the candidate's exact training dataset, so the held-out
rows were never trained on by the candidate (verified against the recorded
group_fingerprint) and are entirely out-of-domain for the incumbent.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dataset_loading import load_training_dataset  # noqa: E402
from src.dataset_splits import grouped_splits  # noqa: E402
from src.predict import load_model, spam_probabilities  # noqa: E402

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1.0 + z * z / n
    center = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (center - spread) / denom), min(1.0, (center + spread) / denom))


def rate(k: int, n: int) -> float:
    return k / n if n else float("nan")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score_rows(rows: list[dict], bundle, threshold: float) -> dict:
    """Aggregate TP/FP/FN/TN, per-category FPR/FNR, and Wilson intervals."""
    probabilities = spam_probabilities(bundle, [row["message"] for row in rows])
    tp = fp = tn = fn = 0
    fp_by_cat: Counter = Counter()
    fn_by_cat: Counter = Counter()
    ham_by_cat: Counter = Counter()
    spam_by_cat: Counter = Counter()
    for row, prob in zip(rows, probabilities):
        predicted_spam = prob >= threshold
        is_spam = row["label"] == "spam"
        category = row.get("category") or "unknown"
        if is_spam:
            spam_by_cat[category] += 1
            if predicted_spam:
                tp += 1
            else:
                fn += 1
                fn_by_cat[category] += 1
        else:
            ham_by_cat[category] += 1
            if predicted_spam:
                fp += 1
                fp_by_cat[category] += 1
            else:
                tn += 1
    n_ham = fp + tn
    n_spam = tp + fn
    prec_lo, prec_hi = wilson(tp, tp + fp)
    rec_lo, rec_hi = wilson(tp, n_spam)
    fpr_lo, fpr_hi = wilson(fp, n_ham)
    fnr_lo, fnr_hi = wilson(fn, n_spam)
    categories = {}
    for cat in sorted(set(ham_by_cat) | set(spam_by_cat)):
        cat_fp, cat_fn = fp_by_cat[cat], fn_by_cat[cat]
        cat_ham, cat_spam = ham_by_cat[cat], spam_by_cat[cat]
        entry: dict = {
            "ham": cat_ham,
            "spam": cat_spam,
            "false_positives": cat_fp,
            "false_negatives": cat_fn,
        }
        if cat_ham:
            lo, hi = wilson(cat_fp, cat_ham)
            entry["fpr"] = rate(cat_fp, cat_ham)
            entry["fpr_wilson95"] = [lo, hi]
        if cat_spam:
            lo, hi = wilson(cat_fn, cat_spam)
            entry["fnr"] = rate(cat_fn, cat_spam)
            entry["fnr_wilson95"] = [lo, hi]
        categories[cat] = entry
    return {
        "decision_threshold": threshold,
        "n": n_ham + n_spam,
        "ham": n_ham,
        "spam": n_spam,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "precision": rate(tp, tp + fp),
        "precision_wilson95": [prec_lo, prec_hi],
        "recall": rate(tp, n_spam),
        "recall_wilson95": [rec_lo, rec_hi],
        "fpr": rate(fp, n_ham),
        "fpr_wilson95": [fpr_lo, fpr_hi],
        "fnr": rate(fn, n_spam),
        "fnr_wilson95": [fnr_lo, fnr_hi],
        "by_category": categories,
    }


def calibration(rows: list[dict], bundle, n_bins: int = 10) -> dict:
    probabilities = spam_probabilities(bundle, [row["message"] for row in rows])
    labels = [1.0 if row["label"] == "spam" else 0.0 for row in rows]
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / len(labels)
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, y in zip(probabilities, labels):
        bins[min(int(p * n_bins), n_bins - 1)].append((p, y))
    ece = 0.0
    populated = []
    for b in bins:
        if not b:
            continue
        conf = sum(p for p, _ in b) / len(b)
        acc = sum(y for _, y in b) / len(b)
        ece += (len(b) / len(labels)) * abs(conf - acc)
        populated.append(len(b))
    return {
        "brier": brier,
        "ece": ece,
        "bins_populated": len(populated),
        "min_bin_n": min(populated) if populated else 0,
        "bin_counts": populated,
    }


def read_csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate evaluation on frozen sets (message-free report).")
    parser.add_argument("--old-model", required=True)
    parser.add_argument("--new-model", required=True)
    parser.add_argument("--base-data", default="data/raw/spam.csv")
    parser.add_argument(
        "--training-supplements",
        nargs="+",
        default=[
            "data/raw/ph_supplement.csv",
            "data/raw/ph_supplement_2.csv",
            "data/raw/ph_supplement_3.csv",
            "data/raw/ph_supplement_4.csv",
            "data/raw/ph_supplement_5.csv",
            "data/external/tagalog-sms.train-excl-conflict.csv",
        ],
        help="The new model's exact training supplement list (for split reconstruction).",
    )
    parser.add_argument("--ph-inbox-csv", default="data/external/ph-spam-marketing-sms.csv")
    parser.add_argument("--synthetic-holdout-csv", default="data/raw/ph_holdout.csv")
    parser.add_argument(
        "--expected-fingerprint", default="8c4b3a3344a75cf36e1ed74c07c8aaaeda077c72c9f9a713dc6ac35c020dec2c"
    )
    parser.add_argument("--critical-categories", default="otp,bank_alert,bank_phishing,delivery,notifs,gov")
    parser.add_argument("--output", default="docs/benchmarks/v2-1-0-gates-20261128.json")
    args = parser.parse_args()

    old_bundle = load_model(args.old_model)
    new_bundle = load_model(args.new_model)
    old_threshold = float(old_bundle.threshold)
    new_threshold = float(new_bundle.threshold)

    report: dict = {
        "record": "v2.1.0-candidate preregistered gate evaluation on frozen sets",
        "generated_note": "Aggregate counts, rates, and Wilson 95% intervals only; no message text.",
        "models": {
            "old": {
                "path": args.old_model,
                "sha256": sha256(ROOT / args.old_model),
                "decision_threshold": old_threshold,
            },
            "new": {
                "path": args.new_model,
                "sha256": sha256(ROOT / args.new_model),
                "decision_threshold": new_threshold,
            },
        },
        "frozen_sets": {},
    }

    # Set 1: Tagalog held-out groups — reconstruct the candidate's group-isolated
    # split and keep only the test-split Tagalog rows.
    dataset = load_training_dataset(args.base_data, args.training_supplements)
    split = grouped_splits(dataset, val_size=0.15, test_size=0.15, seed=42, split_by="group")
    fingerprint = split.group_fingerprint(dataset.groups)
    frame = dataset.frame
    test_frame = frame.iloc[split.test_idx]
    tagalog_mask = test_frame["source"].astype(str).str.contains("tagalog", case=False)
    tagalog_frame = test_frame[tagalog_mask]
    report["tagalog_heldout_split"] = {
        "method": split.method,
        "seed": split.seed,
        "group_fingerprint": fingerprint,
        "fingerprint_matches_recorded_benchmark": fingerprint == args.expected_fingerprint,
        "heldout_rows": int(len(tagalog_frame)),
        "heldout_labels": {k: int(v) for k, v in Counter(tagalog_frame["label"]).items()},
        "note": (
            "Held-out rows come from the test portion of the same fingerprint-matched "
            "group-isolated split the candidate trained on; they were never trained on by "
            "the candidate and are entirely out-of-domain for the incumbent."
        ),
    }
    tagalog_rows = tagalog_frame.to_dict("records")

    ph_rows = read_csv_rows(ROOT / args.ph_inbox_csv)
    synthetic_rows = read_csv_rows(ROOT / args.synthetic_holdout_csv)

    tagalog_supplement_sha = sha256(ROOT / "data/external/tagalog-sms.train-excl-conflict.csv")
    for name, rows, source_path in (
        ("tagalog_heldout_groups", tagalog_rows, None),
        ("ph_inbox", ph_rows, ROOT / args.ph_inbox_csv),
        ("synthetic_holdout", synthetic_rows, ROOT / args.synthetic_holdout_csv),
    ):
        if name == "tagalog_heldout_groups":
            provenance = {
                "derived_from_training_dataset": True,
                "base_sha256": sha256(ROOT / args.base_data),
                "tagalog_supplement_sha256": tagalog_supplement_sha,
                "membership_binding": "group_fingerprint in tagalog_heldout_split",
            }
        else:
            provenance = {"sha256": sha256(source_path)}
        entry: dict = dict(provenance)
        for side, bundle, threshold in (
            ("old_model", old_bundle, old_threshold),
            ("new_model", new_bundle, new_threshold),
        ):
            scored = score_rows(rows, bundle, threshold)
            scored["calibration"] = calibration(rows, bundle)
            entry[side] = scored
        report["frozen_sets"][name] = entry

    # Critical-category gates on the NEW artifact, real held-out sets only.
    critical = [c.strip() for c in args.critical_categories.split(",")]
    verdicts = {}
    for set_name, entry in report["frozen_sets"].items():
        if set_name == "synthetic_holdout":
            continue
        for cat in critical:
            stats = entry["new_model"]["by_category"].get(cat)
            if not stats or not stats.get("ham"):
                continue
            lo, hi = stats.get("fpr_wilson95", (float("nan"), float("nan")))
            verdicts[f"{set_name}/{cat}"] = {
                "n_ham": stats["ham"],
                "false_positives": stats["false_positives"],
                "fpr": stats.get("fpr"),
                "fpr_wilson95": stats.get("fpr_wilson95"),
                "gate_fpr_le_5pct": bool(stats.get("fpr") is not None and stats["fpr"] <= 0.05),
                "gate_wilson_upper_le_8pct": bool(hi == hi and hi <= 0.08),
            }
    report["critical_category_gates"] = verdicts
    report["gates_all_met"] = bool(verdicts) and all(
        v["gate_fpr_le_5pct"] and v["gate_wilson_upper_le_8pct"] for v in verdicts.values()
    )

    out = ROOT / args.output
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report written: {out}")
    summary = {
        "gates_all_met": report["gates_all_met"],
        "tagalog_fingerprint_match": report["tagalog_heldout_split"]["fingerprint_matches_recorded_benchmark"],
        "verdicts": verdicts,
    }
    print(json.dumps(summary, indent=1)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
