"""Normalize operator-supplied public SMS datasets into project-local schemas.

UCI inputs are written below ignored ``data/raw/``; Kaggle SMS inputs are
normalized below ignored ``data/external/``. This command does not download.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.data import ROOT, DatasetError, _normalize_labels
from src.public_datasets import import_kaggle_ph_dataset, import_kaggle_tagalog_dataset

UCI_LICENSE = "CC BY 4.0"
UCI_URL = "https://archive.ics.uci.edu/dataset/228/sms+spam+collection"


def import_dataset(input_path: str | Path, output_path: str | Path, *, input_format: str = "auto") -> Path:
    """Normalize a UCI TSV or compatible labeled CSV without altering messages."""
    source = Path(input_path)
    destination = Path(output_path).resolve()
    raw_root = (ROOT / "data" / "raw").resolve()
    if raw_root not in destination.parents:
        raise DatasetError("Output must be inside ignored raw-data storage.")
    if destination.exists():
        raise DatasetError("Refusing to overwrite an existing dataset.")
    if not source.is_file():
        raise DatasetError("Input dataset not found.")

    detected = input_format
    if detected == "auto":
        detected = "uci-tsv" if source.suffix.lower() in {".tsv", ".txt"} else "csv"
    if detected not in {"uci-tsv", "csv"}:
        raise DatasetError("input_format must be auto, csv, or uci-tsv.")
    try:
        if detected == "uci-tsv":
            frame = pd.read_csv(source, sep="\t", header=None, names=["label", "message"], dtype=str)
        else:
            frame = pd.read_csv(source, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
        raise DatasetError("Input dataset cannot be read as a valid CSV or TSV.") from None
    columns = {str(column).strip().lower(): column for column in frame.columns}
    if "label" in columns and "message" in columns:
        label_column, message_column = columns["label"], columns["message"]
    elif "v1" in columns and "v2" in columns:
        label_column, message_column = columns["v1"], columns["v2"]
    else:
        raise DatasetError("Input must contain label/message or Kaggle v1/v2 columns.")
    labels = _normalize_labels(frame[label_column], source_label="public dataset import")
    messages = frame[message_column].astype(str).str.strip()
    if messages.eq("").any():
        raise DatasetError("Input contains blank messages; fix them before importing.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "label": labels,
            "message": messages,
            "source": "uci_sms_spam_collection",
            "data_kind": "public",
            "dataset_id": "uci-sms-spam-collection-228",
            "dataset_version": "1.0",
            "license": UCI_LICENSE,
            "collection_period": "historical; exact per-message dates unavailable",
            "language": "en",
        }
    ).to_csv(destination, index=False, encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Operator-provided UCI or Kaggle CSV")
    parser.add_argument("--source", choices=("uci", "kaggle-ph", "kaggle-tagalog"), default="uci")
    parser.add_argument(
        "--output",
        default=None,
        help="Ignored output path (UCI defaults to data/raw/imported; Kaggle corpora to data/external)",
    )
    parser.add_argument("--format", choices=("auto", "csv", "uci-tsv"), default="auto")
    args = parser.parse_args(argv)
    if args.source in {"kaggle-ph", "kaggle-tagalog"}:
        if args.source == "kaggle-ph":
            output = args.output or str(ROOT / "data" / "external" / "ph-spam-marketing-sms.csv")
            import_function = import_kaggle_ph_dataset
            dataset_label = "Kaggle PH SMS"
        else:
            output = args.output or str(ROOT / "data" / "external" / "tagalog-sms.csv")
            import_function = import_kaggle_tagalog_dataset
            dataset_label = "Kaggle Tagalog-SMS"
        try:
            normalized, report = import_function(args.input, output)
        except DatasetError as exc:
            parser.error(str(exc))
        print(
            f"Normalized {dataset_label} rows: {report['rows_loaded']}; "
            f"excluded: {report['blank_or_redacted_excluded']}; "
            f"unknown category: {report['unknown_category_rows']}; "
            f"duplicates: {report['duplicates_removed']}; output: {normalized}"
        )
        return 0
    output = args.output or str(ROOT / "data" / "raw" / "imported" / "uci_sms_spam.csv")
    import_dataset(args.input, output, input_format=args.format)
    print(f"Imported public dataset; license: {UCI_LICENSE}; source: {UCI_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
