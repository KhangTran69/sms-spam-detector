"""Cross-validated model selection, calibration, and threshold policy.

The primary classifier is chosen by group-aware cross-validated spam F1 on the
training split only. Candidates are class-balanced LogisticRegression and
LinearSVC models over a small regularization grid. The chosen model is wrapped
in ``CalibratedClassifierCV`` (sigmoid) so the served ``spam_probability`` is a
calibrated score rather than a raw decision value.

The decision threshold defaults to 0.5. A validation-tuned threshold replaces
it only when out-of-fold training predictions show a robust gain: F1 must
improve in every fold and by at least ``MIN_ROBUST_F1_GAIN`` on average.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from src.features import make_feature_transformer, make_model

DEFAULT_CV_FOLDS = 5
DEFAULT_THRESHOLD = 0.5
MIN_ROBUST_F1_GAIN = 0.01
LOGISTIC_C_GRID = (0.3, 1.0, 3.0, 10.0, 30.0)
SVM_C_GRID = (0.03, 0.1, 0.3, 1.0)
SGD_ALPHA_GRID = (1e-4, 1e-3, 1e-2)
CALIBRATION_METHOD = "sigmoid"


def candidate_classifiers(seed: int) -> list[tuple[str, Any]]:
    """Return (name, unfitted estimator) pairs compared by cross-validation."""
    candidates: list[tuple[str, Any]] = []
    for c_value in LOGISTIC_C_GRID:
        candidates.append(
            (
                f"logistic_regression(C={c_value:g})",
                LogisticRegression(
                    C=c_value, class_weight="balanced", max_iter=5000, solver="liblinear", random_state=seed
                ),
            )
        )
    for c_value in SVM_C_GRID:
        candidates.append(
            (
                f"linear_svm(C={c_value:g})",
                LinearSVC(C=c_value, class_weight="balanced", max_iter=20000, random_state=seed),
            )
        )
    for alpha in SGD_ALPHA_GRID:
        candidates.append(
            (
                f"sgd_classifier(alpha={alpha:g})",
                SGDClassifier(
                    loss="log_loss",
                    penalty="l2",
                    alpha=alpha,
                    class_weight="balanced",
                    max_iter=2000,
                    random_state=seed,
                ),
            )
        )
    return candidates


def cv_splits(
    labels: Sequence[str],
    groups: Sequence[Any] | None,
    *,
    n_splits: int,
    seed: int,
    require_group_isolation: bool = False,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Build stratified folds, requiring disjoint groups when requested."""
    y = np.asarray(labels)
    if len(y) < 2:
        raise ValueError("Cross-validation needs at least two labeled examples.")
    if groups is not None and len(groups) != len(y):
        raise ValueError("groups must contain one identifier per labeled example.")
    minority = int(min(np.sum(y == "spam"), np.sum(y == "ham")))
    folds = max(2, min(n_splits, minority))
    index = np.zeros(len(y))
    if groups is not None:
        unique_groups = len(set(groups))
        folds = min(folds, unique_groups)
        if folds < 2:
            if require_group_isolation:
                raise ValueError("Group-isolated cross-validation needs at least two distinct campaign groups.")
        else:
            try:
                splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
                splits = list(splitter.split(index, y, groups=np.asarray(groups)))
                if all(len(set(y[test])) == 2 and len(set(y[train])) == 2 for train, test in splits):
                    return splits
            except ValueError:
                pass
        if require_group_isolation:
            raise ValueError(
                "Unable to create group-disjoint stratified folds containing both labels in every fold. "
                "Add campaign groups with better class coverage before model selection or calibration."
            )
    elif require_group_isolation:
        raise ValueError("Campaign group identifiers are required for isolated cross-validation.")
    return list(StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed).split(index, y))


@dataclass
class SelectionResult:
    name: str
    estimator: Any
    cv_f1_mean: float
    cv_f1_std: float
    table: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected": self.name,
            "scoring": "spam F1 at the estimator's default decision boundary",
            "cv_f1_mean": round(self.cv_f1_mean, 4),
            "cv_f1_std": round(self.cv_f1_std, 4),
            "candidates": self.table,
        }


