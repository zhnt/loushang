"""Product-bound approval decisions for the Windows Worker backend release.

An approval is inert until Product privately installs the reviewed Wheel and
Hosting rechecks the actual backend material at native capture.
"""

from __future__ import annotations

from loushang.harness.package_product._windows_worker_backend_release import (
    _WindowsBackendApprovalOwnerMethods,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .product_worker_native_approval import CodingWorkerNativeApprovalDecisionV1
from .product_worker_windows_backend_release import (
    _require_candidate_product,
    review_coding_windows_worker_backend_release,
)
from .product_worker_windows_native_approval_journal import (
    CodingWindowsWorkerNativeApprovalJournal,
)


class CodingWindowsWorkerNativeApprovalOwner(
    _WindowsBackendApprovalOwnerMethods[CodingWorkerNativeApprovalDecisionV1]
):
    """Review, record, and revoke one Product scope's native approval."""

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        self._bind_backend_approval(
            product, _require_candidate_product, CodingWindowsWorkerNativeApprovalJournal
        )

    def current(self) -> CodingWorkerNativeApprovalDecisionV1 | None:
        return self._read_backend_approval()

    def approve(
        self,
        *,
        loushang_wheel: bytes,
        review_id: str,
        operation_id: str,
        expected_generation: int,
    ) -> CodingWorkerNativeApprovalDecisionV1:
        """Recheck the running release and persist an exact operator review."""

        return self._change_backend_approval(
            operation_id=operation_id,
            expected_generation=expected_generation,
            action="approve",
            review=review_coding_windows_worker_backend_release(
                self._product, loushang_wheel=loushang_wheel
            ),
            review_id=review_id,
        )

    def revoke(
        self, *, operation_id: str, expected_generation: int
    ) -> CodingWorkerNativeApprovalDecisionV1:
        """Fence a prior approval even after its backend material is lost."""

        return self._change_backend_approval(
            operation_id=operation_id,
            expected_generation=expected_generation,
            action="revoke",
        )


__all__ = ["CodingWindowsWorkerNativeApprovalOwner"]
