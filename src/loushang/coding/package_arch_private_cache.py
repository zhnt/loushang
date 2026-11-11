"""Product binding for the first-party Arch private cache writer."""

from __future__ import annotations

import os
from pathlib import Path

from loushang.harness.resources.packages.plugin_lifecycle.windows_snapshot_io import (
    _write_inherited_private_snapshot,
)


def write_coding_arch_private_windows_snapshot(path: Path, encoded: bytes) -> None:
    """Create an atomic cache file with the Product owner's exact ACL."""
    if os.name != "nt":
        raise OSError("Windows Coding Arch private cache writer is unavailable")
    _write_inherited_private_snapshot(path, encoded)


__all__ = ["write_coding_arch_private_windows_snapshot"]
