"""Filesystem roots exposed by the host platform."""

from __future__ import annotations

import sys
from pathlib import Path
from string import ascii_uppercase


def host_filesystem_roots(workspace_root: Path) -> tuple[Path, ...]:
    """Return local mounts and the workspace's share when it has one."""
    if sys.platform == "win32":
        import ctypes

        # The drive mask avoids probing absent devices and disconnected paths.
        drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
        if not drive_mask:
            raise OSError("cannot determine host filesystem drives")
        roots = tuple(
            Path(f"{drive}:\\")
            for index, drive in enumerate(ascii_uppercase)
            if drive_mask & (1 << index)
        )
    else:
        roots = (Path("/"),)
    anchor = Path(workspace_root.expanduser().resolve(strict=False).anchor)
    return roots if anchor in roots else (*roots, anchor)
