"""Product-owned Linux cleanup evidence for a C5 Worker attempt.

This owner reopens the settled Supervisor, start gate, native group and Product
state under the retention review's locks. It also verifies an exact prior-boot
absence for the offline crash-recovery path. Registered-lease recovery remains
closed.
"""

from __future__ import annotations

from hashlib import sha256

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.hosting.errors import HostingError
from loushang.hosting.machine_identity import linux_machine_key
from loushang.hosting.service_group import linux_current_boot_id

from .package_product_worker_history_retention import (
    CodingWorkerHistoryRetentionReviewV1,
    review_coding_product_worker_history_retention,
)
from .package_product_worker_payload import (
    CodingWorkerPayloadMaterializationError,
    _read_complete_repair_intent,
    _stage_exists,
)

_HOST_DOMAIN = "loushang.coding.worker.cleanup/v1"
_AUTHORITY_ID = "coding.posix-worker.cleanup-evidence.v1"
_AUTHORITY_FINGERPRINT = sha256(
    b"loushang.coding.posix-worker.cleanup-evidence/v1"
).hexdigest()


class CodingPosixWorkerCleanupEvidenceAuthority:
    """Revalidate one original Linux attempt before C5 tree settlement."""

    authority_id = _AUTHORITY_ID
    authority_fingerprint = _AUTHORITY_FINGERPRINT

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        if (
            type(product) is not PosixLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
        ):
            raise ValueError("Coding Worker cleanup requires its Linux Product owner")
        product.assert_root_gc_authority_current()
        self._product = product

    @property
    def host_identity(self) -> str:
        return linux_machine_key(domain=_HOST_DOMAIN)

    @property
    def boot_identity(self) -> str:
        return linux_current_boot_id()

    def current_tree_witness(
        self, *, attempt_id: str
    ) -> CodingWorkerHistoryRetentionReviewV1:
        """Capture a review that the verifier must reopen and match exactly."""

        return review_coding_product_worker_history_retention(
            self._product, attempt_id=attempt_id
        )

    def _complete_repair_verified(
        self,
        *,
        review: CodingWorkerHistoryRetentionReviewV1,
        receipt_fingerprint: str,
        attempt_id: str,
    ) -> bool:
        exact_name = f"worker-complete-repair-{attempt_id}.json"
        matching = tuple(
            name
            for name in review.retained_payload_repair_reference_names
            if name.endswith(f"-{attempt_id}.json")
        )
        if not matching:
            return True
        if matching != (exact_name,) or review.attempt_record is None:
            return False
        try:
            with self._product.pinned_state_root_gc_read() as root_fd:
                if _stage_exists(root_fd, attempt_id):
                    return False
                completed = _read_complete_repair_intent(root_fd, attempt_id)
        except (CodingWorkerPayloadMaterializationError, OSError, ValueError):
            return False
        return bool(
            completed is not None
            and completed[0].attempt_id == attempt_id
            and completed[0].receipt_fingerprint == receipt_fingerprint
            and completed[1]
            == sha256(canonical_json_bytes(review.attempt_record.to_dict())).hexdigest()
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
        return self._verify_tree_review(
            receipt_fingerprint=receipt_fingerprint,
            attempt_id=attempt_id,
            owner_generation=owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
            witness=witness,
            evidence_authority_id=evidence_authority_id,
            evidence_authority_fingerprint=evidence_authority_fingerprint,
            group_status="absent",
            current_boot_identity=None,
        )

    def _verify_tree_review(
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
        group_status: str,
        current_boot_identity: str | None,
    ) -> bool:
        if (
            type(witness) is not CodingWorkerHistoryRetentionReviewV1
            or type(receipt_fingerprint) is not str
            or type(attempt_id) is not str
            or type(owner_generation) is not int
            or owner_generation < 1
            or type(host_identity) is not str
            or type(boot_identity) is not str
            or evidence_authority_id != self.authority_id
            or evidence_authority_fingerprint != self.authority_fingerprint
        ):
            return False
        try:
            if host_identity != self.host_identity:
                return False
            if current_boot_identity is None:
                if boot_identity != self.boot_identity:
                    return False
            elif (
                current_boot_identity != self.boot_identity
                or current_boot_identity == boot_identity
            ):
                return False
            fresh = self.current_tree_witness(attempt_id=attempt_id)
        except (HostingError, OSError, RuntimeError, ValueError):
            return False
        if fresh != witness:
            return False
        gate = fresh.gate_record
        supervisor = fresh.attempt_record
        receipt = fresh.receipt_record
        backup = fresh.worker_backup_references
        c5_references = tuple(
            item
            for item in fresh.retained_activation_references
            if item.attempt_id == attempt_id
        )
        return bool(
            gate is not None
            and gate.phase == "bound"
            and gate.identity is not None
            and gate.identity.boot_id == boot_identity
            and gate.receipt_fingerprint == receipt_fingerprint
            and supervisor is not None
            and supervisor.process_settled
            and supervisor.identity_fingerprint == gate.worker_identity_fingerprint
            and receipt is not None
            and receipt.receipt.fingerprint == receipt_fingerprint
            and receipt.receipt.policy.product_id == "coding"
            and receipt.receipt.policy.product_scope_id == gate.scope_id
            and receipt.receipt.policy.fingerprint == gate.policy_fingerprint
            and fresh.group_status == group_status
            and (
                group_status != "prior_boot_absent"
                or (
                    fresh.history_stream_revisions_match
                    and fresh.historical_opt_in_verified
                )
            )
            and len(c5_references) == 1
            and c5_references[0].receipt_fingerprint == receipt_fingerprint
            and c5_references[0].policy_fingerprint == gate.policy_fingerprint
            and c5_references[0].owner_generation == owner_generation
            and c5_references[0].host_identity == host_identity
            and c5_references[0].boot_identity == boot_identity
            and c5_references[0].phase in {"retired", "cleanup_debt", "settled"}
            and f"worker-payload-{attempt_id}" not in fresh.payload_stage_names
            and self._complete_repair_verified(
                review=fresh,
                receipt_fingerprint=receipt_fingerprint,
                attempt_id=attempt_id,
            )
            and not fresh.unrecognized_worker_state_names
            and backup is not None
            and backup.attempt_id == attempt_id
            and backup.worker_backup_supported is False
            and not backup.references
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
        return self._verify_tree_review(
            receipt_fingerprint=receipt_fingerprint,
            attempt_id=attempt_id,
            owner_generation=owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
            witness=witness,
            evidence_authority_id=evidence_authority_id,
            evidence_authority_fingerprint=evidence_authority_fingerprint,
            group_status="prior_boot_absent",
            current_boot_identity=current_boot_identity,
        )

    def verify_registered_lease_expired(self, **_arguments: object) -> bool:
        return False


__all__ = ["CodingPosixWorkerCleanupEvidenceAuthority"]
