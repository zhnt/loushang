"""Product-private custody of one approved Windows Worker backend Wheel.

The retained Wheel is a source fact, not a launch receipt. Every read rejoins
the current Product approval and the actual installed Python/Hosting material.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_backend_release import (
    _WindowsBackendInstalledMethods,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageWheelVerificationError,
)
from loushang.hosting.windows_backend_material import (
    WindowsBackendMaterialExpectationV1,
)

from .package_legacy_windows_receipt import (
    CodingWindowsPrivateReceiptError,
    _receipt_io,
)
from .package_product_worker_native_approval import (
    CodingWorkerNativeApprovalError,
    CodingWorkerNativeReleaseReviewV1,
)
from .package_product_worker_policy import CodingWorkerNativeClosureV1
from .package_product_worker_windows_backend_release import (
    CodingWindowsWorkerBackendMaterialReviewV1,
    _require_candidate_product,
)
from .package_product_worker_windows_native_approval_owner import (
    CodingWindowsWorkerNativeApprovalOwner,
)

_NAME = "worker-native-backend-release-v1.whl"
_MAX_WHEEL_BYTES = 64 * 1024 * 1024


class CodingWindowsWorkerInstalledBackendError(RuntimeError):
    """The approved Product source is absent, stale, or incomplete."""


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerInstalledBackendV1(_WindowsBackendInstalledMethods):
    review: CodingWorkerNativeReleaseReviewV1
    approval_generation: int
    expectation: WindowsBackendMaterialExpectationV1

    def native_closure(self) -> CodingWorkerNativeClosureV1:
        """Bind the reviewed backend and approval generation as native facts."""

        approval = self.review.approval
        return CodingWorkerNativeClosureV1(
            native_platform="windows-amd64",
            native_profile_catalog_revision=(
                f"h6-windows:{approval.catalog_sha256}:g{self.approval_generation}"
            ),
            containment_launcher_digest=approval.launcher_sha256,
            containment_profile_digest=approval.profile_sha256,
        )


class CodingWindowsWorkerInstalledBackendReader:
    """Product-bound native closure port; this grants no launch authority."""

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        _require_product(product)
        self._product = product

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._product.gc_gate

    @property
    def product_owner(self) -> WindowsLocalWheelProductSessionOwner:
        return self._product

    def current_closure(self) -> CodingWorkerNativeClosureV1:
        return read_coding_windows_worker_installed_backend_release(
            self._product
        ).native_closure()


def install_coding_windows_worker_backend_release(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    loushang_wheel: bytes,
    review_id: str,
) -> CodingWindowsWorkerInstalledBackendV1:
    """Publish an independently approved, exact Wheel once in Product state."""
    _require_product(product)
    return CodingWindowsWorkerInstalledBackendV1._install(
        product, loushang_wheel=loushang_wheel, review_id=review_id
    )


def read_coding_windows_worker_installed_backend_release(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerInstalledBackendV1:
    """Recheck Product custody, native material, and approval on every read."""
    _require_product(product)
    return CodingWindowsWorkerInstalledBackendV1._read(product)


def _require_product(product: WindowsLocalWheelProductSessionOwner) -> None:
    _require_candidate_product(product)
    product.assert_root_gc_authority_current()


__all__ = [
    "CodingWindowsWorkerInstalledBackendError",
    "CodingWindowsWorkerInstalledBackendV1",
    "CodingWindowsWorkerInstalledBackendReader",
    "install_coding_windows_worker_backend_release",
    "read_coding_windows_worker_installed_backend_release",
]


CodingWindowsWorkerInstalledBackendV1._material_type = (
    CodingWindowsWorkerBackendMaterialReviewV1
)
CodingWindowsWorkerInstalledBackendV1._approval_owner_type = (
    CodingWindowsWorkerNativeApprovalOwner
)
CodingWindowsWorkerInstalledBackendV1._receipt_io = _receipt_io
CodingWindowsWorkerInstalledBackendV1._release_name = _NAME
CodingWindowsWorkerInstalledBackendV1._wheel_limit = _MAX_WHEEL_BYTES
CodingWindowsWorkerInstalledBackendV1._failure = (
    CodingWindowsWorkerInstalledBackendError
)
CodingWindowsWorkerInstalledBackendV1._read_errors = (
    CodingWindowsPrivateReceiptError,
    CodingWorkerNativeApprovalError,
    PackageWheelVerificationError,
    ImportError,
    OSError,
    TypeError,
    ValueError,
)
