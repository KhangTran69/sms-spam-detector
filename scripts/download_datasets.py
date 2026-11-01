"""Download approved public SMS corpora into ignored local storage."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.import_public_dataset import ROOT
from src.public_datasets import (
    download_kaggle_tagalog,
    download_ph_github_csv,
    import_kaggle_ph_dataset,
    import_kaggle_tagalog_dataset,
)

DATASET_OPTIONS = {
    "ph-spam-marketing-sms": (
        download_ph_github_csv,
        import_kaggle_ph_dataset,
        "ph-spam-marketing-sms-raw.csv",
        "ph-spam-marketing-sms.csv",
        False,
    ),
    "tagalog-sms": (
        download_kaggle_tagalog,
        import_kaggle_tagalog_dataset,
        "tagalog-sms-raw.csv",
        "tagalog-sms.csv",
        True,
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        choices=tuple(DATASET_OPTIONS),
        default="ph-spam-marketing-sms",
        help="Approved dataset to download (default: ph-spam-marketing-sms)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Raw CSV output path (must stay under data/external/)",
    )
    parser.add_argument(
        "--normalized-output",
        type=Path,
        default=None,
        help="Normalized CSV output path (must stay under data/external/)",
    )
    args = parser.parse_args(argv)
    download_dataset, import_dataset, default_raw, default_normalized, requires_kaggle = DATASET_OPTIONS[args.dataset]
    username = os.environ.get("KAGGLE_USERNAME", "").strip()
    key = os.environ.get("KAGGLE_KEY", "").strip()
    if requires_kaggle and (not username or not key):
        parser.error("Kaggle credentials are required; set KAGGLE_USERNAME and KAGGLE_KEY in the environment.")

    external = (ROOT / "data" / "external").resolve()
    raw_path = (args.output or external / default_raw).resolve()
    normalized_path = (args.normalized_output or external / default_normalized).resolve()
    report_path = normalized_path.with_suffix(normalized_path.suffix + ".report.json")
    if any(external not in path.parents for path in (raw_path, normalized_path, report_path)):
        parser.error("All download and normalization outputs must be under data/external/ ignored storage.")
    if len({raw_path, normalized_path, report_path}) != 3:
        parser.error("Raw, normalized, and report outputs must be distinct paths.")
    if report_path.exists():
        parser.error("Refusing to overwrite an existing normalization report.")

    try:
        if requires_kaggle:
            download_dataset(raw_path, username, key)
        else:
            download_dataset(raw_path)
        normalized, report = import_dataset(raw_path, normalized_path)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Downloaded and normalized {args.dataset} corpus: "
        f"{report['rows_loaded']} rows loaded; "
        f"{report['blank_or_redacted_excluded']} blank/redacted, "
        f"{report['unknown_category_rows']} unknown-category, "
        f"{report['duplicates_removed']} duplicate rows excluded."
    )
    print(f"Raw: {raw_path}\nNormalized: {normalized}\nAggregate report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
