"""Read-only Product evidence for a normally closed Windows C5 attempt.

The C5 boot-identity slot binds this authority to the original Product runtime
incarnation. It does not claim an OS boot observation or authorize changed-boot
or orphan-lease recovery. Those paths require separate offline authority.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.worker._native_profile_bridge import (
    _WindowsNativeContainmentSettlementWitness,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
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

_AUTHORITY_ID = "coding.windows-worker.cleanup-evidence.v1"
_AUTHORITY_FINGERPRINT = sha256(
    b"loushang.coding.windows-worker.cleanup-evidence/v1"
).hexdigest()


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerLiveCleanupReviewV1:
    """One live-runtime read; no field grants cleanup or Package GC."""

    runtime: CodingWindowsWorkerOrphanRuntimeReviewV1
    native: WindowsWorkerProvisioningAttemptV1 | None
    activation: CodingProductWorkerRetainedAttemptV1 | None


class CodingWindowsWorkerCleanupEvidenceAuthority:
    """Reopen an exact native, Supervisor, receipt, and C5 settlement join."""

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
        self._product = receipt_owner.product_owner
        self._receipt = receipt
        self._request = request

    @property
    def host_identity(self) -> str:
        return "coding-windows-store:" + self._product.epoch_runtime.registry.store_id

    @property
    def boot_identity(self) -> str:
        return "coding-windows-runtime:" + self._receipt.policy.product_runtime_id

    def current_tree_witness(
        self, *, attempt_id: str
    ) -> CodingWindowsWorkerLiveCleanupReviewV1:
        if attempt_id != self._request.identity.attempt_id:
            raise ValueError("Windows C5 cleanup attempt changed")
        registry = self._product.epoch_runtime.registry
        orphans = registry.review_orphans(store_id=registry.store_id)
        with self._product.gc_gate.guard():
            self._product.assert_root_gc_authority_current()
            runtime = _review_under_gc_guard(
                self._product, attempt_id=attempt_id, orphans=orphans
            )
            native = tuple(
                item
                for item in inspect_coding_windows_product_worker_provisioning_attempts(
                    self._product
                )
                if item.attempt_id == attempt_id
            )
            retained = tuple(
                item
                for item in CodingWindowsWorkerActivationStateJournal(
                    self._product
                ).retained_attempts_read_only()
                if item.attempt_id == attempt_id
            )
            self._product.assert_root_gc_authority_current()
        return CodingWindowsWorkerLiveCleanupReviewV1(
            runtime=runtime,
            native=native[0] if len(native) == 1 else None,
            activation=retained[0] if len(retained) == 1 else None,
        )

    def _current_review_matches(
        self, *, witness: object, attempt_id: str
    ) -> CodingWindowsWorkerLiveCleanupReviewV1 | None:
        if type(witness) is not CodingWindowsWorkerLiveCleanupReviewV1:
            return None
        try:
            fresh = self.current_tree_witness(attempt_id=attempt_id)
        except (OSError, RuntimeError, ValueError):
            return None
        if fresh != witness:
            return None
        return fresh if self._review_matches(fresh) else None

    def _review_matches(self, fresh: CodingWindowsWorkerLiveCleanupReviewV1) -> bool:
        runtime = fresh.runtime
        attempt = runtime.attempt
        record = runtime.receipt_record
        native = fresh.native
        activation = fresh.activation
        if (
            attempt is None
            or record is None
            or native is None
            or activation is None
            or runtime.orphan_leases
            or runtime.native_job_absent is not True
            or not attempt.clean_exit_settled
            or attempt.attempt_id != self._request.identity.attempt_id
            or attempt.launch_request_fingerprint != self._request.fingerprint
            or attempt.launch_identity_fingerprint != self._request.identity.fingerprint
            or attempt.launch_receipt_fingerprint != self._receipt.fingerprint
            or record.receipt != self._receipt
            or native.phase != "settled"
            or native.last_witness_state != "SETTLED"
            or native.settlement_fingerprint is None
            or native.phase_history != attempt.native_phase_history
            or native.witness_present_history != attempt.native_witness_present_history
            or native.identity.get("receiptFingerprint") != self._receipt.fingerprint
            or native.identity.get("workerRequestFingerprint")
            != self._request.fingerprint
            or native.identity.get("ownerGeneration")
            != self._request.identity.owner_generation
            or native.identity.get("jobObjectName") != attempt.native_job_name
            or activation.phase != "retired"
            or activation.cleanup_contract_version != 2
            or activation.receipt_fingerprint != self._receipt.fingerprint
            or activation.policy_fingerprint != self._receipt.policy.fingerprint
            or activation.owner_generation != self._request.identity.owner_generation
            or activation.host_identity != self.host_identity
            or activation.boot_identity != self.boot_identity
        ):
            return False
        return True

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
        if not self._identity_matches(
            receipt_fingerprint=receipt_fingerprint,
            attempt_id=attempt_id,
            owner_generation=owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
            evidence_authority_id=evidence_authority_id,
            evidence_authority_fingerprint=evidence_authority_fingerprint,
        ):
            return False
        return (
            self._current_review_matches(witness=witness, attempt_id=attempt_id)
            is not None
        )

    def verify_native_containment_settlement(
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
        if (
            not self._identity_matches(
                receipt_fingerprint=receipt_fingerprint,
                attempt_id=attempt_id,
                owner_generation=owner_generation,
                host_identity=host_identity,
                boot_identity=boot_identity,
                evidence_authority_id=evidence_authority_id,
                evidence_authority_fingerprint=evidence_authority_fingerprint,
            )
            or type(witness) is not _WindowsNativeContainmentSettlementWitness
        ):
            return False
        try:
            fresh = self.current_tree_witness(attempt_id=attempt_id)
        except (OSError, RuntimeError, ValueError):
            return False
        native = fresh.native
        return bool(
            native is not None
            and self._review_matches(fresh)
            and witness.receipt_fingerprint == self._receipt.fingerprint
            and witness.worker_request_fingerprint == self._request.fingerprint
            and witness.attempt_id == attempt_id
            and witness.owner_generation == owner_generation
            and witness.journal_fingerprint == native.settlement_fingerprint
        )

    def _identity_matches(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        return (
            receipt_fingerprint == self._receipt.fingerprint
            and attempt_id == self._request.identity.attempt_id
            and owner_generation == self._request.identity.owner_generation
            and host_identity == self.host_identity
            and boot_identity == self.boot_identity
            and evidence_authority_id == self.authority_id
            and evidence_authority_fingerprint == self.authority_fingerprint
        )

    def verify_changed_boot_absence(self, **_arguments: object) -> bool:
        return False

    def verify_registered_lease_expired(self, **_arguments: object) -> bool:
        return False


__all__ = [
    "CodingWindowsWorkerCleanupEvidenceAuthority",
    "CodingWindowsWorkerLiveCleanupReviewV1",
]
