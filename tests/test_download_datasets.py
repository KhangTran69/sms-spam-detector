from __future__ import annotations

import io
import os
import urllib.request
import zipfile

import pytest
import scripts.download_datasets as dataset_downloader
from scripts.download_datasets import main

from src.public_datasets import (
    _KaggleCredentialRedirectHandler,
    download_kaggle_ph,
    download_kaggle_tagalog,
    download_ph_github_csv,
)


def zip_bytes(*members: tuple[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members:
            archive.writestr(name, content)
    return buffer.getvalue()


def mock_kaggle_opener(monkeypatch, content: bytes):
    captured = {}

    class FakeOpener:
        def open(self, request, *, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return io.BytesIO(content)

    def build_opener(*handlers):
        captured["handlers"] = handlers
        return FakeOpener()

    monkeypatch.setattr("urllib.request.build_opener", build_opener)
    return captured


def test_kaggle_redirect_handler_removes_authorization_across_origins():
    request = urllib.request.Request(
        "https://www.kaggle.com/api/v1/download",
        headers={"Authorization": "Basic fixture-credential", "User-Agent": "test-agent"},
    )
    handler = _KaggleCredentialRedirectHandler()

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://storage.googleapis.com/dataset/archive.zip",
    )

    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("User-agent") == "test-agent"


def test_kaggle_redirect_handler_keeps_authorization_on_same_origin():
    request = urllib.request.Request(
        "https://www.kaggle.com/api/v1/download",
        headers={"Authorization": "Basic fixture-credential"},
    )
    redirected = _KaggleCredentialRedirectHandler().redirect_request(
        request, None, 302, "Found", {}, "https://www.kaggle.com/datasets/archive.zip"
    )

    assert redirected is not None
    assert redirected.get_header("Authorization") == "Basic fixture-credential"


def test_downloader_requires_kaggle_credentials_before_network(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)

    with pytest.raises(SystemExit) as error:
        main(["--dataset", "tagalog-sms", "--output", str(tmp_path / "dataset.csv")])

    assert error.value.code == 2
    assert "KAGGLE_USERNAME" in capsys.readouterr().err


def test_downloader_extracts_csv_and_writes_message_free_metadata(tmp_path, monkeypatch):
    content = b"date-received,category,text\n2026-01-01,spam,secret SMS text\n"
    archive = zip_bytes(("nested/messages.csv", content))
    captured = mock_kaggle_opener(monkeypatch, archive)
    output = tmp_path / "data.csv"

    result = download_kaggle_ph(output, "kaggle-user", "kaggle-token")

    assert result == output
    assert any(isinstance(handler, _KaggleCredentialRedirectHandler) for handler in captured["handlers"])
    assert captured["request"].get_header("Authorization") is not None
    assert output.read_bytes() == content
    metadata = (tmp_path / "data.csv.metadata.json").read_text(encoding="utf-8")
    assert "secret SMS text" not in metadata
    assert "CC BY 4.0" in metadata
    assert "sha256" in metadata
    assert "downloaded_at_utc" in metadata
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o600
        assert output.with_suffix(output.suffix + ".metadata.json").stat().st_mode & 0o777 == 0o600
        assert output.parent.stat().st_mode & 0o777 == 0o700


def test_ph_downloader_uses_the_public_github_csv_without_credentials(tmp_path, monkeypatch):
    content = b"date-received,date-read,sender,category,text\n2026-01-01,,redacted_contact,spam,Synthetic fixture\n"
    request_urls = []

    def open_request(request, **_kwargs):
        request_urls.append(request.full_url)
        return io.BytesIO(content)

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    output = tmp_path / "ph-raw.csv"

    result = download_ph_github_csv(output)

    assert result == output
    assert output.read_bytes() == content
    assert request_urls == [
        "https://raw.githubusercontent.com/scottleechua/data/main/spam-and-marketing-sms/text-messages.csv"
    ]
    metadata = output.with_suffix(".csv.metadata.json").read_text(encoding="utf-8")
    assert "CC BY 4.0" in metadata
    assert "raw.githubusercontent.com/scottleechua/data/main/spam-and-marketing-sms/text-messages.csv" in metadata
    assert "Synthetic fixture" not in metadata
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o600
        assert output.with_suffix(".csv.metadata.json").stat().st_mode & 0o777 == 0o600


def test_ph_downloader_rejects_non_csv_responses_without_writing(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: io.BytesIO(b"upstream error"))
    output = tmp_path / "ph-raw.csv"

    with pytest.raises(ValueError, match="text and category columns"):
        download_ph_github_csv(output)

    assert not output.exists()


def test_downloader_restricts_managed_external_directory(tmp_path, monkeypatch):
    external = tmp_path / "data" / "external"
    external.mkdir(parents=True)
    monkeypatch.setattr("src.import_public_dataset.ROOT", tmp_path)
    archive = zip_bytes(("messages.csv", "date-received,category,text\n2026-01-01,spam,synthetic\n"))
    mock_kaggle_opener(monkeypatch, archive)

    output = download_kaggle_ph(external / "raw.csv", "kaggle-user", "kaggle-token")

    assert output.is_file()
    if os.name != "nt":
        assert external.stat().st_mode & 0o777 == 0o700
        assert output.stat().st_mode & 0o777 == 0o600


def test_downloader_rejects_unsafe_archive_paths(tmp_path, monkeypatch):
    archive = zip_bytes(("../outside.csv", "text"), ("messages.csv", "text"))
    mock_kaggle_opener(monkeypatch, archive)

    with pytest.raises(ValueError, match="unsafe archive path"):
        download_kaggle_ph(tmp_path / "data.csv", "kaggle-user", "kaggle-token")

    assert not (tmp_path.parent / "outside.csv").exists()


def test_downloader_refuses_to_overwrite_output(tmp_path):
    output = tmp_path / "existing.csv"
    output.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="overwrite"):
        download_kaggle_ph(output, "kaggle-user", "kaggle-token")


def test_tagalog_downloader_records_cc0_source_metadata(tmp_path, monkeypatch):
    content = b"Date,Sender,Text,Category\n2026-01-01,Example sender,Synthetic spam,spam\n"
    archive = zip_bytes(("tagalog-sms.csv", content))
    mock_kaggle_opener(monkeypatch, archive)
    output = tmp_path / "tagalog-sms-raw.csv"

    download_kaggle_tagalog(output, "kaggle-user", "kaggle-token")

    assert output.read_bytes() == content
    metadata = (tmp_path / "tagalog-sms-raw.csv.metadata.json").read_text(encoding="utf-8")
    assert "onzero0/tagalog-sms" in metadata
    assert "CC0: Public Domain" in metadata
    assert "Synthetic spam" not in metadata


def test_cli_downloads_tagalog_dataset_to_ignored_external_paths(tmp_path, monkeypatch):
    external = tmp_path / "data" / "external"
    external.mkdir(parents=True)
    monkeypatch.setattr(dataset_downloader, "ROOT", tmp_path)
    monkeypatch.setattr("src.import_public_dataset.ROOT", tmp_path)
    monkeypatch.setenv("KAGGLE_USERNAME", "kaggle-user")
    monkeypatch.setenv("KAGGLE_KEY", "kaggle-token")

    def write_tagalog_csv(destination, _username, _key):
        destination.write_text(
            "Date,Sender,Text,Category\n"
            "2026-01-01,Example sender,Synthetic prize message,spam\n"
            "2026-01-02,Example sender,Synthetic bill reminder,notifs\n",
            encoding="utf-8",
        )
        return destination

    options = dict(dataset_downloader.DATASET_OPTIONS)
    _, import_tagalog, raw_name, normalized_name, requires_credentials = options["tagalog-sms"]
    options["tagalog-sms"] = (write_tagalog_csv, import_tagalog, raw_name, normalized_name, requires_credentials)
    monkeypatch.setattr(dataset_downloader, "DATASET_OPTIONS", options)

    result = main(["--dataset", "tagalog-sms"])

    assert result == 0
    normalized = external / "tagalog-sms.csv"
    assert normalized.is_file()
    assert "Example sender" not in normalized.read_text(encoding="utf-8")


def test_default_ph_cli_path_needs_no_kaggle_credentials(tmp_path, monkeypatch):
    external = tmp_path / "data" / "external"
    external.mkdir(parents=True)
    monkeypatch.setattr(dataset_downloader, "ROOT", tmp_path)
    monkeypatch.setattr("src.import_public_dataset.ROOT", tmp_path)
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)

    def write_ph_csv(destination):
        destination.write_text(
            "date-received,date-read,sender,category,text\n2026-01-01,,redacted_contact,spam,Synthetic fixture\n",
            encoding="utf-8",
        )
        return destination

    options = dict(dataset_downloader.DATASET_OPTIONS)
    _, import_ph, raw_name, normalized_name, requires_credentials = options["ph-spam-marketing-sms"]
    options["ph-spam-marketing-sms"] = (write_ph_csv, import_ph, raw_name, normalized_name, requires_credentials)
    monkeypatch.setattr(dataset_downloader, "DATASET_OPTIONS", options)

    result = main([])

    assert result == 0
    assert (external / "ph-spam-marketing-sms.csv").is_file()