def select_classifier(
    frame: Any,
    labels: Sequence[str],
    groups: Sequence[Any] | None,
    *,
    text_features: str,
    seed: int,
    n_splits: int = DEFAULT_CV_FOLDS,
) -> SelectionResult:
    """Pick the candidate with the best mean cross-validated spam F1.

    Features are fitted once per fold (on that fold's training rows only) and
    reused across candidates, which keeps the search cheap and leakage-free.
    """
    y = np.asarray(labels)
    candidates = candidate_classifiers(seed)
    scores: dict[str, list[float]] = {name: [] for name, _ in candidates}
    for train_idx, test_idx in cv_splits(
        labels, groups, n_splits=n_splits, seed=seed, require_group_isolation=groups is not None
    ):
        transformer = make_feature_transformer(text_features)
        x_train = transformer.fit_transform(frame.iloc[train_idx])
        x_test = transformer.transform(frame.iloc[test_idx])
        for name, estimator in candidates:
            fitted = clone(estimator).fit(x_train, y[train_idx])
            scores[name].append(float(f1_score(y[test_idx], fitted.predict(x_test), pos_label="spam")))
    table = [
        {
            "candidate": name,
            "cv_f1_mean": round(float(np.mean(values)), 4),
            "cv_f1_std": round(float(np.std(values)), 4),
            "folds": len(values),
        }
        for name, values in scores.items()
    ]
    # Deterministic tie-break: higher mean, lower std, then candidate order.
    best_name = max(scores, key=lambda key: (round(float(np.mean(scores[key])), 6), -float(np.std(scores[key]))))
    estimator = dict(candidates)[best_name]
    return SelectionResult(
        name=best_name,
        estimator=estimator,
        cv_f1_mean=float(np.mean(scores[best_name])),
        cv_f1_std=float(np.std(scores[best_name])),
        table=table,
    )


def calibrated_model(
    estimator: Any,
    *,
    text_features: str,
    seed: int,
    labels: Sequence[str],
    groups: Sequence[Any] | None = None,
) -> Pipeline:
    """Calibrate the full feature/classifier pipeline on isolated group folds.

    Keeping feature extraction inside ``CalibratedClassifierCV`` matters: if
    TF-IDF vocabulary is fitted before its internal split, held-out campaign
    text influences the calibration fold even when the classifier split is
    group-disjoint.
    """
    folds = cv_splits(
        labels,
        groups,
        n_splits=DEFAULT_CV_FOLDS,
        seed=seed,
        require_group_isolation=groups is not None,
    )
    calibrator = CalibratedClassifierCV(
        make_model(clone(estimator), text_features=text_features),
        method=CALIBRATION_METHOD,
        cv=folds,
        ensemble=False,
    )
    return Pipeline([("classifier", calibrator)])


def out_of_fold_probabilities(
    estimator: Any,
    frame: Any,
    labels: Sequence[str],
    groups: Sequence[Any] | None,
    *,
    text_features: str,
    seed: int,
    n_splits: int = DEFAULT_CV_FOLDS,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return per-fold (labels, calibrated spam probabilities) on held-out rows."""
    y = np.asarray(labels)
    results: list[tuple[np.ndarray, np.ndarray]] = []
    for train_idx, test_idx in cv_splits(
        labels, groups, n_splits=n_splits, seed=seed + 1, require_group_isolation=groups is not None
    ):
        train_groups = [groups[index] for index in train_idx] if groups is not None else None
        model = calibrated_model(
            estimator,
            text_features=text_features,
            seed=seed,
            labels=y[train_idx],
            groups=train_groups,
        )
        model.fit(frame.iloc[train_idx], y[train_idx])
        spam_column = list(model.classes_).index("spam")
        results.append((y[test_idx], model.predict_proba(frame.iloc[test_idx])[:, spam_column]))
    return results


def robust_threshold_decision(
    candidate: float,
    folds: Sequence[tuple[np.ndarray, np.ndarray]],
    *,
    default: float = DEFAULT_THRESHOLD,
    min_gain: float = MIN_ROBUST_F1_GAIN,
) -> dict[str, Any]:
    """Adopt ``candidate`` only if it beats ``default`` F1 in every fold and on average by ``min_gain``."""
    gains: list[float] = []
    for y_true, probabilities in folds:
        f1_candidate = f1_score(y_true, np.where(probabilities >= candidate, "spam", "ham"), pos_label="spam")
        f1_default = f1_score(y_true, np.where(probabilities >= default, "spam", "ham"), pos_label="spam")
        gains.append(float(f1_candidate - f1_default))
    mean_gain = float(np.mean(gains)) if gains else 0.0
    adopt = bool(gains) and abs(candidate - default) > 1e-9 and min(gains) > 0 and mean_gain >= min_gain
    return {
        "candidate_threshold": round(float(candidate), 4),
        "default_threshold": default,
        "fold_f1_gains": [round(value, 4) for value in gains],
        "mean_f1_gain": round(mean_gain, 4),
        "min_required_mean_gain": min_gain,
        "adopted": adopt,
        "threshold": round(float(candidate), 4) if adopt else default,
    }
