"""File-only cache policy for fresh, coordinator-owned installation slots.

No interpreter execution, Product-state reset or process ownership lives here.
The caller invokes this inside InstallationSlot.run after preverification and
input reset, immediately before the retained measured owner. Base Python caches
and seed-preserved Product state are deliberately outside this policy.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
import sys
import tempfile
from pathlib import Path


def _identity(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.resolve() != path:
        raise ValueError("bytecode root must be a canonical real directory")
    return info.st_dev, info.st_ino


def inventory(root, *, installation=False):
    """Inventory .pyc files without following venv interpreter/alias symlinks."""
    _identity(root)
    links = (
        {
            "bin/python": str(Path(sys._base_executable).resolve()),
            "bin/python3": "python",
            f"bin/python{sys.version_info.major}.{sys.version_info.minor}": "python",
            "lib64": "lib",
        }
        if installation
        else {}
    )
    result = {}
    pending = [root]
    visited = size = 0
    while pending:
        path = pending.pop()
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        visited += 1
        if visited > 100000:
            raise ValueError("bytecode inventory exceeds 100000 entries")
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(path) as children:
                for child in children:
                    pending.append(Path(child.path))
                    if visited + len(pending) > 100000:
                        raise ValueError("bytecode inventory exceeds 100000 entries")
        elif stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            if relative == "bin/python" and installation:
                # uv may name its 3.11 alias rather than the resolved 3.11.x
                # directory. Compare the known interpreter's canonical path,
                # but never traverse that symlink as part of the cache walk.
                valid = (
                    Path(target).is_absolute()
                    and str(path.resolve()) == links[relative]
                )
            else:
                valid = relative in links and target == links[relative]
            if not valid:
                raise ValueError(f"unrecognized symlink in bytecode scope: {relative}")
        elif stat.S_ISREG(info.st_mode):
            if path.suffix != ".pyc":
                if not installation:
                    raise ValueError("foreign non-bytecode file in external cache")
                continue
            if installation:
                try:
                    source = (
                        Path(importlib.util.source_from_cache(str(path)))
                        if path.parent.name == "__pycache__"
                        else path.with_suffix(".py")
                    )
                    if not stat.S_ISREG(source.lstat().st_mode):
                        raise ValueError("cache source is not a regular file")
                except (OSError, ValueError) as error:
                    # A source-less .pyc can be the installed program itself.
                    # Reject the complete inventory before unlinking any cache.
                    raise ValueError(
                        "installed bytecode lacks a regular source"
                    ) from error
            size += info.st_size
            if size > 256 * 1024 * 1024:
                raise ValueError("bytecode inventory exceeds 256 MiB")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            result[relative] = dict(
                dev=info.st_dev,
                ino=info.st_ino,
                size=info.st_size,
                mtime_ns=info.st_mtime_ns,
                mode=stat.S_IMODE(info.st_mode),
                sha256=digest,
            )
        else:
            raise ValueError("non-regular entry in bytecode scope")
    return result


class BytecodePolicy:
    """Private per-variant external caches plus the currently active whole venv."""

    def __init__(self, slot, artifacts: Path):
        self._slot = slot
        self._slot_root = slot.root
        self._slot_identity = _identity(slot.root)
        self.root = Path(tempfile.mkdtemp(prefix="g18-pyc-", dir=artifacts)).resolve()
        self._roots = {side: self.root / side for side in ("a", "b")}
        for root in self._roots.values():
            root.mkdir(mode=0o700)
        self._identities = {
            root: _identity(root) for root in (self.root, *self._roots.values())
        }

    def external(self, side):
        if side not in self._roots:
            raise ValueError("bytecode variant must be a or b")
        return self._roots[side]

    def checkpoint(self):
        slot = self._slot.checkpoint()
        for root, expected in self._identities.items():
            if _identity(root) != expected:
                raise ValueError("checkpoint cache directory changed")
        return dict(
            root=str(self.root),
            identities={
                str(path): list(value) for path, value in self._identities.items()
            },
            inventories={
                side: {
                    "external": inventory(self.external(side)),
                    "installed": inventory(
                        self._slot.prefix
                        if slot["receipt"]["active"] == side
                        else self._slot.root / side,
                        installation=True,
                    ),
                }
                for side in ("a", "b")
            },
        )

    @classmethod
    def reopen(cls, slot, value):
        subject = cls.__new__(cls)
        subject._slot = slot
        subject._slot_root = slot.root
        subject._slot_identity = _identity(slot.root)
        subject.root = Path(value["root"])
        subject._roots = {side: subject.root / side for side in ("a", "b")}
        subject._identities = {
            Path(path): tuple(item) for path, item in value["identities"].items()
        }
        if set(subject._identities) != {subject.root, *subject._roots.values()}:
            raise ValueError("invalid checkpoint cache roots")
        if subject.checkpoint() != value:
            raise ValueError("bytecode changed during pause")
        return subject

    def _require_active(self, side):
        receipt = self._slot.receipt
        if not receipt["busy"] or receipt["failed"] or receipt["active"] != side:
            raise RuntimeError("cache policy requires the active serial slot callback")
        if (
            self._slot.root != self._slot_root
            or _identity(self._slot_root) != self._slot_identity
            or self._slot.prefix != self._slot_root / "active"
        ):
            raise ValueError("bytecode installation ownership changed")
        for root, identity in self._identities.items():
            if _identity(root) != identity:
                raise ValueError("external bytecode directory identity changed")
        if list(_identity(self._slot.prefix)) != receipt["identities"][side]:
            raise ValueError("active bytecode installation identity changed")

    def inspect(self, side):
        self._require_active(side)
        return {
            "installed": inventory(self._slot.prefix, installation=True),
            "external": inventory(self.external(side)),
        }

    def prepare(self, side, mode):
        """After source checks and reset: clear if absent, then file-only verify.

        No target Python may run between this and the actual measured launch.
        For warm mode the coordinator separately proves the declared warmup ran.
        """
        if mode not in ("warm", "absent"):
            raise ValueError("bytecode mode must be warm or absent")
        before = self.inspect(side)
        if mode == "absent":
            roots = {"installed": self._slot.prefix, "external": self.external(side)}
            for scope, entries in before.items():
                for relative, expected in entries.items():
                    self._require_active(side)
                    path = roots[scope] / relative
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode) or (
                        info.st_dev,
                        info.st_ino,
                        info.st_size,
                        info.st_mtime_ns,
                    ) != (
                        expected["dev"],
                        expected["ino"],
                        expected["size"],
                        expected["mtime_ns"],
                    ):
                        raise ValueError("bytecode changed before removal")
                    path.unlink()  # Exact inventoried .pyc in our quiescent owned scope.
        ready = self.inspect(side)
        if mode == "absent" and any(ready.values()):
            raise ValueError("task-owned bytecode remains before launch")
        if mode == "warm" and ready != before:
            raise ValueError("bytecode changed during file-only inspection")
        return dict(
            mode=mode,
            installed_prefix=str(self._slot.prefix),
            external_prefix=str(self.external(side)),
            before=before,
            ready=ready,
            write_policy="normal Python writes; -I children use adjacent installed caches",
            exclusions="base Python/stdlib shared as found; Product-state bytecode seed-preserved",
        )
