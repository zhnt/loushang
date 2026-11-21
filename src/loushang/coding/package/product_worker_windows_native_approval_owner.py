"""Product-bound approval decisions for the Windows Worker backend release.

An approval is inert until Product privately installs the reviewed Wheel and
Hosting rechecks the actual backend material at native capture.
"""

from __future__ import annotations

from loushang.harness.package_product._windows_worker_backend_release import (
    change_windows_backend_approval,
    current_windows_backend_approval,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._native_approval import (
    NATIVE_APPROVAL_JOURNAL_NAME,
)

from .product_worker_native_approval import CodingWorkerNativeApprovalDecisionV1
from .product_worker_windows_backend_release import (
    _require_candidate_product,
    review_coding_windows_worker_backend_release,
)
from .product_worker_windows_native_approval_journal import (
    CodingWindowsWorkerNativeApprovalJournal,
)


class CodingWindowsWorkerNativeApprovalOwner:
    """Review, record, and revoke one Product scope's native approval."""

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        _require_candidate_product(product)
        product.assert_root_gc_authority_current()
        self._product = product
        self._journal = CodingWindowsWorkerNativeApprovalJournal(
            product.state_root / NATIVE_APPROVAL_JOURNAL_NAME,
            scope_id=product.policy.project_scope_id,
        )

    def current(self) -> CodingWorkerNativeApprovalDecisionV1 | None:
        return current_windows_backend_approval(self._product, self._journal)

    def approve(
        self,
        *,
        loushang_wheel: bytes,
        review_id: str,
        operation_id: str,
        expected_generation: int,
    ) -> CodingWorkerNativeApprovalDecisionV1:
        """Recheck the running release and persist an exact operator review."""

        review = review_coding_windows_worker_backend_release(
            self._product, loushang_wheel=loushang_wheel
        )
        if review.review_id != review_id:
            raise ValueError("Windows Worker backend review changed")
        return change_windows_backend_approval(
            self,
            operation_id=operation_id,
            expected_generation=expected_generation,
            action="approve",
            review=review,
        )

    def revoke(
        self, *, operation_id: str, expected_generation: int
    ) -> CodingWorkerNativeApprovalDecisionV1:
        """Fence a prior approval even after its backend material is lost."""

        return change_windows_backend_approval(
            self,
            operation_id=operation_id,
            expected_generation=expected_generation,
            action="revoke",
            review=None,
        )


__all__ = ["CodingWindowsWorkerNativeApprovalOwner"]
