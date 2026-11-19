"""Read-only Product evidence for a normally closed Windows C5 attempt.

The C5 boot-identity slot binds this authority to the original Product runtime
incarnation. It does not claim an OS boot observation or authorize changed-boot
or orphan-lease recovery. Those paths require separate offline authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.package_product._windows_worker_recovery import (
    WindowsProductWorkerCleanupEvidence,
)

from .product_worker_activation_history import CodingProductWorkerRetainedAttemptV1
from .product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from .product_worker_windows_orphan_review import (
    CodingWindowsWorkerOrphanRuntimeReviewV1,
    _review_under_gc_guard,
    review_coding_windows_product_worker_orphan_runtime,
)
from .product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
)
from .product_worker_windows_receipt import CodingWindowsWorkerProductReceiptOwner

_AUTHORITY_ID = "coding.windows-worker.cleanup-evidence.v2"
_AUTHORITY_FINGERPRINT = sha256(
    b"loushang.coding.windows-worker.cleanup-evidence/v2"
).hexdigest()


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerLiveCleanupReviewV1:
    """One live-runtime read; no field grants cleanup or Package GC."""

    runtime: CodingWindowsWorkerOrphanRuntimeReviewV1
    native: WindowsWorkerProvisioningAttemptV1 | None
    activation: CodingProductWorkerRetainedAttemptV1 | None


class CodingWindowsWorkerCleanupEvidenceAuthority(
    WindowsProductWorkerCleanupEvidence[
        CodingWindowsWorkerProductReceiptOwner,
        CodingWindowsWorkerLiveCleanupReviewV1,
        CodingProductWorkerRetainedAttemptV1,
    ]
):
    """Reopen an exact native, Supervisor, receipt, and C5 settlement join."""

    _review_type = CodingWindowsWorkerLiveCleanupReviewV1
    authority_id = _AUTHORITY_ID
    authority_fingerprint = _AUTHORITY_FINGERPRINT
    _cleanup_product_id = "coding"
    _cleanup_receipt_owner_type = CodingWindowsWorkerProductReceiptOwner
    _cleanup_review_under_guard = staticmethod(_review_under_gc_guard)
    _cleanup_inspect_native = staticmethod(
        inspect_coding_windows_product_worker_provisioning_attempts
    )
    _cleanup_activation_journal = staticmethod(
        CodingWindowsWorkerActivationStateJournal
    )
    _cleanup_review_runtime = staticmethod(
        review_coding_windows_product_worker_orphan_runtime
    )

    @property
    def host_identity(self) -> str:
        return "coding-windows-store:" + self._product.epoch_runtime.registry.store_id

    @property
    def boot_identity(self) -> str:
        return "coding-windows-runtime:" + self._receipt.policy.product_runtime_id

    def verify_changed_boot_absence(self, **_arguments: object) -> bool:
        return False

    def verify_registered_lease_expired(self, **_arguments: object) -> bool:
        return False


__all__ = [
    "CodingWindowsWorkerCleanupEvidenceAuthority",
    "CodingWindowsWorkerLiveCleanupReviewV1",
]
