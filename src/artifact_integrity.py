"""Hash checks for serialized model artifacts and local checkpoint trees.

This module uses only the standard library so release tooling can validate a
model bundle without deserializing its pickle payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ArtifactIntegrityError(ValueError):
    """The model file and its metadata sidecar do not agree."""


def main(argv: list[str] | None = None) -> int:
    """Validate a release model and its sidecar without deserializing the model."""
    parser = argparse.ArgumentParser(description="Verify a model bundle against its metadata SHA-256.")
    parser.add_argument("model", type=Path, help="Path to the model bundle; the default sidecar is adjacent")
    parser.add_argument("--metadata", type=Path, help="Optional explicit metadata sidecar path")
    args = parser.parse_args(argv)
    try:
        model_bytes = args.model.read_bytes()
        digest, _warning = verify_artifact_sidecar(args.model, model_bytes, args.metadata, require_hash=True)
    except (OSError, ArtifactIntegrityError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"Verified model artifact SHA-256: {digest}")
    return 0


def verify_artifact_sidecar(
    artifact_path: str | Path,
    artifact_bytes: bytes,
    sidecar_path: str | Path | None = None,
    *,
    require_hash: bool = False,
) -> tuple[str, str | None]:
    """Return the exact bundle hash and a warning when legacy metadata has no hash.

    A present but invalid or mismatched hash is always an error. `require_hash`
    is used by release validation to reject absent/legacy metadata.
    """
    artifact_path = Path(artifact_path)
    metadata_path = Path(sidecar_path) if sidecar_path is not None else artifact_path.with_suffix(".metadata.json")
    digest = hashlib.sha256(artifact_bytes).hexdigest()

    try:
        metadata_text = metadata_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if require_hash:
            raise ArtifactIntegrityError("Model metadata sidecar is missing.") from None
        return digest, "Model metadata sidecar is missing; sidecar hash verification was unavailable."
    except UnicodeDecodeError as exc:
        raise ArtifactIntegrityError("Model metadata sidecar is not valid UTF-8.") from exc
    except OSError as exc:
        raise ArtifactIntegrityError(f"Could not read model metadata sidecar ({type(exc).__name__}).") from exc

    try:
        metadata: Any = json.loads(metadata_text)
    except json.JSONDecodeError as exc:
        raise ArtifactIntegrityError("Model metadata sidecar is not valid JSON.") from exc
    if not isinstance(metadata, dict):
        raise ArtifactIntegrityError("Model metadata sidecar must contain a JSON object.")

    sidecar_digest = metadata.get("artifact_sha256")
    if sidecar_digest is None or sidecar_digest == "":
        if require_hash:
            raise ArtifactIntegrityError("Model metadata sidecar does not contain artifact_sha256.")
        return digest, "Model metadata sidecar has no artifact SHA-256; continuing with a legacy bundle."
    if not isinstance(sidecar_digest, str) or not _SHA256_RE.fullmatch(sidecar_digest):
        raise ArtifactIntegrityError(
            "Model metadata sidecar artifact_sha256 must be a 64-character hexadecimal digest."
        )
    if sidecar_digest.lower() != digest:
        raise ArtifactIntegrityError("Model sidecar SHA-256 mismatch; refusing to deserialize the artifact.")
    return digest, None


def directory_sha256(directory: str | Path, *, excluded_paths: tuple[str, ...] = ()) -> str:
    """Hash a directory's relative paths, sizes, and bytes in stable order."""
    root = Path(directory)
    if not root.exists() or not root.is_dir():
        raise ArtifactIntegrityError("Checkpoint path must be an existing directory.")

    digest = hashlib.sha256()
    excluded = set(excluded_paths)
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        relative_path = path.relative_to(root).as_posix()
        if relative_path in excluded:
            continue
        relative = relative_path.encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
