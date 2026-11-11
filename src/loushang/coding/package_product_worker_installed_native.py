"""Public Coding values and readers for an installed inert Linux H6 release."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from loushang.harness.package_product._linux_worker_native_release import (
    _PRODUCT_NATIVE_RELEASE_ROOT,
    _LinuxWorkerNativeReleaseCustody,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)

from .package_product_worker_native_approval import (
    CodingWorkerNativeApprovalError,
    CodingWorkerNativeApprovalJournal,
    CodingWorkerNativeReleaseApprovalV1,
    CodingWorkerNativeReleaseReviewV1,
)
from .package_product_worker_native_release import (
    CodingWorkerNativeReleaseError,
    _release_verifier,
)
from .package_product_worker_policy import CodingWorkerNativeClosureV1


@dataclass(frozen=True, slots=True)
class CodingWorkerNativeLaunchMaterialV1:
    """Verified Product locator for Hosting's descriptor-sealing capture.

    This is not a launch capability. Hosting must capture and verify the
    launcher descriptor, and the Worker receipt must still be current.
    """

    launcher_path: Path
    closure: CodingWorkerNativeClosureV1


def open_coding_product_installed_worker_release_reader(
    product_owner: PosixLocalWheelProductSessionOwner,
) -> CodingProductInstalledWorkerReleaseReader:
    """Bind the installed native catalog to one explicit Coding Product owner."""
    return _product_native_release_custody().open_reader(product_owner)


class CodingProductInstalledWorkerReleaseReader:
    """Recheck Product's retained source Wheel and receipt on each read."""

    def __init__(self, *, product_owner: PosixLocalWheelProductSessionOwner) -> None:
        self._product_owner = product_owner
        self._root = product_owner.state_root / _PRODUCT_NATIVE_RELEASE_ROOT

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._product_owner.gc_gate

    @property
    def product_owner(self) -> PosixLocalWheelProductSessionOwner:
        return self._product_owner

    def current_closure(self) -> CodingWorkerNativeClosureV1:
        return self.current_launch_material().closure

    def current_launch_material(self) -> CodingWorkerNativeLaunchMaterialV1:
        """Reopen the Product release before giving Hosting its native locator."""
        return _product_native_release_custody().current_launch_material(
            self._root, self._product_owner
        )


def verify_coding_product_native_release_root(
    root_path: Path, product_owner: PosixLocalWheelProductSessionOwner
) -> tuple[CodingWorkerNativeClosureV1, dict[str, object]]:
    """Verify one complete Product-staged or published native installation."""
    return _product_native_release_custody().verify_root(root_path, product_owner)


def verify_coding_product_native_release_descriptor(
    root: int, product_owner: PosixLocalWheelProductSessionOwner
) -> tuple[CodingWorkerNativeClosureV1, dict[str, object]]:
    """Verify all Product facts from the same opened installation directory."""
    return _product_native_release_custody().verify_descriptor(root, product_owner)


def read_coding_product_native_release_receipt(
    target: Path, product_owner: PosixLocalWheelProductSessionOwner
) -> dict[str, object]:
    """Read one exact Product source receipt without following a replaced name."""
    return _product_native_release_custody().read_receipt(target, product_owner)


class CodingLinuxInstalledWorkerReleaseReader:
    """Reopen exact Wheel RECORD and native bytes under a private Product root."""

    def __init__(
        self, *, installation_root: Path, gc_gate: PluginPackageGcReservationJournal
    ) -> None:
        if (
            not isinstance(installation_root, Path)
            or not installation_root.is_absolute()
        ):
            raise ValueError("Worker native installation root must be absolute")
        if not isinstance(gc_gate, PluginPackageGcReservationJournal):
            raise TypeError("Worker native installation requires a Product GC gate")
        self._root = installation_root
        self._gc_gate = gc_gate

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._gc_gate

    def current_closure(self) -> CodingWorkerNativeClosureV1:
        return _release_verifier().installed_closure(
            self._root, version_provider=lambda: version("loushang")
        )


def _product_native_release_custody(
    *,
    wheel_version: Callable[[], str] | None = None,
) -> _LinuxWorkerNativeReleaseCustody[
    CodingWorkerNativeReleaseApprovalV1,
    CodingWorkerNativeReleaseReviewV1,
    CodingWorkerNativeClosureV1,
    CodingWorkerNativeLaunchMaterialV1,
    CodingProductInstalledWorkerReleaseReader,
]:
    return _LinuxWorkerNativeReleaseCustody(
        product_id="coding",
        product_label="Coding",
        trust_class="local-worker-candidate",
        approval_type=lambda: CodingWorkerNativeReleaseApprovalV1,
        approval_owner_type=lambda: CodingWorkerNativeApprovalJournal,
        review_factory=lambda: CodingWorkerNativeReleaseReviewV1.create,
        reader_factory=lambda: CodingProductInstalledWorkerReleaseReader,
        material_factory=lambda: CodingWorkerNativeLaunchMaterialV1,
        verifier=_release_verifier,
        error_type=lambda: CodingWorkerNativeReleaseError,
        approval_error_type=lambda: CodingWorkerNativeApprovalError,
        wheel_version=wheel_version
        if wheel_version is not None
        else lambda: version("loushang"),
        installed_version=lambda: version("loushang"),
    )
