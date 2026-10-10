"""Settle one Linux Worker C5 attempt after exact offline crash recovery."""

from __future__ import annotations

import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from hashlib import sha256

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.product_activation import (
    ActivationWitness,
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
    WorkerCleanupSettlementV1,
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
from .package_product_worker_cleanup_evidence import (
    CodingPosixWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_history_retention import (
    CodingWorkerHistoryRetentionReviewV1,
    _review_coding_product_worker_history_under_guard,
)
from .package_product_worker_payload import (
    _read_complete_repair_intent,
    _stage_exists,
)
from .package_product_worker_receipt import (
    read_coding_product_worker_receipt_record,
)
from .package_product_worker_start_gate_recovery import (
    _review_offline,
)

_STALE_WITNESS: ActivationWitness = ("0" * 64, "0" * 64, "stale", 0, 0)


class CodingWorkerCrashC5SettlementError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _ClosedLinuxCrashRecoveryAuthority:
    """Serialize C5 changes while refusing any fresh Worker admission."""

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        self._product = product

    @contextmanager
    def serialized_admission(self) -> Iterator[None]:
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            yield
            self._product.assert_root_gc_authority_current()

    def current_witness(
        self, _receipt: ProductWorkerActivationReceiptV1
    ) -> ActivationWitness:
        return _STALE_WITNESS

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        raise ValueError("Linux crash recovery cannot change Worker admission")


class _UnderGuardCleanupEvidenceAuthority(CodingPosixWorkerCleanupEvidenceAuthority):
    """Read fresh C5 evidence inside the caller's runtime and GC locks."""

    def __init__(
        self,
        product: PosixLocalWheelProductSessionOwner,
        *,
        active_runtime_lease_ids: tuple[str, ...],
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
    ) -> None:
        super().__init__(product)
        self._active_runtime_lease_ids = active_runtime_lease_ids
        self._gc_snapshot = gc_snapshot

    def current_tree_witness(
        self, *, attempt_id: str
    ) -> CodingWorkerHistoryRetentionReviewV1:
        return _review_coding_product_worker_history_under_guard(
            self._product,
            attempt_id=attempt_id,
            active_runtime_lease_ids=self._active_runtime_lease_ids,
            gc_snapshot=self._gc_snapshot,
        )


def settle_coding_product_worker_crash_c5(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Retire and settle C5 under one offline runtime and GC transaction."""

    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise CodingWorkerCrashC5SettlementError(
            "coding_worker_crash_c5_product_unsupported"
        )
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id) as quiet:
        if quiet.active_runtime_lease_ids:
            raise CodingWorkerCrashC5SettlementError(
                "coding_worker_crash_c5_runtime_active"
            )
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            result = _settle_crash_c5_under_guard(
                product,
                attempt_id=attempt_id,
                active_runtime_lease_ids=quiet.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )
            product.assert_root_gc_authority_current()
            return result


def _settle_crash_c5_under_guard(
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    active_runtime_lease_ids: tuple[str, ...],
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
) -> CodingProductWorkerRetainedAttemptV1:
    review = _review_offline(product, attempt_id=attempt_id)
    gate = review.gate_record
    supervisor = review.attempt_record
    if (
        gate is None
        or gate.phase != "bound"
        or gate.identity is None
        or supervisor is None
        or not supervisor.process_settled
        or supervisor.phase != "process_settled"
        or not review.native_closure_current
        or review.group_status != "absent"
    ):
        raise CodingWorkerCrashC5SettlementError(
            "coding_worker_crash_c5_recovery_incomplete"
        )
    record = read_coding_product_worker_receipt_record(
        product, receipt_fingerprint=gate.receipt_fingerprint
    )
    if (
        record is None
        or record.receipt.policy.product_id != "coding"
        or record.receipt.policy.fingerprint != gate.policy_fingerprint
        or record.receipt.policy.product_scope_id != gate.scope_id
        or supervisor.identity_fingerprint != gate.worker_identity_fingerprint
    ):
        raise CodingWorkerCrashC5SettlementError(
            "coding_worker_crash_c5_receipt_changed"
        )
    with product.pinned_state_root_gc_read() as root_fd:
        if _stage_exists(root_fd, attempt_id):
            raise CodingWorkerCrashC5SettlementError(
                "coding_worker_crash_c5_payload_live"
            )
        completed = _read_complete_repair_intent(root_fd, attempt_id)
    if (
        completed is None
        or completed[0].receipt_fingerprint != record.receipt.fingerprint
        or completed[1]
        != sha256(canonical_json_bytes(supervisor.to_dict())).hexdigest()
    ):
        raise CodingWorkerCrashC5SettlementError(
            "coding_worker_crash_c5_payload_unproven"
        )

    journal = CodingProductWorkerActivationStateJournal(
        product.state_root / "worker-activation-state.jsonl",
        scope_id=product.policy.project_scope_id,
        store_id=product.epoch_runtime.registry.store_id,
    )
    retained = tuple(
        item
        for item in journal.retained_attempts_read_only()
        if item.attempt_id == attempt_id
    )
    if len(retained) != 1:
        raise CodingWorkerCrashC5SettlementError(
            "coding_worker_crash_c5_attempt_unavailable"
        )
    [c5] = retained
    receipt = record.receipt
    evidence = _UnderGuardCleanupEvidenceAuthority(
        product,
        active_runtime_lease_ids=active_runtime_lease_ids,
        gc_snapshot=gc_snapshot,
    )
    if (
        c5.receipt_fingerprint != receipt.fingerprint
        or c5.policy_fingerprint != receipt.policy.fingerprint
        or c5.owner_generation != receipt.policy.owner_selection_generation
        or c5.cleanup_contract_version != 1
        or c5.host_identity != evidence.host_identity
        or c5.boot_identity != evidence.boot_identity
        or not c5.current
    ):
        raise CodingWorkerCrashC5SettlementError(
            "coding_worker_crash_c5_attempt_changed"
        )
    state = journal.load()
    attempts = None if state is None else state.get("attempts")
    if not isinstance(attempts, Mapping):
        raise CodingWorkerCrashC5SettlementError(
            "coding_worker_crash_c5_state_unavailable"
        )
    exact = tuple(
        item
        for item in attempts.values()
        if isinstance(item, Mapping) and item.get("attemptId") == attempt_id
    )
    if (
        len(exact) != 1
        or exact[0].get("evidenceAuthorityId") != evidence.authority_id
        or exact[0].get("evidenceAuthorityFingerprint")
        != evidence.authority_fingerprint
        or exact[0].get("phase") != c5.phase
    ):
        raise CodingWorkerCrashC5SettlementError(
            "coding_worker_crash_c5_evidence_changed"
        )
    if c5.phase == "settled":
        if exact[0].get("cleanupSettlement") is None:
            raise CodingWorkerCrashC5SettlementError(
                "coding_worker_crash_c5_settlement_unverified"
            )
        return c5

    coordinator = ProductWorkerActivationCoordinator(
        authority=_ClosedLinuxCrashRecoveryAuthority(product),
        evidence_authority=evidence,
        trusted_evidence_authority_id=evidence.authority_id,
        trusted_evidence_authority_fingerprint=evidence.authority_fingerprint,
        state_store=open_coding_product_worker_activation_state_store(product),
    )
    generation = receipt.policy.owner_selection_generation
    coordinator.retire_exact(
        receipt=receipt, attempt_id=attempt_id, owner_generation=generation
    )
    coordinator.record_protocol_terminal(
        receipt=receipt, attempt_id=attempt_id, owner_generation=generation
    )
    witness = evidence.current_tree_witness(attempt_id=attempt_id)
    coordinator.record_cleanup_settlement(
        WorkerCleanupSettlementV1(
            receipt_fingerprint=receipt.fingerprint,
            attempt_id=attempt_id,
            owner_generation=generation,
            host_identity=evidence.host_identity,
            boot_identity=evidence.boot_identity,
            protocol_terminal=True,
            domain_retired=True,
            tree_settled=True,
        ),
        witness=witness,
    )
    [settled] = (
        item
        for item in journal.retained_attempts_read_only()
        if item.attempt_id == attempt_id
    )
    if settled.phase != "settled":
        raise CodingWorkerCrashC5SettlementError(
            "coding_worker_crash_c5_settlement_unverified"
        )
    return settled


__all__ = [
    "CodingWorkerCrashC5SettlementError",
    "settle_coding_product_worker_crash_c5",
]
