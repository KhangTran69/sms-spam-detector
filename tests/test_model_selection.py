import numpy as np
import pandas as pd

from src.features import messages_to_frame
from src.model_selection import (
    calibrated_model,
    cv_splits,
    robust_threshold_decision,
    select_classifier,
)

SPAM = [f"WIN P{n},000 now! Claim at http://bit.ly/prize{n} before midnight" for n in range(20)]
HAM = [f"Hi, see you at {n} pm for dinner with the family, ingat" for n in range(20)]


def _data():
    messages = SPAM + HAM
    labels = ["spam"] * len(SPAM) + ["ham"] * len(HAM)
    groups = [f"g{index}" for index in range(len(messages))]
    return messages_to_frame(messages), labels, groups


def test_cv_splits_keep_groups_separate():
    labels = ["spam", "ham"] * 20
    groups = [index // 2 for index in range(40)]
    for train, test in cv_splits(labels, groups, n_splits=5, seed=1):
        assert not {groups[i] for i in train} & {groups[i] for i in test}


def test_select_classifier_reports_every_candidate():
    frame, labels, groups = _data()
    result = select_classifier(frame, labels, groups, text_features="combined", seed=3, n_splits=3)
    names = [row["candidate"] for row in result.table]
    assert result.name in names
    assert any(name.startswith("linear_svm") for name in names)
    assert any(name.startswith("logistic_regression") for name in names)
    assert any(name.startswith("sgd_classifier") for name in names)


def test_calibrated_model_outputs_probabilities():
    frame, labels, groups = _data()
    result = select_classifier(frame, labels, groups, text_features="word", seed=3, n_splits=3)
    model = calibrated_model(result.estimator, text_features="word", seed=3, labels=labels, groups=groups)
    calibrator = model.named_steps["classifier"]
    calibration_folds = calibrator.cv
    assert calibrator.ensemble is False
    assert "features" in calibrator.estimator.named_steps
    assert all(
        not ({groups[i] for i in train} & {groups[i] for i in held_out}) for train, held_out in calibration_folds
    )
    model.fit(frame, labels)
    probabilities = model.predict_proba(frame)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    assert list(model.classes_) == ["ham", "spam"]


def test_grouped_cross_validation_fails_instead_of_leaking_when_campaign_support_is_insufficient():
    labels = ["ham"] * 4 + ["spam"] * 4
    groups = ["ham_campaign"] * 4 + ["spam_campaign"] * 4

    try:
        cv_splits(labels, groups, n_splits=2, seed=5, require_group_isolation=True)
    except ValueError as error:
        assert "group-disjoint stratified folds" in str(error)
    else:
        raise AssertionError("expected grouped CV to fail when every campaign contains only one label")


def test_robust_threshold_requires_gain_in_every_fold():
    y = np.array(["spam", "spam", "ham", "ham"])
    good = (y, np.array([0.45, 0.9, 0.1, 0.2]))
    neutral = (y, np.array([0.9, 0.9, 0.1, 0.2]))
    assert robust_threshold_decision(0.4, [good, good])["adopted"] is True
    decision = robust_threshold_decision(0.4, [good, neutral])
    assert decision["adopted"] is False
    assert decision["threshold"] == 0.5


def test_frame_type():
    frame, _, _ = _data()
    assert isinstance(frame, pd.DataFrame)
