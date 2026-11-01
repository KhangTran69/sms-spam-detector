from __future__ import annotations

import json

from src.consented_rehearsal import run_synthetic_rehearsal


def test_synthetic_rehearsal_exercises_the_governed_path_and_cleans_all_inputs():
    report = run_synthetic_rehearsal()

    serialized = json.dumps(report, sort_keys=True)
    assert report["status"] == "completed"
    assert report["evidence_class"] == "synthetic_rehearsal"
    assert report["intake"]["explicit_consent"] is True
    assert report["intake"]["reserved_example_url_rejected"] is True
    assert report["review"]["reviewer_count"] == 2
    assert report["review"]["blind"] is True
    assert report["review"]["donor_hints_used_as_labels"] is False
    assert report["review"]["model_results_exposed_to_reviewers"] is False
    assert report["review"]["adjudications"] >= 1
    assert report["preflight"]["training_valid"] is True
    assert report["preflight"]["evaluation_valid"] is True
    assert report["split"]["method"] == "chronological_group_holdout"
    assert report["split"]["campaign_group_overlap"] == 0
    assert report["training"]["threshold_source"] == "development_validation_only"
    assert report["evaluation"]["status"] == "evaluated"
    assert report["evaluation"]["attempts"] == 1
    assert report["evaluation"]["reported_data_kind"] == "synthetic_rehearsal"
    assert report["cleanup"]["temporary_workspace_removed"] is True
    assert "Synthetic campaign" not in serialized
    assert "reviewer-two-disagreement" not in serialized
    assert "https://sms-link.example" not in serialized
    assert "not consented participant data" in serialized.lower()
    assert "real-world accuracy estimate" in serialized.lower()
