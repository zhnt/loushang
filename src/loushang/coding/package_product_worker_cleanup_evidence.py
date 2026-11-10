"""Product-owned Linux cleanup evidence for a C5 Worker attempt.

This owner reopens the settled Supervisor, start gate, native group and Product
state under the retention review's locks. It also verifies an exact prior-boot
absence for the offline crash-recovery path. Registered-lease recovery remains
closed.
"""

from __future__ import annotations

from hashlib import sha256
from typing import cast

from loushang.harness.package_product._linux_worker_recovery import (
    CleanupEvidenceAuthority,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .package_product_worker_history_retention import (
    CodingWorkerHistoryRetentionReviewV1,
)
from .package_product_worker_registered_recovery import _recovery_bindings

_HOST_DOMAIN = "loushang.coding.worker.cleanup/v1"
_AUTHORITY_ID = "coding.posix-worker.cleanup-evidence.v1"
_AUTHORITY_FINGERPRINT = sha256(
    b"loushang.coding.posix-worker.cleanup-evidence/v1"
).hexdigest()


class CodingPosixWorkerCleanupEvidenceAuthority(
    CleanupEvidenceAuthority[CodingWorkerHistoryRetentionReviewV1]
):
    """Revalidate one original Linux attempt before C5 tree settlement."""

    authority_id = _AUTHORITY_ID
    authority_fingerprint = _AUTHORITY_FINGERPRINT

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        super().__init__(product, _recovery_bindings())

    @property
    def host_identity(self) -> str:
        return super().host_identity

    @property
    def boot_identity(self) -> str:
        return super().boot_identity

    def current_tree_witness(
        self, *, attempt_id: str
    ) -> CodingWorkerHistoryRetentionReviewV1:
        """Capture a review that the verifier must reopen and match exactly."""
        return cast(
            CodingWorkerHistoryRetentionReviewV1,
            super().current_tree_witness(attempt_id=attempt_id),
        )

    def verify_tree_settlement(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        witness: object,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        return super().verify_tree_settlement(
            receipt_fingerprint=receipt_fingerprint,
            attempt_id=attempt_id,
            owner_generation=owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
            witness=witness,
            evidence_authority_id=evidence_authority_id,
            evidence_authority_fingerprint=evidence_authority_fingerprint,
        )

    def verify_changed_boot_absence(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        current_boot_identity: str,
        witness: object,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        return super().verify_changed_boot_absence(
            receipt_fingerprint=receipt_fingerprint,
            attempt_id=attempt_id,
            owner_generation=owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
            current_boot_identity=current_boot_identity,
            witness=witness,
            evidence_authority_id=evidence_authority_id,
            evidence_authority_fingerprint=evidence_authority_fingerprint,
        )

    def verify_registered_lease_expired(self, **_arguments: object) -> bool:
        return super().verify_registered_lease_expired(**_arguments)


__all__ = ["CodingPosixWorkerCleanupEvidenceAuthority"]
