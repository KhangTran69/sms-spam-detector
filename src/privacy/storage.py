"""Restrictive local-storage helpers for consented private data."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def ensure_private_directory(path: str | Path) -> Path:
    """Create a directory with owner-only permissions or reject an unsafe one.

    Existing directories are never chmodded: callers may pass shared system
    paths such as ``/tmp``, and changing those permissions would affect other
    applications. Choose a dedicated private child directory instead.
    """
    directory = Path(path).expanduser().resolve()
    missing: list[Path] = []
    parent = directory
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for item in reversed(missing):
        item.mkdir(mode=0o700)
    if os.name == "posix":
        try:
            permissions = stat.S_IMODE(directory.stat().st_mode)
        except OSError as exc:
            raise ValueError("Private data directory permissions could not be checked.") from exc
        if permissions & 0o077:
            raise ValueError("Private data directory must have restrictive permissions (owner access only).")
    return directory
