from __future__ import annotations

from pathlib import Path


def test_privileged_release_job_is_checkout_free_and_retry_safe():
    workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/release-provenance.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    _prepare, separator, signing_job = workflow.partition("\n  sign-and-attest:")

    assert separator
    assert "actions/checkout@" not in signing_job
    assert "scripts/upload_release_asset.py" not in signing_job
    assert 'existing_digest="$(jq -r' in signing_job
    assert '"sha256:$wheel_sha256"' in signing_job
    assert "refusing to overwrite" in signing_job
    assert 'gh release upload "$RELEASE_TAG" "$wheel_path"' in signing_job
