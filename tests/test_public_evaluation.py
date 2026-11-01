from __future__ import annotations

import hashlib
import json
import stat
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import src.public_evaluation as public_evaluation


def write_dataset(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    path.write_text(
        "label,message,source,category,language,data_kind\n"
        + "".join(
            f'{label},"{message}",{source},{category},{language},{kind}\n'
            for label, message, kind in rows
            for source, category, language in [("fixture", "sms", "fil")]
        ),
        encoding="utf-8",
    )
    return path


def run_report(monkeypatch, tmp_path: Path, rows: list[tuple[str, str, str]]):
    dataset_path = write_dataset(tmp_path / "dataset.csv", rows)
    model_path = tmp_path / "private-model.pkl"
    model_path.write_bytes(b"fixture model bytes")
    bundle = SimpleNamespace(
        version="fixture-v1",
        threshold=0.5,
        metadata={"probability_calibrated": False},
    )
    monkeypatch.setattr(public_evaluation, "load_model", lambda path, identify_artifact=False: bundle)
    monkeypatch.setattr(
        public_evaluation,
        "spam_probabilities",
        lambda _bundle, messages: [0.91 if "spam" in message else 0.12 for message in messages],
    )
    report = public_evaluation.evaluate_public_dataset(
        dataset_path,
        model_path,
        tmp_path / "reports",
        operating_fpr=0.0,
    )
    return report, dataset_path, model_path


def write_consent_dataset(path: Path, row_count: int = 12) -> Path:
    today = datetime.now(UTC).date()
    fields = {
        "data_kind": "consented",
        "source": "synthetic_fixture",
        "consent_verified": "true",
        "consent_active": "true",
        "review_consent": "true",
        "model_research_consent": "true",
        "authorized_to_share": "true",
        "consent_scope": "model_research",
        "consent_version": "test_v1",
        "consent_date": today.isoformat(),
        "retention_until": (today + timedelta(days=90)).isoformat(),
        "reviewer_a_id": "reviewer_a",
        "reviewer_b_id": "reviewer_b",
        "reviewer_a_label_confidence": "high",
        "reviewer_b_label_confidence": "high",
        "adjudicator_id": "",
        "adjudicated_label_confidence": "high",
        "review_status": "adjudicated",
    }
    rows = []
    for index in range(row_count):
        label = "ham" if index % 2 == 0 else "spam"
        scam = "not_suspected" if label == "ham" else "suspected"
        category = "otp_legit" if label == "ham" else "phishing"
        rows.append(
            {
                **fields,
                "label": label,
                "scam_assessment": scam,
                "message": (
                    f"Synthetic {string.ascii_lowercase[index // 26]}{string.ascii_lowercase[index % 26]} "
                    f"reviewed {label} fixture {index}"
                ),
                "source": "synthetic_fixture",
                "category": category,
                "language": "en" if index % 3 else "fil",
                "group": f"campaign_{index:03d}",
                "consent_record_id": f"consent_{index:03d}",
                "received_at": f"{(today - timedelta(days=row_count - index)).isoformat()}T12:00:00Z",
                "reviewer_a_label": label,
                "reviewer_a_scam_assessment": scam,
                "reviewer_b_label": label,
                "reviewer_b_scam_assessment": scam,
                "adjudicated_label": label,
                "adjudicated_scam_assessment": scam,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def write_evaluation_plan(
    path: Path,
    dataset_path: Path,
    model_path: Path,
    *,
    training_path: Path | None = None,
    **overrides,
) -> Path:
    plan = {
        "schema_version": 1,
        "registered_at": datetime.now(UTC).isoformat(),
        "intended_use": "Synthetic test fixture only",
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "training_dataset_sha256": "",
        "training_membership_sha256": "",
        "test_membership_sha256": "",
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "model_version": "fixture-v1",
        "decision_threshold": 0.5,
        "split_method": "chronological_campaign_holdout",
        "campaign_overlap_checked": True,
        "test_split_sealed": True,
        "coverage_rationale": "Fixture-only coverage criteria exercise the readiness gate.",
        "uncertainty_rationale": "Fixture-only limits exercise the confidence interval gate.",
        "minimum_campaign_groups": 2,
        "minimum_coverage": {
            "language": {"en": 1, "fil": 1},
            "category": {"otp_legit": 1, "phishing": 1},
        },
        "maximum_cluster_interval_width": {
            "precision": 0.99,
            "recall": 0.99,
            "f1": 0.99,
            "false_positive_rate": 0.99,
            "false_negative_rate": 0.99,
        },
    }
    if training_path is not None:
        training_sha256 = hashlib.sha256(training_path.read_bytes()).hexdigest()
        plan["training_dataset_sha256"] = training_sha256
        plan["training_membership_sha256"] = public_evaluation._membership_fingerprint(
            training_sha256, len(pd.read_csv(training_path))
        )
    plan["test_membership_sha256"] = public_evaluation._membership_fingerprint(
        plan["dataset_sha256"], len(pd.read_csv(dataset_path))
    )
    plan.update(overrides)
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def write_consent_splits(tmp_path: Path) -> tuple[Path, Path]:
    complete = write_consent_dataset(tmp_path / "complete-consented.csv", row_count=60)
    frame = pd.read_csv(complete)
    training_path = tmp_path / "consented-training.csv"
    test_path = tmp_path / "consented-test.csv"
    frame.iloc[:40].to_csv(training_path, index=False)
    frame.iloc[40:].to_csv(test_path, index=False)
    return training_path, test_path


def test_report_records_exact_provenance_metrics_and_safe_breakdowns(monkeypatch, tmp_path):
    secret_message = "SECRET SMS TEXT spam transfer funds now"
    rows = [
        ("spam", secret_message, "public"),
        ("spam", "another spam campaign", "public"),
        ("ham", "family lunch", "public"),
        ("ham", "bank otp", "public"),
    ]

    report, dataset_path, model_path = run_report(monkeypatch, tmp_path, rows)

    assert report["dataset"]["kind"] == "public"
    assert report["dataset"]["sha256"] == hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    assert len(report["dataset"]["evaluation_membership_sha256"]) == 64
    assert report["model"]["sha256"] == hashlib.sha256(model_path.read_bytes()).hexdigest()
    assert report["model"]["version"] == "fixture-v1"
    assert report["metrics"]["confusion_matrix"] == {"tp": 2, "fp": 0, "tn": 2, "fn": 0}
    assert report["metrics"]["false_negative_rate"] == 0.0
    assert report["metrics"]["roc_auc"] is not None
    assert report["metrics"]["pr_auc"] is not None
    assert report["calibration"]["bins"]
    assert report["operating_threshold"]["max_false_positive_rate"] == 0.0
    assert report["breakdowns"]["language"]
    assert report["breakdowns"]["source"]
    assert report["breakdowns"]["category"]
    assert "source_revision" in report["run"]
    assert "source_tree_dirty" in report["run"]
    assert report["run"]["configuration"]["decision_threshold"] == 0.5
    assert report["run"]["libraries"]

    json_path = tmp_path / "reports" / "dataset_fixture-v1.json"
    markdown_path = tmp_path / "reports" / "dataset.md"
    serialized = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["model"]["sha256"] == report["model"]["sha256"]
    assert secret_message not in serialized
    assert str(dataset_path) not in serialized
    assert str(model_path) not in serialized


def test_single_class_dataset_marks_auc_and_fnr_unavailable(monkeypatch, tmp_path):
    rows = [("ham", "legitimate note one", "synthetic"), ("ham", "legitimate note two", "synthetic")]

    report, _, _ = run_report(monkeypatch, tmp_path, rows)

    assert report["metrics"]["roc_auc"] is None
    assert report["metrics"]["pr_auc"] is None
    assert report["metrics"]["false_negative_rate"] is None
    assert report["metrics"]["false_negative_rate_status"] == "unavailable_no_positive_examples"


def test_mixed_provenance_is_rejected_before_reporting(monkeypatch, tmp_path):
    dataset_path = write_dataset(
        tmp_path / "mixed.csv",
        [("spam", "public sample", "public"), ("ham", "synthetic sample", "synthetic")],
    )
    model_path = tmp_path / "model.pkl"
    model_path.write_bytes(b"model")
    monkeypatch.setattr(public_evaluation, "load_model", lambda *args, **kwargs: SimpleNamespace())

    with pytest.raises(ValueError, match="one provenance kind"):
        public_evaluation.evaluate_public_dataset(dataset_path, model_path, tmp_path / "reports")


def test_missing_model_writes_blocked_readiness_report_without_metrics(tmp_path):
    secret_message = "Synthetic fixture only: never include this in reports"
    dataset_path = write_dataset(
        tmp_path / "dataset.csv",
        [("ham", secret_message, "public"), ("spam", "synthetic spam fixture", "public")],
    )
    output_dir = tmp_path / "readiness"

    report = public_evaluation.evaluate_public_dataset(
        dataset_path,
        tmp_path / "missing-model.pkl",
        output_dir,
    )

    assert report["status"] == "blocked"
    assert report["readiness"]["blockers"] == ["model_artifact_missing"]
    assert report["readiness"]["metrics_generated"] is False
    assert report["metrics"] is None
    json_path = output_dir / "dataset_readiness.json"
    markdown_path = output_dir / "dataset_readiness.md"
    serialized = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    assert secret_message not in serialized
    assert "no performance metrics were generated" in markdown_path.read_text(encoding="utf-8").lower()


def test_readiness_report_keeps_the_hash_of_the_loaded_dataset_snapshot(monkeypatch, tmp_path):
    dataset_path = write_dataset(
        tmp_path / "dataset.csv",
        [
            ("ham", "Synthetic fixture ham", "synthetic"),
            ("spam", "Synthetic fixture spam", "synthetic"),
        ],
    )
    loaded_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    original_load_dataset = public_evaluation.load_dataset

    def load_then_change_file(path, **kwargs):
        dataset = original_load_dataset(path, **kwargs)
        Path(path).write_text(
            "label,message,source,category,language,data_kind\\nham,Synthetic changed fixture,fixture,sms,en,synthetic\\n",
            encoding="utf-8",
        )
        return dataset

    monkeypatch.setattr(public_evaluation, "load_dataset", load_then_change_file)
    report = public_evaluation.evaluate_public_dataset(
        dataset_path,
        tmp_path / "missing-model.pkl",
        tmp_path / "readiness",
    )

    assert report["dataset"]["sha256"] == loaded_hash
    assert report["dataset"]["rows"] == 2


def test_consented_readiness_report_is_written_with_private_permissions(tmp_path):
    dataset_path = write_consent_dataset(tmp_path / "consented.csv")
    output_dir = tmp_path / "private-reports"

    report = public_evaluation.evaluate_public_dataset(
        dataset_path,
        tmp_path / "missing-model.pkl",
        output_dir,
    )

    assert report["status"] == "blocked"
    assert report["dataset"]["kind"] == "consented"
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    for path in output_dir.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    serialized = "".join(path.read_text(encoding="utf-8") for path in output_dir.iterdir())
    assert "Synthetic reviewed fixture message" not in serialized
    assert "campaign_000" not in serialized


def test_consent_evaluation_requires_plan_and_skips_threshold_search(monkeypatch, tmp_path):
    training_path, dataset_path = write_consent_splits(tmp_path)
    model_path = tmp_path / "fixture-model.pkl"
    model_path.write_bytes(b"synthetic fixture model")
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    bundle = SimpleNamespace(
        version="fixture-v1",
        threshold=0.5,
        artifact_sha256=model_hash,
        metadata={
            "probability_calibrated": False,
            "threshold_selection": {"decision": {"policy": "validation", "threshold": 0.5}},
            "training_config": {"threshold_policy": "validation", "split_by": "time"},
            "data_sources": [{"sha256": hashlib.sha256(training_path.read_bytes()).hexdigest()}],
            "split": {"method": "chronological_group_holdout", "group_leakage": 0},
        },
    )
    monkeypatch.setattr(public_evaluation, "load_model", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(
        public_evaluation,
        "spam_probabilities",
        lambda _bundle, messages: [0.1 if "ham" in message else 0.9 for message in messages],
    )
    monkeypatch.setattr(
        public_evaluation,
        "_operating_threshold",
        lambda *args, **kwargs: pytest.fail("sealed consented evaluation must not search thresholds"),
    )
    plan_path = write_evaluation_plan(
        tmp_path / "plan.json",
        dataset_path,
        model_path,
        training_path=training_path,
    )

    report = public_evaluation.evaluate_public_dataset(
        dataset_path,
        model_path,
        tmp_path / "private-reports",
        training_data_path=training_path,
        evaluation_plan_path=plan_path,
    )

    assert report["status"] == "evaluated"
    assert report["evaluation_plan"]["sha256"] == hashlib.sha256(plan_path.read_bytes()).hexdigest()
    assert report["operating_threshold"]["status"] == "not_run_sealed_consent_evaluation"
    assert report["metrics"]["campaign_bootstrap_95"]["available"] is True
    assert "false_negative_rate" in report["metrics"]["campaign_bootstrap_95"]["intervals"]
    serialized = "".join(path.read_text(encoding="utf-8") for path in (tmp_path / "private-reports").iterdir())
    assert "Synthetic reviewed fixture" not in serialized


def test_consent_evaluation_blocks_coverage_below_preregistered_plan(monkeypatch, tmp_path):
    training_path, dataset_path = write_consent_splits(tmp_path)
    model_path = tmp_path / "fixture-model.pkl"
    model_path.write_bytes(b"synthetic fixture model")
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    bundle = SimpleNamespace(
        version="fixture-v1",
        threshold=0.5,
        artifact_sha256=model_hash,
        metadata={
            "probability_calibrated": False,
            "threshold_selection": {"decision": {"policy": "validation", "threshold": 0.5}},
            "training_config": {"threshold_policy": "validation", "split_by": "time"},
            "data_sources": [{"sha256": hashlib.sha256(training_path.read_bytes()).hexdigest()}],
            "split": {"method": "chronological_group_holdout", "group_leakage": 0},
        },
    )
    monkeypatch.setattr(public_evaluation, "load_model", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(
        public_evaluation,
        "spam_probabilities",
        lambda *args, **kwargs: pytest.fail("coverage must be checked before scoring"),
    )
    plan_path = write_evaluation_plan(
        tmp_path / "plan.json",
        dataset_path,
        model_path,
        training_path=training_path,
        minimum_coverage={"language": {"fil": 100}, "category": {"phishing": 1}},
    )

    report = public_evaluation.evaluate_public_dataset(
        dataset_path,
        model_path,
        tmp_path / "private-reports",
        training_data_path=training_path,
        evaluation_plan_path=plan_path,
    )

    assert report["status"] == "blocked"
    assert "language_coverage_below_plan" in report["readiness"]["blockers"]
    assert report["metrics"] is None


def test_consent_evaluation_blocks_cross_split_campaign_leakage(monkeypatch, tmp_path):
    training_path, dataset_path = write_consent_splits(tmp_path)
    training = pd.read_csv(training_path)
    training.loc[0, "group"] = "campaign_040"
    training.to_csv(training_path, index=False)
    model_path = tmp_path / "fixture-model.pkl"
    model_path.write_bytes(b"synthetic fixture model")
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    bundle = SimpleNamespace(
        version="fixture-v1",
        threshold=0.5,
        artifact_sha256=model_hash,
        metadata={
            "probability_calibrated": False,
            "threshold_selection": {"decision": {"policy": "validation", "threshold": 0.5}},
            "training_config": {"threshold_policy": "validation", "split_by": "time"},
            "data_sources": [{"sha256": hashlib.sha256(training_path.read_bytes()).hexdigest()}],
            "split": {"method": "chronological_group_holdout", "group_leakage": 0},
        },
    )
    monkeypatch.setattr(public_evaluation, "load_model", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(
        public_evaluation,
        "spam_probabilities",
        lambda *args, **kwargs: pytest.fail("campaign leakage must block before scoring"),
    )
    plan_path = write_evaluation_plan(
        tmp_path / "plan.json",
        dataset_path,
        model_path,
        training_path=training_path,
    )

    report = public_evaluation.evaluate_public_dataset(
        dataset_path,
        model_path,
        tmp_path / "private-reports",
        training_data_path=training_path,
        evaluation_plan_path=plan_path,
    )

    assert report["status"] == "blocked"
    assert "campaign_group_overlap_across_splits" in report["readiness"]["blockers"]
    assert report["metrics"] is None


def test_private_readiness_output_refuses_repository_root_and_shared_directory(tmp_path):
    dataset_path = write_consent_dataset(tmp_path / "private-participant-named-file.csv")
    model_path = tmp_path / "missing-model.pkl"

    with pytest.raises(ValueError, match="outside the repository or under ignored"):
        public_evaluation.evaluate_public_dataset(dataset_path, model_path, public_evaluation.ROOT)

    shared_directory = tmp_path / "shared-reports"
    shared_directory.mkdir(mode=0o755)
    shared_directory.chmod(0o755)
    with pytest.raises(ValueError, match="restrictive permissions"):
        public_evaluation.evaluate_public_dataset(dataset_path, model_path, shared_directory)
    assert stat.S_IMODE(shared_directory.stat().st_mode) == 0o755


def test_consent_evaluation_is_claimed_once_before_scoring(monkeypatch, tmp_path):
    training_path, dataset_path = write_consent_splits(tmp_path)
    model_path = tmp_path / "fixture-model.pkl"
    model_path.write_bytes(b"synthetic fixture model")
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    bundle = SimpleNamespace(
        version="fixture-v1",
        threshold=0.5,
        artifact_sha256=model_hash,
        metadata={
            "probability_calibrated": False,
            "threshold_selection": {"decision": {"policy": "validation", "threshold": 0.5}},
            "training_config": {"threshold_policy": "validation", "split_by": "time"},
            "data_sources": [{"sha256": hashlib.sha256(training_path.read_bytes()).hexdigest()}],
            "split": {"method": "chronological_group_holdout", "group_leakage": 0},
        },
    )
    score_calls = []
    monkeypatch.setattr(public_evaluation, "load_model", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(
        public_evaluation,
        "spam_probabilities",
        lambda _bundle, messages: (
            score_calls.append(len(messages)) or [0.1 if "ham" in item else 0.9 for item in messages]
        ),
    )
    plan_path = write_evaluation_plan(
        tmp_path / "plan.json",
        dataset_path,
        model_path,
        training_path=training_path,
    )
    output_dir = tmp_path / "private-reports"

    first = public_evaluation.evaluate_public_dataset(
        dataset_path,
        model_path,
        output_dir,
        training_data_path=training_path,
        evaluation_plan_path=plan_path,
    )
    second = public_evaluation.evaluate_public_dataset(
        dataset_path,
        model_path,
        tmp_path / "alternate-private-reports",
        training_data_path=training_path,
        evaluation_plan_path=plan_path,
    )

    assert first["status"] == "evaluated"
    assert second["status"] == "blocked"
    assert "sealed_evaluation_already_attempted" in second["readiness"]["blockers"]
    assert second["metrics"] is None
    assert len(score_calls) == 1
    attempt_path = (
        dataset_path.parent / f".{hashlib.sha256(dataset_path.read_bytes()).hexdigest()}.sealed-evaluation-attempt.json"
    )
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    assert attempt["dataset_sha256"] == hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    assert attempt["model_sha256"] == model_hash
    assert attempt["evaluation_plan_sha256"] == hashlib.sha256(plan_path.read_bytes()).hexdigest()


def test_incomplete_plan_returns_content_free_readiness_without_scoring(monkeypatch, tmp_path):
    training_path, dataset_path = write_consent_splits(tmp_path)
    model_path = tmp_path / "fixture-model.pkl"
    model_path.write_bytes(b"synthetic fixture model")
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    bundle = SimpleNamespace(
        version="fixture-v1",
        threshold=0.5,
        artifact_sha256=model_hash,
        metadata={
            "probability_calibrated": False,
            "threshold_selection": {"decision": {"policy": "validation", "threshold": 0.5}},
            "training_config": {"threshold_policy": "validation", "split_by": "time"},
            "data_sources": [{"sha256": hashlib.sha256(training_path.read_bytes()).hexdigest()}],
            "split": {"method": "chronological_group_holdout", "group_leakage": 0},
        },
    )
    secret_fixture = "Synthetic fixture text must never be reported"
    monkeypatch.setattr(public_evaluation, "load_model", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(
        public_evaluation,
        "spam_probabilities",
        lambda *args, **kwargs: pytest.fail("an incomplete pre-registration must block before scoring"),
    )
    plan_path = write_evaluation_plan(
        tmp_path / "incomplete-plan.json",
        dataset_path,
        model_path,
        training_path=training_path,
        coverage_rationale="",
    )
    output_dir = tmp_path / "private-readiness"

    report = public_evaluation.evaluate_public_dataset(
        dataset_path,
        model_path,
        output_dir,
        training_data_path=training_path,
        evaluation_plan_path=plan_path,
    )

    assert report["status"] == "blocked"
    assert "evaluation_plan_acceptance_rationale_missing" in report["readiness"]["blockers"]
    assert report["metrics"] is None
    serialized = "".join(path.read_text(encoding="utf-8") for path in output_dir.iterdir())
    assert secret_fixture not in serialized
    assert "Synthetic " not in serialized


def test_excessive_cluster_uncertainty_returns_content_free_readiness(monkeypatch, tmp_path):
    training_path, dataset_path = write_consent_splits(tmp_path)
    model_path = tmp_path / "fixture-model.pkl"
    model_path.write_bytes(b"synthetic fixture model")
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    bundle = SimpleNamespace(
        version="fixture-v1",
        threshold=0.5,
        artifact_sha256=model_hash,
        metadata={
            "probability_calibrated": False,
            "threshold_selection": {"decision": {"policy": "validation", "threshold": 0.5}},
            "training_config": {"threshold_policy": "validation", "split_by": "time"},
            "data_sources": [{"sha256": hashlib.sha256(training_path.read_bytes()).hexdigest()}],
            "split": {"method": "chronological_group_holdout", "group_leakage": 0},
        },
    )
    secret_fixture = "Synthetic fixture text must never be reported"
    monkeypatch.setattr(public_evaluation, "load_model", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(
        public_evaluation,
        "spam_probabilities",
        lambda _bundle, messages: [0.1 if "ham" in item else 0.9 for item in messages],
    )
    monkeypatch.setattr(
        public_evaluation,
        "campaign_bootstrap_intervals",
        lambda *args, **kwargs: {
            "available": True,
            "intervals": {
                "precision": [0.0, 1.0],
                "recall": [0.0, 1.0],
                "f1": [0.0, 1.0],
                "false_positive_rate": [0.0, 1.0],
                "false_negative_rate": [0.0, 1.0],
            },
        },
    )
    plan_path = write_evaluation_plan(
        tmp_path / "strict-plan.json",
        dataset_path,
        model_path,
        training_path=training_path,
        maximum_cluster_interval_width={
            "precision": 0.2,
            "recall": 0.2,
            "f1": 0.2,
            "false_positive_rate": 0.2,
            "false_negative_rate": 0.2,
        },
    )
    output_dir = tmp_path / "private-uncertainty"

    report = public_evaluation.evaluate_public_dataset(
        dataset_path,
        model_path,
        output_dir,
        training_data_path=training_path,
        evaluation_plan_path=plan_path,
    )

    assert report["status"] == "blocked"
    assert "campaign_uncertainty_precision_below_plan" in report["readiness"]["blockers"]
    assert report["metrics"] is None
    serialized = "".join(path.read_text(encoding="utf-8") for path in output_dir.iterdir())
    assert secret_fixture not in serialized
    assert "Synthetic " not in serialized
