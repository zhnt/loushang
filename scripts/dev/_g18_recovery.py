"""Opaque, task-owned recovery input; no Product codecs or process supervision.

The caller supplies synchronous operations which return only after the existing
retained process owner settles. This object serializes those operations and never
resets after a failed operation. Its control directory is outside Product state.
It preserves content, modes and mtime, not inode/ctime or in-memory/OS lock state.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path


def inventory(root: Path) -> dict:
    """Bounded regular-file tree; unknown inputs are errors, not exclusions."""
    entries = {}
    size = 0
    pending = [root]
    while pending:
        path = pending.pop()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o7000:
            raise ValueError("privileged mode in recovery input")
        if stat.S_ISDIR(info.st_mode):
            value = dict(kind="directory", mode=mode, mtime_ns=info.st_mtime_ns)
            with os.scandir(path) as children:
                for child in children:
                    pending.append(Path(child.path))
                    if len(entries) + len(pending) >= 10000:
                        raise ValueError("recovery input exceeds 10000 entries")
        elif stat.S_ISREG(info.st_mode):
            size += info.st_size
            if size > 64 * 1024 * 1024:
                raise ValueError("recovery input exceeds 64 MiB")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            value = dict(
                kind="file",
                mode=mode,
                mtime_ns=info.st_mtime_ns,
                size=info.st_size,
                sha256=digest,
            )
        else:
            raise ValueError("non-regular recovery input")
        entries[path.relative_to(root).as_posix()] = value
        if len(entries) > 10000:
            raise ValueError("recovery input exceeds 10000 entries")
    if entries["."]["kind"] != "directory":
        raise ValueError("recovery root must be a directory")
    return entries


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _identity(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("recovery directory identity changed")
    return info.st_dev, info.st_ino


class RecoveryState:
    """One fresh subject, one immutable seed, serial retained-owner operations.

    No public attachment to an existing subject and no retry/reset after failure.
    Artifacts and all failed input/staging trees are retained for diagnosis.
    Callbacks must use the existing retained owner, not a detached Popen/thread.
    """

    def __init__(self, temporary_parent: Path, artifacts: Path):
        if platform.system() != "Linux":
            raise ValueError("Linux recovery state only")
        self.arena = Path(
            tempfile.mkdtemp(prefix="g18-recovery-", dir=temporary_parent)
        ).resolve()
        self.subject = self.arena / "subject"
        self.control = self.arena / "control"
        self.subject.mkdir(mode=0o700)
        self.control.mkdir(mode=0o700)
        self.archive = Path(
            tempfile.mkdtemp(prefix="g18-seed-", dir=artifacts)
        ).resolve()
        self.seed = self.archive / "input"
        self._arena_identity = _identity(self.arena)
        self._subject_identity = _identity(self.subject)
        self._busy = False
        self._failed = False
        self._expected = None
        self._created_at = None
        self._restores = 0
        self._thread = threading.get_ident()

    def _idle(self):
        if self._busy or self._failed or threading.get_ident() != self._thread:
            raise RuntimeError("recovery owner pending or operation failed")
        self._paths()

    def _paths(self):
        if (
            _identity(self.arena) != self._arena_identity
            or _identity(self.subject) != self._subject_identity
        ):
            raise ValueError("recovery subject identity changed")

    @contextmanager
    def _exclusive(self):
        self._idle()
        self._busy = True
        try:
            yield
        except BaseException:
            self._failed = True
            raise
        finally:
            self._busy = False

    def prepare(self, operation):
        """Run real seed setup; copy only after its complete owner has returned."""
        with self._exclusive():
            if self._expected is not None or self.seed.exists():
                raise RuntimeError("recovery seed already prepared")
            result = operation(self.subject, self.control)
            self._paths()
            before = inventory(self.subject)
            shutil.copytree(self.subject, self.seed, symlinks=True)
            if inventory(self.subject) != before or inventory(self.seed) != before:
                raise ValueError("recovery seed changed during capture")
            self._expected = before
            self._created_at = time.time()
            (self.archive / "manifest.json").write_text(
                json.dumps(self.receipt, indent=2) + "\n"
            )
        return result

    @property
    def receipt(self):
        if self._expected is None:
            raise RuntimeError("recovery seed not prepared")
        # Never expose the coordinator's independent expected manifest by alias.
        return json.loads(
            json.dumps(
                dict(
                    schema_version=1,
                    subject=str(self.subject),
                    archive=str(self.archive),
                    created_at=self._created_at,
                    manifest=self._expected,
                    sha256=_digest(self._expected),
                    restores=self._restores,
                    file_identity="inode/ctime not preserved; no warm Store-head claim",
                )
            )
        )

    def _restore(self):
        self._paths()
        if self._expected is None:
            raise RuntimeError("recovery seed not prepared")
        try:
            if inventory(self.seed) != self._expected:
                raise ValueError("recovery snapshot manifest mismatch")
            current = inventory(self.subject)
            staged = Path(tempfile.mkdtemp(prefix="restore-", dir=self.arena))
            shutil.copytree(self.seed, staged, symlinks=True, dirs_exist_ok=True)
            if (
                inventory(staged) != self._expected
                or inventory(self.seed) != self._expected
            ):
                raise ValueError("recovery snapshot copy mismatch")
            self._paths()
            # Only this fresh task-owned subject is removed. The fd-safe Linux
            # remover never follows symlinks; validate all entries before chmod.
            if not shutil.rmtree.avoids_symlink_attacks:
                raise RuntimeError("fd-safe recovery removal required")
            for relative, value in current.items():
                if value["kind"] == "directory":
                    path = self.subject / relative
                    path.chmod(
                        value["mode"] | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
                    )
            shutil.rmtree(self.subject)
            os.replace(staged, self.subject)
            self._subject_identity = _identity(self.subject)
            if inventory(self.subject) != self._expected:
                raise ValueError("restored recovery input mismatch")
            self._restores += 1
        except BaseException:
            self._failed = True
            raise

    def sample(self, operation):
        """Reset even the first/warmup sample, then invoke its retained owner."""
        with self._exclusive():
            self._restore()
            result = operation(self.subject, self.control)
            if inventory(self.seed) != self._expected:
                raise ValueError("candidate changed recovery snapshot")
        return result
