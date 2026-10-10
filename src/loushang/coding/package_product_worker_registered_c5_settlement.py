"""Settle one registered Linux Worker only after its no-effect repair closes."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_activation_state import (
    open_coding_product_worker_activation_state_store,
)
from .package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)
from .package_product_worker_crash_c5_settlement import (
    _ClosedLinuxCrashRecoveryAuthority,
    _UnderGuardCleanupEvidenceAuthority,
)
from .package_product_worker_history_retention import (
    CodingWorkerHistoryRetentionReviewV1,
)
from .package_product_worker_no_effect_closure import (
    is_coding_worker_no_effect_closure,
)
from .package_product_worker_payload import _stage_exists
from .package_product_worker_posix_gc_history import (
    CodingPosixWorkerGcHistoryAuthority,
)
from .package_product_worker_registered_payload_repair import (
    _expected_intent,
    _read_intent,
    registered_payload_repair_matches_no_effect_closure,
)
from .package_product_worker_registered_recovery import (
    CodingWorkerRegisteredOrphanReviewV1,
    review_coding_product_worker_registered_orphan,
)


class CodingWorkerRegisteredC5SettlementError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _require_registered_witness(
    product: PosixLocalWheelProductSessionOwner,
    *,
    review: CodingWorkerRegisteredOrphanReviewV1,
    witness: CodingWorkerHistoryRetentionReviewV1,
) -> None:
    """Accept the one expected transient unbound-gate shape and no other debt."""

    gate = review.gate_record
    receipt = review.receipt_record
    c5 = review.activation_attempt
    if (
        not review.payload_repair_candidate
        or gate is None
        or receipt is None
        or c5 is None
        or witness.gate_record != gate
        or witness.receipt_record != receipt
        or witness.attempt_record is not None
        or not witness.historical_opt_in_verified
        or not witness.history_stream_revisions_match
        or not witness.global_activation_reference_ids_match
        or witness.global_unverified_opt_in_references
        or witness.unbound_supervisor_attempt_ids
        or witness.unrecognized_worker_state_names
        or witness.payload_stage_names
        or witness.active_runtime_lease_ids
        or witness.active_activation_references
        != ((receipt.receipt.fingerprint, review.attempt_id),)
        or review.attempt_id not in witness.receipt_gate_references
        or witness.unsettled_receipt_gate_references != (review.attempt_id,)
        or witness.global_unverified_activation_references
        != ((review.attempt_id, "activation_reference_gate_unbound"),)
        or witness.global_unverified_receipt_gate_references
        != ((review.attempt_id, "receipt_reference_gate_unbound"),)
        or tuple(
            item
            for item in witness.retained_activation_references
            if item.attempt_id == review.attempt_id
        )
        != (c5,)
        or tuple(
            name
            for name in witness.retained_payload_repair_reference_names
            if name.endswith(f"-{review.attempt_id}.json")
        )
        != (f"worker-registered-repair-{review.attempt_id}.json",)
    ):
        raise CodingWorkerRegisteredC5SettlementError(
            "coding_worker_registered_c5_history_unverified"
        )
    backup = witness.worker_backup_references
    if (
        backup is None
        or backup.attempt_id != review.attempt_id
        or backup.worker_backup_supported is not False
        or backup.references
    ):
        raise CodingWorkerRegisteredC5SettlementError(
            "coding_worker_registered_c5_backup_unverified"
        )
    with product.pinned_state_root_gc_read() as root_fd:
        if _stage_exists(root_fd, review.attempt_id) or _read_intent(
            root_fd, review.attempt_id
        ) != _expected_intent(review):
            raise CodingWorkerRegisteredC5SettlementError(
                "coding_worker_registered_c5_payload_unverified"
            )


class _UnderGuardRegisteredCleanupEvidenceAuthority(
    _UnderGuardCleanupEvidenceAuthority
):
    def __init__(
        self,
        product: PosixLocalWheelProductSessionOwner,
        *,
        review: CodingWorkerRegisteredOrphanReviewV1,
        active_runtime_lease_ids: tuple[str, ...],
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
    ) -> None:
        super().__init__(
            product,
            active_runtime_lease_ids=active_runtime_lease_ids,
            gc_snapshot=gc_snapshot,
        )
        self._registered_review = review

    def verify_registered_lease_expired(
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
        review = self._registered_review
        c5 = review.activation_attempt
        if (
            type(witness) is not CodingWorkerHistoryRetentionReviewV1
            or c5 is None
            or not review.payload_repair_candidate
            or attempt_id != review.attempt_id
            or receipt_fingerprint != c5.receipt_fingerprint
            or owner_generation != c5.owner_generation
            or host_identity != c5.host_identity
            or host_identity != self.host_identity
            or boot_identity != c5.boot_identity
            or current_boot_identity != review.current_boot_identity
            or current_boot_identity != self.boot_identity
            or current_boot_identity == boot_identity
            or evidence_authority_id != self.authority_id
            or evidence_authority_fingerprint != self.authority_fingerprint
        ):
            return False
        try:
            fresh = self.current_tree_witness(attempt_id=attempt_id)
            if fresh != witness:
                return False
            _require_registered_witness(self._product, review=review, witness=fresh)
        except (OSError, RuntimeError, ValueError):
            return False
        return True


def _reopen_settled_registered_c5(
    product: PosixLocalWheelProductSessionOwner,
    review: CodingWorkerRegisteredOrphanReviewV1,
) -> CodingProductWorkerRetainedAttemptV1:
    c5 = review.activation_attempt
    gate = review.gate_record
    receipt = review.receipt_record
    registry = product.epoch_runtime.registry
    if (
        c5 is None
        or gate is None
        or receipt is None
        or review.supervisor_attempt is not None
        or review.repaired_orphan_lease is None
        or review.repaired_owner_revision is None
        or review.orphan_lease is not None
        or review.unrecognized_worker_state_names
        or c5.host_identity != review.host_identity
        or c5.boot_identity == review.current_boot_identity
        or not is_coding_worker_no_effect_closure(
            gate=gate, activation=c5, supervisor=None, receipt=receipt
        )
    ):
        raise CodingWorkerRegisteredC5SettlementError(
            "coding_worker_registered_c5_recovery_incomplete"
        )
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id) as quiet:
        if (
            quiet.active_runtime_lease_ids
            or quiet.owner_revision != review.repaired_owner_revision
        ):
            raise CodingWorkerRegisteredC5SettlementError(
                "coding_worker_registered_c5_runtime_changed"
            )
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            with product.pinned_state_root_gc_read() as root_fd:
                intent = _read_intent(root_fd, review.attempt_id)
                names = tuple(os.listdir(root_fd))
                if (
                    intent is None
                    or _stage_exists(root_fd, review.attempt_id)
                    or not registered_payload_repair_matches_no_effect_closure(
                        intent,
                        gate=gate,
                        receipt=receipt,
                        activation=c5,
                        supervisor=None,
                    )
                    or intent.lease_id != review.repaired_orphan_lease.lease_id
                ):
                    raise CodingWorkerRegisteredC5SettlementError(
                        "coding_worker_registered_c5_settlement_unverified"
                    )
            CodingPosixWorkerGcHistoryAuthority(product).require_settled(
                observed_names=names
            )
            journal = CodingProductWorkerActivationStateJournal(
                product.state_root / "worker-activation-state.jsonl",
                scope_id=product.policy.project_scope_id,
                store_id=registry.store_id,
            )
            if tuple(
                item
                for item in journal.retained_attempts_read_only()
                if item.attempt_id == review.attempt_id
            ) != (c5,):
                raise CodingWorkerRegisteredC5SettlementError(
                    "coding_worker_registered_c5_settlement_changed"
                )
            product.assert_root_gc_authority_current()
            return c5


def settle_coding_product_worker_registered_c5(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Reopen exact no-effect evidence under runtime and GC locks, then CAS C5."""

    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise CodingWorkerRegisteredC5SettlementError(
            "coding_worker_registered_c5_product_unsupported"
        )
    review = review_coding_product_worker_registered_orphan(
        product, attempt_id=attempt_id
    )
    if (
        review.activation_attempt is not None
        and review.activation_attempt.phase == "settled"
    ):
        return _reopen_settled_registered_c5(product, review)
    if not review.payload_repair_candidate or review.receipt_record is None:
        raise CodingWorkerRegisteredC5SettlementError(
            "coding_worker_registered_c5_recovery_incomplete"
        )
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id) as quiet:
        if (
            quiet.active_runtime_lease_ids
            or quiet.owner_revision != review.repaired_owner_revision
        ):
            raise CodingWorkerRegisteredC5SettlementError(
                "coding_worker_registered_c5_runtime_changed"
            )
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            evidence = _UnderGuardRegisteredCleanupEvidenceAuthority(
                product,
                review=review,
                active_runtime_lease_ids=quiet.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )
            witness = evidence.current_tree_witness(attempt_id=attempt_id)
            _require_registered_witness(product, review=review, witness=witness)
            journal = CodingProductWorkerActivationStateJournal(
                product.state_root / "worker-activation-state.jsonl",
                scope_id=product.policy.project_scope_id,
                store_id=registry.store_id,
            )
            state = journal.load()
            attempts = None if state is None else state.get("attempts")
            if not isinstance(attempts, Mapping):
                raise CodingWorkerRegisteredC5SettlementError(
                    "coding_worker_registered_c5_state_unavailable"
                )
            exact = tuple(
                item
                for item in attempts.values()
                if isinstance(item, Mapping) and item.get("attemptId") == attempt_id
            )
            if (
                len(exact) != 1
                or exact[0].get("phase") != "registered"
                or exact[0].get("evidenceAuthorityId") != evidence.authority_id
                or exact[0].get("evidenceAuthorityFingerprint")
                != evidence.authority_fingerprint
            ):
                raise CodingWorkerRegisteredC5SettlementError(
                    "coding_worker_registered_c5_attempt_changed"
                )
            coordinator = ProductWorkerActivationCoordinator(
                authority=_ClosedLinuxCrashRecoveryAuthority(product),
                evidence_authority=evidence,
                trusted_evidence_authority_id=evidence.authority_id,
                trusted_evidence_authority_fingerprint=evidence.authority_fingerprint,
                state_store=open_coding_product_worker_activation_state_store(product),
            )
            receipt = review.receipt_record.receipt
            coordinator.recover_registered_no_effect(
                receipt=receipt,
                attempt_id=attempt_id,
                owner_generation=receipt.policy.owner_selection_generation,
                current_boot_identity=evidence.boot_identity,
                witness=witness,
            )
            retained = tuple(
                item
                for item in journal.retained_attempts_read_only()
                if item.attempt_id == attempt_id
            )
            if (
                len(retained) != 1
                or retained[0].phase != "settled"
                or not retained[0].no_effect
            ):
                raise CodingWorkerRegisteredC5SettlementError(
                    "coding_worker_registered_c5_settlement_unverified"
                )
            product.assert_root_gc_authority_current()
            return retained[0]


__all__ = [
    "CodingWorkerRegisteredC5SettlementError",
    "settle_coding_product_worker_registered_c5",
]
