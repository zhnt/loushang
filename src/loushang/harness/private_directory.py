"""Product-neutral creation of private directory chains.

``Path.mkdir(mode=0o700, parents=True)`` and ``os.makedirs(mode=0o700)`` apply
``mode`` to the leaf only. Each intermediate level is created through an internal
``self.parent.mkdir(parents=True, exist_ok=True)`` call that drops ``mode``, so
ancestors inherit the process default (``0o777 & ~umask``). Under a permissive
umask such as ``0o002`` -- the Debian/Ubuntu system-user default -- those
ancestors become group-writable ``0o775``, which private-directory admission
rejects as unsafe. A caller could therefore build a tree and then be refused by
its own admission layer.

This module owns the single implementation of that creation rule so journal
locking, the machine-resource control plane and any other writer share one
reviewed primitive instead of repeating security-relevant directory logic.

Scope is deliberately narrow: create the missing levels at ``0o700``. This is
not an admission or ownership guarantee. It does not validate that an existing
level is private, does not claim the chain, and does not serialise concurrent
creators beyond what ``mkdir`` itself provides. Callers that own a specific leaf
still tighten and validate that leaf through their own authority.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

__all__ = ["create_private_directory_chain"]

_PRIVATE_MODE = 0o700


def create_private_directory_chain(path: str | Path) -> Path:
    """Create every missing ancestor of ``path`` plus ``path`` at ``0o700``.

    ``path`` must be absolute. Missing levels are created explicitly at ``0o700``
    so a permissive umask cannot widen them.

    Levels that already exist are never rewritten, even when their mode is not
    private: an existing directory may belong to another owner or hold data this
    call did not create.

    Symlinks are never followed. A directory symlink is a valid directory to
    ``is_dir()``, so every level is classified with ``lstat`` and any symlink,
    dangling symlink or non-directory entry is rejected instead of resolved. The
    returned path is the ``path`` argument, not a resolved target.

    Raises ``ValueError`` for a relative ``path`` and ``NotADirectoryError`` for a
    symlink, a non-directory entry, or a filesystem root that cannot be reached.
    """

    target = Path(path).expanduser()
    if not target.is_absolute():
        raise ValueError("private directory target must be absolute")

    missing: list[Path] = []
    current = target
    while True:
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            missing.append(current)
        except OSError as error:
            if error.errno == errno.ENOTDIR:
                raise NotADirectoryError(str(current)) from None
            raise
        else:
            _require_direct_directory(current, metadata)
            break
        parent = current.parent
        if parent == current:
            raise NotADirectoryError(str(target))
        current = parent

    for level in reversed(missing):
        try:
            os.mkdir(level, mode=_PRIVATE_MODE)
        except FileExistsError:
            # A concurrent creator won this level. It is not this call's to
            # rewrite, and a following ``is_dir()`` would accept a symlink, so
            # reclassify with lstat and refuse anything that is not a direct
            # directory.
            try:
                metadata = level.lstat()
            except OSError:
                raise NotADirectoryError(str(level)) from None
            _require_direct_directory(level, metadata)
        else:
            _tighten_created_level(level)
    return target


def _tighten_created_level(path: Path) -> None:
    """Fix the mode of a level this call just created.

    ``mkdir`` masks ``mode`` with the umask, so an inherited bit such as setgid on
    the parent is copied onto the new directory: under a setgid parent,
    ``mkdir(mode=0o700)`` yields ``0o2700``, which private-directory admission
    rejects because it requires exactly ``0o700``. Only levels created by this
    call are corrected; an existing directory is never rewritten.
    """

    if os.name != "posix":
        return
    metadata = path.lstat()
    if stat.S_IMODE(metadata.st_mode) == _PRIVATE_MODE:
        return
    os.chmod(path, _PRIVATE_MODE)


def _require_direct_directory(path: Path, metadata: os.stat_result) -> None:
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise NotADirectoryError(str(path))
