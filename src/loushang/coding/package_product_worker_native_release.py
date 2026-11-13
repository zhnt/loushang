"""Read one generated Linux H6 release as inert Worker closure evidence.

The release directory is a build input, not an installed native distribution.
This reader cannot issue a Product receipt or authorize a Worker launch.
"""

from __future__ import annotations

from pathlib import Path

from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.worker._linux_native_release import _LinuxNativeReleaseVerifier

from .package_product_worker_policy import (
    CodingWorkerNativeClosureReadError,
    CodingWorkerNativeClosureV1,
)

_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "hosting/native/contained_launcher_linux_x86_64.c"
)


class CodingWorkerNativeReleaseError(CodingWorkerNativeClosureReadError):
    """The generated release cannot supply exact native closure facts."""


class CodingLinuxWorkerReleaseCatalogReader:
    """Reopen generated build bytes under the Product GC gate identity.

    This candidate accepts a caller-selected private release directory. A
    production reader must instead bind an installed platform distribution.
    """

    def __init__(
        self,
        *,
        release_root: Path,
        gc_gate: PluginPackageGcReservationJournal,
    ) -> None:
        if not isinstance(release_root, Path) or not release_root.is_absolute():
            raise ValueError("Worker release root must be absolute")
        if not isinstance(gc_gate, PluginPackageGcReservationJournal):
            raise TypeError("Worker release requires a Product GC gate")
        self._release_root = release_root
        self._gc_gate = gc_gate

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._gc_gate

    def current_closure(self) -> CodingWorkerNativeClosureV1:
        return _release_verifier().generated_closure(self._release_root)


def _release_verifier() -> _LinuxNativeReleaseVerifier[CodingWorkerNativeClosureV1]:
    return _LinuxNativeReleaseVerifier(
        source_path=_SOURCE,
        error_type=CodingWorkerNativeReleaseError,
        closure_type=CodingWorkerNativeClosureV1,
    )


def _read_member(
    root: int,
    name: str,
    limit: int,
    *,
    executable: bool = False,
    installed: bool = False,
) -> bytes:
    return _release_verifier().read_member(
        root, name, limit, executable=executable, installed=installed
    )
