"""Validate and import consented, de-identified SMS batches locally.

The importer uses the exact schema and checks implemented by
``src.consented_data``. It reads one byte snapshot, validates that frame, then
writes that same frame so the data cannot change between preflight and import.
It never prints message text, personal values, or the source path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from src.consented_data import _read_intake_csv, normalize_intake_columns, validate_batch
from src.data import LABEL_ALIASES, ROOT, DatasetError

TEMPLATE = ROOT / "data" / "templates" / "consented_ph_sms_template.csv"
CONSENTED_DIR = ROOT / "data" / "raw" / "consented"
PURPOSES = {"training": "training", "evaluation": "evaluation", "train": "training", "holdout": "evaluation"}


def _remove_temporary(path: Path | None) -> bool:
    if path is None:
        return True
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def template_columns() -> list[str]:
    """Return the single supported intake schema."""
    return pd.read_csv(TEMPLATE, nrows=0).columns.tolist()


def import_consented(
    input_path: str | Path,
    *,
    purpose: str = "training",
    role: str | None = None,
    output_dir: Path = CONSENTED_DIR,
    today=None,
) -> dict[str, Any]:
    """Validate and write one batch for training or final evaluation.

    ``role`` remains as a compatibility alias for callers using the earlier
    ``train``/``holdout`` API. New callers should pass ``purpose``.
    """
    selected = role if role is not None else purpose
    normalized_purpose = PURPOSES.get(str(selected).strip().lower())
    if normalized_purpose is None:
        raise DatasetError("purpose must be training or evaluation.")

    try:
        input_bytes, frame = _read_intake_csv(input_path)
        report = validate_batch(frame, today=today, purpose=normalized_purpose)
    except ValueError as exc:
        raise DatasetError(str(exc)) from None
    if not report.valid:
        findings = [{"row": item.row, "rule": item.rule} for item in report.findings]
        raise DatasetError(f"Consent intake rejected; correct the listed row/rule findings: {json.dumps(findings)}")

    normalized = normalize_intake_columns(frame)
    labels = normalized["label"].astype(str).str.strip().str.lower().map(LABEL_ALIASES)
    if labels.isna().any():  # Defensive: validate_batch has already checked labels.
        raise DatasetError("Consent intake contains invalid labels.")
    normalized["label"] = labels.astype(str)
    normalized["data_kind"] = "consented"

    digest = hashlib.sha256(input_bytes).hexdigest()[:16]
    output_dir = Path(output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise DatasetError("Protected output directory cannot be created.") from None
    destination = output_dir / f"{normalized_purpose}_{digest}.csv"
    if destination.exists():
        raise DatasetError("Refusing to overwrite an existing consented batch.")

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{normalized_purpose}_",
            suffix=".tmp",
            dir=output_dir,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            normalized.to_csv(handle, index=False)
        # Same-directory hard-link creation publishes atomically and fails if
        # another run already created this content-addressed destination.
        os.link(temporary, destination)
    except OSError:
        cleaned = _remove_temporary(temporary)
        if not cleaned:
            raise DatasetError(
                "Temporary consented data cleanup failed; inspect the protected output directory."
            ) from None
        if destination.exists():
            raise DatasetError("Refusing to overwrite an existing consented batch.") from None
        raise DatasetError("Consented batch could not be written to the protected output directory.") from None
    if not _remove_temporary(temporary):
        raise DatasetError("Temporary consented data cleanup failed; inspect the protected output directory.")

    return {
        "output": destination.name,
        "purpose": normalized_purpose,
        "rows_written": report.rows,
        "labels": report.labels,
        "languages": report.languages,
        "categories": report.categories,
        "groups": report.groups,
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and import a consented, de-identified SMS CSV.")
    parser.add_argument("--input", required=True, help="Private intake CSV stored outside Git.")
    parser.add_argument("--purpose", choices=("training", "evaluation"), default="training")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=CONSENTED_DIR,
        help="Protected directory for the imported batch (default: data/raw/consented).",
    )
    args = parser.parse_args(argv)
    try:
        report = import_consented(args.input, purpose=args.purpose, output_dir=args.output_dir)
    except DatasetError as exc:
        print(f"data error: {exc}")
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
