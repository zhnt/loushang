"""Read-only Product evidence for a normally closed Windows C5 attempt.

The C5 boot-identity slot binds this authority to the original Product runtime
incarnation. It does not claim an OS boot observation or authorize changed-boot
or orphan-lease recovery. Those paths require separate offline authority.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import partial
from hashlib import sha256

from loushang.harness.package_product._worker_windows_attempt import (
    capture_windows_product_worker_cleanup,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.history._windows_recovery import (
    WindowsWorkerCleanupEvidence,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from .package_product_worker_windows_orphan_review import (
    CodingWindowsWorkerOrphanRuntimeReviewV1,
    _review_under_gc_guard,
    review_coding_windows_product_worker_orphan_runtime,
)
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .package_product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
)
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)

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
    WindowsWorkerCleanupEvidence[CodingWindowsWorkerLiveCleanupReviewV1]
):
    """Reopen an exact native, Supervisor, receipt, and C5 settlement join."""

    _review_type = CodingWindowsWorkerLiveCleanupReviewV1
    authority_id = _AUTHORITY_ID
    authority_fingerprint = _AUTHORITY_FINGERPRINT

    def __init__(
        self,
        *,
        receipt_owner: CodingWindowsWorkerProductReceiptOwner,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
    ) -> None:
        if (
            os.name != "nt"
            or type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
            or type(receipt) is not ProductWorkerActivationReceiptV1
            or type(request) is not ManagedWorkerLaunchRequestV1
            or request.identity.product_id != "coding"
            or request.identity.scope_id != receipt.policy.product_scope_id
            or request.identity.plugin_id != receipt.policy.plugin_id
            or request.identity.owner_generation
            != receipt.policy.owner_selection_generation
            or receipt_owner.product_owner.policy.product_id != "coding"
        ):
            raise ValueError("Windows C5 cleanup requires one bound Product attempt")
        receipt_owner.product_owner.assert_root_gc_authority_current()
        self._product: WindowsLocalWheelProductSessionOwner = (
            receipt_owner.product_owner
        )
        self._receipt = receipt
        self._attempt_id = request.identity.attempt_id
        self._owner_generation = request.identity.owner_generation
        self._request_fingerprint = request.fingerprint
        self._identity_fingerprint = request.identity.fingerprint
        self._mode = "normal"

    @classmethod
    def for_resume_parent_enrollment(
        cls,
        *,
        receipt_owner: CodingWindowsWorkerProductReceiptOwner,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> CodingWindowsWorkerCleanupEvidenceAuthority:
        """Bind the stable evidence domain before any attempt materialization.

        This authority is used only to open C5 and enroll a Resume parent. It
        carries no attempt witness and therefore cannot settle an activation.
        """

        if (
            os.name != "nt"
            or type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
            or type(receipt) is not ProductWorkerActivationReceiptV1
            or receipt_owner.product_owner.policy.product_id != "coding"
            or receipt.policy.product_id != "coding"
        ):
            raise ValueError("Windows C5 Resume enrollment requires one Product")
        receipt_owner.product_owner.assert_root_gc_authority_current()
        authority = cls.__new__(cls)
        authority._product = receipt_owner.product_owner
        authority._receipt = receipt
        authority._attempt_id = "resume-parent-enrollment"
        authority._owner_generation = receipt.policy.owner_selection_generation
        authority._request_fingerprint = "0" * 64
        authority._identity_fingerprint = "0" * 64
        authority._mode = "enrollment"
        return authority

    @classmethod
    def for_crash_recovery(
        cls,
        *,
        product: WindowsLocalWheelProductSessionOwner,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
    ) -> CodingWindowsWorkerCleanupEvidenceAuthority:
        """Bind a dead Session only from its persisted Product recovery join."""

        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
            or type(receipt) is not ProductWorkerActivationReceiptV1
        ):
            raise ValueError("Windows C5 crash recovery requires an exact Product")
        return cls._from_crash_recovery(
            product=product,
            receipt=receipt,
            attempt_id=attempt_id,
            review_runtime=review_coding_windows_product_worker_orphan_runtime,
        )

    @property
    def host_identity(self) -> str:
        return "coding-windows-store:" + self._product.epoch_runtime.registry.store_id

    @property
    def boot_identity(self) -> str:
        return "coding-windows-runtime:" + self._receipt.policy.product_runtime_id

    def current_tree_witness(
        self, *, attempt_id: str
    ) -> CodingWindowsWorkerLiveCleanupReviewV1:
        if attempt_id != self._attempt_id:
            raise ValueError("Windows C5 cleanup attempt changed")
        runtime, native, activation = capture_windows_product_worker_cleanup(
            self._product,
            attempt_id=attempt_id,
            review_runtime=_review_under_gc_guard,
            inspect_native=inspect_coding_windows_product_worker_provisioning_attempts,
            activation_journal=partial(
                CodingWindowsWorkerActivationStateJournal, self._product
            ),
        )
        return CodingWindowsWorkerLiveCleanupReviewV1(
            runtime=runtime, native=native, activation=activation
        )

    def verify_changed_boot_absence(self, **_arguments: object) -> bool:
        return False

    def verify_registered_lease_expired(self, **_arguments: object) -> bool:
        return False


__all__ = [
    "CodingWindowsWorkerCleanupEvidenceAuthority",
    "CodingWindowsWorkerLiveCleanupReviewV1",
]
