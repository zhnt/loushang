"""Product-owned Windows writer for the first-party Arch private cache."""

from __future__ import annotations

import os
import secrets
from contextlib import suppress
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
)


def write_coding_arch_private_windows_snapshot(path: Path, encoded: bytes) -> None:
    """Create an atomic cache file with the Product owner's exact ACL."""

    if os.name != "nt":
        raise OSError("Windows Coding Arch private cache writer is unavailable")
    temporary_path: Path | None = None
    with WindowsPrivateDirectoryAcl(inherit_children=True) as acl:
        parent_fd = open_windows_directory(path.parent, read_control=True)
        try:
            acl.validate(parent_fd)
            temporary_path = path.parent / f".{path.name}.{secrets.token_hex(16)}.tmp"
            temporary_fd = open_windows_regular_file_at(
                parent_fd,
                temporary_path.name,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
            try:
                acl.validate(temporary_fd)
                with os.fdopen(temporary_fd, "wb") as stream:
                    temporary_fd = -1
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                if temporary_fd >= 0:
                    os.close(temporary_fd)
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            os.close(parent_fd)
            if temporary_path is not None:
                with suppress(FileNotFoundError):
                    temporary_path.unlink()


__all__ = ["write_coding_arch_private_windows_snapshot"]
