"""Validate and import consented, redacted Philippine SMS rows.

Input is a CSV that follows ``data/templates/consented_ph_sms_template.csv``.
The importer:

* requires a consent record (``consent_id``, ``consent_recorded_at``), a
  redaction reviewer, and a primary labeler on every row;
* drops rows where a second labeler disagrees (``second_label`` differs), so
  they can be adjudicated instead of trained on;
* rejects the **whole file** if any message still looks unredacted (PH mobile
  numbers, emails, or 6+ digit codes/accounts). Use ``[PHONE]``, ``[EMAIL]``,
  ``[CODE]``, ``[ACCOUNT]``, and ``[NAME]`` placeholders instead;
* requires a ``group`` (campaign/donor) so splits stay group-separated;
* writes ``data_kind=consented`` rows only under the git-ignored
  ``data/raw/consented/`` directory and never prints message text.

Train with: ``python -m src.train --supplement data/raw/consented/<file>.csv``.
Hold out with: ``python -m src.import_consented --input x.csv --role holdout`` and
then ``python -m src.train --holdout data/raw/consented/holdout_<file>.csv``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.data import ROOT, DatasetError, _normalize_labels

TEMPLATE = ROOT / "data" / "templates" / "consented_ph_sms_template.csv"
CONSENTED_DIR = ROOT / "data" / "raw" / "consented"
REQUIRED_NONEMPTY = (
    "label",
    "message",
    "group",
    "consent_id",
    "consent_recorded_at",
    "redaction_reviewed_by",
    "labeler",
)
UNREDACTED_PATTERNS = {
    "ph_mobile_number": re.compile(r"(?:\+?63|0)9\d{2}[\s-]?\d{3}[\s-]?\d{4}"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "long_digit_code": re.compile(r"(?<![\d₱,.])\d{6,}(?![\d,.])"),
}


def template_columns() -> list[str]:
    return pd.read_csv(TEMPLATE, nrows=0).columns.tolist()


def find_unredacted(messages: pd.Series) -> dict[str, list[int]]:
    """Return {pattern name: [1-based CSV data row numbers]} without message text."""
    hits: dict[str, list[int]] = {}
    for index, message in messages.items():
        for name, pattern in UNREDACTED_PATTERNS.items():
            if pattern.search(str(message)):
                hits.setdefault(name, []).append(int(str(index)) + 2)
    return hits


def import_consented(
    input_path: str | Path, *, role: str = "train", output_dir: Path = CONSENTED_DIR
) -> dict[str, Any]:
    source = Path(input_path)
    if not source.is_file():
        raise DatasetError(f"Input not found: {source}")
    if role not in {"train", "holdout"}:
        raise DatasetError("role must be train or holdout")
    frame = pd.read_csv(source, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = [column for column in template_columns() if column not in frame.columns]
    if missing:
        raise DatasetError(f"{source.name}: missing template columns {missing}")
    for column in REQUIRED_NONEMPTY:
        blank = frame.index[frame[column].str.strip().eq("")].tolist()
        if blank:
            raise DatasetError(f"{source.name}: column {column!r} is blank on rows {[i + 2 for i in blank[:10]]}")
    frame["label"] = _normalize_labels(frame["label"], source)
    leaks = find_unredacted(frame["message"])
    if leaks:
        summary = {name: rows[:10] for name, rows in leaks.items()}
        raise DatasetError(f"{source.name}: possible unredacted personal data on rows {summary}; redact and retry.")
    second = frame["second_label"].str.strip().str.lower()
    disagreement = second.ne("") & second.ne(frame["label"])
    kept = frame[~disagreement].copy()
    kept["data_kind"] = "consented"
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "holdout_" if role == "holdout" else ""
    destination = output_dir / f"{prefix}{source.stem}.csv"
    if destination.exists():
        raise DatasetError(f"Refusing to overwrite existing dataset: {destination}")
    kept.to_csv(destination, index=False)
    return {
        "output": str(destination),
        "rows_in": len(frame),
        "rows_written": len(kept),
        "label_disagreements_dropped": int(disagreement.sum()),
        "class_counts": {str(key): int(value) for key, value in kept["label"].value_counts().items()},
        "groups": int(kept["group"].nunique()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import consented, redacted PH SMS rows.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--role", choices=("train", "holdout"), default="train")
    args = parser.parse_args(argv)
    try:
        report = import_consented(args.input, role=args.role)
    except DatasetError as exc:
        print(f"data error: {exc}")
        return 2
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
