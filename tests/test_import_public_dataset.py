from __future__ import annotations

import json

import pandas as pd
import pytest

import src.import_public_dataset as public_import
from src.data import DatasetError, dataset_manifest, load_dataset
from src.import_public_dataset import UCI_LICENSE


def use_temporary_raw_dir(tmp_path, monkeypatch):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    monkeypatch.setattr(public_import, "ROOT", tmp_path)
    return raw


def test_import_uci_tsv_adds_attribution_and_public_provenance(tmp_path, monkeypatch):
    raw = use_temporary_raw_dir(tmp_path, monkeypatch)
    source = tmp_path / "uci.tsv"
    source.write_text("ham\tSalamat po\nspam\tClaim your prize now\n", encoding="utf-8")
    output = public_import.import_dataset(source, raw / "uci.csv", input_format="uci-tsv")
    dataset = load_dataset(output, require_both_classes=True, min_class_count=0)

    assert dataset.class_counts == {"ham": 1, "spam": 1}
    assert dataset.records[0].provenance == {
        "dataset_id": "uci-sms-spam-collection-228",
        "dataset_version": "1.0",
        "license": UCI_LICENSE,
        "collection_period": "historical; exact per-message dates unavailable",
    }
    assert dataset.summary()["data_kind_counts"] == {"public": 2}
    manifest = dataset_manifest(dataset)
    assert "Salamat po" not in json.dumps(manifest)
    assert manifest["sources"][0]["class_counts"] == dataset.class_counts


def test_import_refuses_output_outside_ignored_raw_dir(tmp_path, monkeypatch):
    use_temporary_raw_dir(tmp_path, monkeypatch)
    source = tmp_path / "uci.tsv"
    source.write_text("ham\tHello\nspam\tPrize\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="inside ignored raw-data"):
        public_import.import_dataset(source, tmp_path / "public.csv", input_format="uci-tsv")


def test_import_refuses_to_overwrite(tmp_path, monkeypatch):
    raw = use_temporary_raw_dir(tmp_path, monkeypatch)
    source = tmp_path / "uci.tsv"
    source.write_text("ham\tHello\nspam\tPrize\n", encoding="utf-8")
    output = raw / "uci.csv"
    output.write_text("existing", encoding="utf-8")
    with pytest.raises(DatasetError, match="overwrite"):
        public_import.import_dataset(source, output, input_format="uci-tsv")


def test_source_provenance_must_be_consistent_per_file(tmp_path):
    path = tmp_path / "inconsistent.csv"
    pd.DataFrame(
        [
            ("ham", "hello", "dataset-a"),
            ("spam", "prize", "dataset-b"),
        ],
        columns=("label", "message", "dataset_id"),
    ).to_csv(path, index=False)
    with pytest.raises(DatasetError, match="dataset_id must be consistent"):
        load_dataset(path, min_class_count=0)


def test_validation_errors_do_not_echo_sms_content(tmp_path):
    secret = "Your secret OTP is 493821; never disclose"
    path = tmp_path / "conflict.csv"
    pd.DataFrame([("ham", secret), ("spam", secret)], columns=("label", "message")).to_csv(path, index=False)
    with pytest.raises(DatasetError) as error:
        load_dataset(path, min_class_count=0)
    assert secret not in str(error.value)
