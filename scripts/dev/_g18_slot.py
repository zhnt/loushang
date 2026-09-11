"""A private fixed execution path for two parked installations, Linux only.

Only directory identity and serial switching live here. Trusted synchronous
callbacks own installation, source verification, cache policy and execution via
the existing retained process owner. They must return only after full settlement.
Never execute parked paths. An exception leaves the slot closed and intact.
"""

from __future__ import annotations

import os
import platform
import stat
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path


def _identity(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("installation slot must be a real directory")
    return info.st_dev, info.st_ino


class InstallationSlot:
    """Two whole venvs built and run at one fresh canonical absolute prefix."""

    def __init__(self, parent: Path):
        if platform.system() != "Linux":
            raise ValueError("Linux installation slot only")
        self.root = Path(tempfile.mkdtemp(prefix="g18-slot-", dir=parent)).resolve()
        self.prefix = self.root / "active"
        self._root_identity = _identity(self.root)
        self._identities = {}
        self._active = None
        self._busy = False
        self._failed = False
        self._thread = threading.get_ident()

    def _paths(self):
        if (
            self.root.resolve() != self.root
            or _identity(self.root) != self._root_identity
        ):
            raise ValueError("installation slot root identity changed")
        for side in ("a", "b"):
            parked = self.root / side
            if side in self._identities:
                selected = self.prefix if side == self._active else parked
                if _identity(selected) != self._identities[side]:
                    raise ValueError("installation variant identity changed")
            if (
                side not in self._identities or side == self._active
            ) and os.path.lexists(parked):
                raise ValueError("unexpected parked installation")
        if self._active is None and os.path.lexists(self.prefix):
            raise ValueError("unexpected active installation")

    @contextmanager
    def _exclusive(self):
        if self._failed or self._busy or threading.get_ident() != self._thread:
            raise RuntimeError("installation owner pending or slot failed")
        self._busy = True
        try:
            self._paths()
            yield
            self._paths()
        except BaseException:
            self._failed = True
            raise
        finally:
            self._busy = False

    @staticmethod
    def _side(side):
        if side not in ("a", "b"):
            raise ValueError("installation variant must be a or b")

    def _rename(self, source, destination):
        # All endpoints are exact children of our exclusive fresh directory.
        # No overwrite, shutil.move/copy fallback, or cross-filesystem transfer.
        if os.path.lexists(destination):
            raise ValueError("installation rename destination already exists")
        if _identity(source)[0] != self._root_identity[0]:
            raise ValueError("installation must share the slot filesystem")
        os.rename(source, destination)

    def provision(self, side, operation):
        """Create and verify a venv at prefix, then park it after owner return."""
        self._side(side)
        with self._exclusive():
            if side in self._identities or self._active is not None:
                raise RuntimeError("installation already provisioned or active")
            result = operation(self.prefix)
            # Register the newly built active tree before checking all paths;
            # a later failure still leaves its actual location in the receipt.
            self._identities[side] = _identity(self.prefix)
            self._active = side
            self._paths()
            self._rename(self.prefix, self.root / side)
            self._active = None
        return result

    def run(self, side, operation):
        """Activate, preverify, prepare, execute and postverify under one guard.

        Verification/preparation are caller work outside its measured interval.
        If any owned process fails to settle, operation must not return success.
        """
        self._side(side)
        with self._exclusive():
            if set(self._identities) != {"a", "b"}:
                raise RuntimeError("both installations must be provisioned")
            if side != self._active:
                if self._active is not None:
                    self._rename(self.prefix, self.root / self._active)
                    self._active = None
                self._rename(self.root / side, self.prefix)
                self._active = side
                self._paths()
            result = operation(self.prefix)
        return result

    @property
    def receipt(self):
        # After a failed/interrupted rename, active is the last registered side,
        # not a recovery token or proof of the physical location. Never resume.
        return dict(
            root=str(self.root),
            prefix=str(self.prefix),
            active=self._active,
            busy=self._busy,
            failed=self._failed,
            identities={side: list(value) for side, value in self._identities.items()},
        )

    def checkpoint(self):
        """Explicit idle token; the ordinary diagnostic receipt is not resumable."""
        if self._busy or self._failed or threading.get_ident() != self._thread:
            raise RuntimeError("slot is not safely checkpointable")
        self._paths()
        return dict(receipt=self.receipt, root_identity=list(self._root_identity))

    @classmethod
    def reopen(cls, value):
        if platform.system() != "Linux":
            raise ValueError("Linux installation slot only")
        receipt = value["receipt"]
        if (
            receipt["busy"]
            or receipt["failed"]
            or set(receipt["identities"]) != {"a", "b"}
        ):
            raise ValueError("cannot reopen an unsafe slot")
        subject = cls.__new__(cls)
        subject.root = Path(receipt["root"])
        subject.prefix = Path(receipt["prefix"])
        if (
            subject.root.resolve() != subject.root
            or subject.prefix != subject.root / "active"
        ):
            raise ValueError("slot checkpoint prefix changed")
        subject._root_identity = tuple(value["root_identity"])
        subject._identities = {
            side: tuple(item) for side, item in receipt["identities"].items()
        }
        subject._active = receipt["active"]
        if subject._active not in (None, "a", "b"):
            raise ValueError("invalid checkpoint active side")
        subject._busy = subject._failed = False
        subject._thread = threading.get_ident()
        subject._paths()
        return subject
