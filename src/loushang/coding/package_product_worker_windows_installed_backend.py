"""Product-private custody of one approved Windows Worker backend Wheel.

The retained Wheel is a source fact, not a launch receipt. Every read rejoins
the current Product approval and the actual installed Python/Hosting material.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_product_worker_native_approval import (
    CodingWorkerNativeApprovalError,
    CodingWorkerNativeReleaseReviewV1,
)
from .package_product_worker_policy import CodingWorkerNativeClosureV1
from .package_product_worker_windows_backend_release import (
    inspect_coding_windows_worker_backend_material,
)
from .package_product_worker_windows_native_approval_owner import (
    CodingWindowsWorkerNativeApprovalOwner,
)

_NAME = "worker-native-backend-release-v1.whl"
_MAX_WHEEL_BYTES = 64 * 1024 * 1024


class CodingWindowsWorkerInstalledBackendError(RuntimeError):
    """The approved Product source is absent, stale, or incomplete."""


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerInstalledBackendV1:
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
    if (
        type(loushang_wheel) is not bytes
        or not 0 < len(loushang_wheel) <= _MAX_WHEEL_BYTES
        or type(review_id) is not str
    ):
        raise ValueError("Windows Worker backend installation input is invalid")
    with product.gc_gate.guard(require_write=True):
        product.assert_root_gc_authority_current()
        material = inspect_coding_windows_worker_backend_material(
            product, loushang_wheel=loushang_wheel
        )
        review = material.review
        if review.review_id != review_id:
            raise CodingWindowsWorkerInstalledBackendError(
                "Windows Worker backend review changed"
            )
        generation = _current_approval_generation(product, review)
        with product.epoch_runtime.borrow_product_state_root_descriptor():
            path = _release_path(product)
            existing = read_windows_private_receipt(
                path,
                maximum_bytes=_MAX_WHEEL_BYTES,
                allow_unpublished_stage=True,
            )
            if existing is None:
                write_windows_private_receipt(
                    path, loushang_wheel, maximum_bytes=_MAX_WHEEL_BYTES
                )
            elif existing != loushang_wheel:
                raise CodingWindowsWorkerInstalledBackendError(
                    "Windows Worker backend replacement requires a new operation"
                )
            retained = read_windows_private_receipt(
                path, maximum_bytes=_MAX_WHEEL_BYTES
            )
            if retained != loushang_wheel:
                raise CodingWindowsWorkerInstalledBackendError(
                    "Windows Worker backend Product source changed"
                )
        product.assert_root_gc_authority_current()
        if _current_approval_generation(product, review) != generation:
            raise CodingWindowsWorkerInstalledBackendError(
                "Windows Worker backend approval changed"
            )
        return CodingWindowsWorkerInstalledBackendV1(
            review=review,
            approval_generation=generation,
            expectation=material.expectation,
        )


def read_coding_windows_worker_installed_backend_release(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerInstalledBackendV1:
    """Recheck Product custody, native material, and approval on every read."""

    _require_product(product)
    try:
        with product.gc_gate.guard():
            product.assert_root_gc_authority_current()
            with product.epoch_runtime.borrow_product_state_root_descriptor():
                wheel = read_windows_private_receipt(
                    _release_path(product), maximum_bytes=_MAX_WHEEL_BYTES
                )
            if wheel is None:
                raise CodingWindowsWorkerInstalledBackendError(
                    "Windows Worker backend Product source is absent"
                )
            material = inspect_coding_windows_worker_backend_material(
                product, loushang_wheel=wheel
            )
            review = material.review
            generation = _current_approval_generation(product, review)
            product.assert_root_gc_authority_current()
            return CodingWindowsWorkerInstalledBackendV1(
                review=review,
                approval_generation=generation,
                expectation=material.expectation,
            )
    except (
        CodingWindowsPrivateReceiptError,
        CodingWorkerNativeApprovalError,
        PackageWheelVerificationError,
        ImportError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise CodingWindowsWorkerInstalledBackendError(
            "Windows Worker backend Product source cannot be verified"
        ) from exc


def _current_approval_generation(
    product: WindowsLocalWheelProductSessionOwner,
    review: CodingWorkerNativeReleaseReviewV1,
) -> int:
    decision = CodingWindowsWorkerNativeApprovalOwner(product).current()
    if (
        decision is None
        or decision.action != "approve"
        or decision.approval != review.approval
    ):
        raise CodingWindowsWorkerInstalledBackendError(
            "Windows Worker backend Product approval is not current"
        )
    return decision.generation


def _release_path(product: WindowsLocalWheelProductSessionOwner) -> Path:
    return product.state_root / _NAME


def _require_product(product: WindowsLocalWheelProductSessionOwner) -> None:
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or not any(
            binding.source_trust_class == "local-worker-candidate"
            for binding in product.policy.bindings
        )
    ):
        raise ValueError("Windows Worker candidate Product owner is required")
    product.assert_root_gc_authority_current()


__all__ = [
    "CodingWindowsWorkerInstalledBackendError",
    "CodingWindowsWorkerInstalledBackendV1",
    "CodingWindowsWorkerInstalledBackendReader",
    "install_coding_windows_worker_backend_release",
    "read_coding_windows_worker_installed_backend_release",
]
