"""Evaluation helpers and Philippine example checks."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import classification_report, confusion_matrix, ConfusionMatrixDisplay, precision_recall_fscore_support, precision_score
from sklearn.model_selection import train_test_split

from src.features import messages_to_frame
from src.predict import load_model, predict_message
from src.train import DEFAULT_DATA, DEFAULT_SUPPLEMENT, RANDOM_STATE, TEST_SIZE, load_dataset, load_training_data

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "spam_detector_v1.pkl"
DEFAULT_HOLDOUT = ROOT / "data" / "raw" / "ph_holdout.csv"
DEFAULT_PLOT = ROOT / "data" / "processed" / "confusion_matrix.png"
THRESHOLDS = (0.3, 0.5, 0.6, 0.7, 0.8, 0.9)

# Diagnostic examples from the project brief. They are not part of any
# training/supplement file, so predictions show generalized pattern behavior.
PHILIPPINE_EXAMPLES = [
    "Nag-claim ka ng ₱500,000 sa GMA Kapuso Foundation. Call now 09123456789",
    "BDO: Your account is locked. Verify here: http://bit.ly/fakebdo",
    "Congrats! You won ₱1M from PCSO. Text your name and address to 0922xxxxxxx",
]


def _spam_probability(model, messages: list[str]) -> list[float]:
    probabilities = model.predict_proba(messages_to_frame(messages))
    classes = list(model.classes_)
    spam_idx = classes.index("spam")
    return [float(p[spam_idx]) for p in probabilities]


def evaluate(
    data_path=DEFAULT_DATA,
    supplement_path=DEFAULT_SUPPLEMENT,
    model_path=DEFAULT_MODEL,
    holdout_path=DEFAULT_HOLDOUT,
    plot_path=DEFAULT_PLOT,
):
    model = load_model(model_path)
    messages, labels = load_training_data(data_path, supplement_path)

    # Replicate the training split so metrics reflect the held-out test set only.
    X_train, X_test, y_train, y_test = train_test_split(
        messages, labels, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=labels
    )
    predictions = model.predict(messages_to_frame(X_test))

    print(f"\n=== Test split ({len(y_test)} messages) ===")
    print(classification_report(y_test, predictions, zero_division=0))
    print(
        f"Spam precision (avoid flagging legitimate messages): "
        f"{precision_score(y_test, predictions, pos_label='spam', zero_division=0):.4f}"
    )

    matrix = confusion_matrix(y_test, predictions, labels=["ham", "spam"])
    display = ConfusionMatrixDisplay(matrix, display_labels=["ham", "spam"])
    display.plot(cmap="Blues", values_format="d")
    if plot_path:
        Path(plot_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(plot_path, bbox_inches="tight")
        print(f"Confusion matrix saved to {plot_path}")
    plt.close(display.figure_)

    # Precision-focused threshold sweep: a higher cut-off trades recall for
    # fewer false positives on legitimate OTP/bank messages.
    print("\n=== Threshold sweep (spam precision focus) ===")
    spam_probabilities = _spam_probability(model, X_test)
    print(f"{'threshold':>9} | {'precision':>9} | {'recall':>7} | {'FP ham->spam':>12} | {'FN spam->ham':>12}")
    recommended = None
    for threshold in THRESHOLDS:
        flagged = [p >= threshold for p in spam_probabilities]
        precision, recall, _, _ = precision_recall_fscore_support(
            y_test, ["spam" if f else "ham" for f in flagged], labels=["spam"], zero_division=0
        )
        fp = sum(1 for truth, p in zip(y_test, spam_probabilities) if truth == "ham" and p >= threshold)
        fn = sum(1 for truth, f in zip(y_test, flagged) if truth == "spam" and not f)
        if recommended is None and precision[0] >= 0.99:
            recommended = threshold
        print(f"{threshold:>9.2f} | {precision[0]:>9.4f} | {recall[0]:>7.4f} | {fp:>12d} | {fn:>12d}")
    if recommended is not None:
        print(f"Smallest threshold with spam precision >= 0.99: {recommended:.2f}")
    else:
        print("No tested threshold reaches spam precision >= 0.99; collect more legitimate ham examples.")

    # Optional labeled Philippine holdout, disjoint from training data.
    if holdout_path and Path(holdout_path).exists():
        holdout_messages, holdout_labels = load_dataset(holdout_path)
        holdout_predictions = model.predict(messages_to_frame(holdout_messages))
        print("\n=== Philippine holdout ===")
        print(classification_report(holdout_labels, holdout_predictions, zero_division=0))
        otp_flagged = 0
        for message, truth, prediction in zip(holdout_messages, holdout_labels, holdout_predictions):
            marker = "OK " if truth == prediction else "WRONG"
            is_otp_ham = truth == "ham" and any(word in message.lower() for word in ("otp", "code", "one-time"))
            if is_otp_ham and prediction == "spam":
                otp_flagged += 1
                marker = "OTP-FP"
            print(f"[{marker}] {truth:>4} -> {prediction:<4} {message}")
        print(f"Legit OTP/code messages falsely flagged: {otp_flagged}")

    print("\n=== Philippine scam examples from the project brief ===")
    for message in PHILIPPINE_EXAMPLES:
        result = predict_message(message, model=model)
        print(f"{result['prediction']:>4} (p={result['probability']:.3f}) flags={result['flags']} | {message}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument(
        "--supplement",
        nargs="*",
        default=[str(path) for path in DEFAULT_SUPPLEMENT],
        help="Philippine supplement CSV(s); pass 'none' to disable all",
    )
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT), help="Philippine holdout CSV; pass 'none' to disable")
    parser.add_argument("--plot", default=str(DEFAULT_PLOT))
    args = parser.parse_args()
    supplements = [a for a in args.supplement if a.lower() != "none"]
    evaluate(
        args.data,
        supplements or None,
        args.model,
        None if args.holdout.lower() == "none" else args.holdout,
        args.plot,
    )
