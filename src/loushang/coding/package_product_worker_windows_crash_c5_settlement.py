"""Settle a crashed Windows Worker C5 attempt after Product recovery closes it."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.product_activation import (
    ActivationWitness,
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
    WorkerCleanupSettlementV2,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_activation_state import (
    open_coding_windows_product_worker_activation_state_store,
)
from .package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from .package_product_worker_windows_cleanup_evidence import (
    CodingWindowsWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_windows_crash_cleanup_review import (
    _valid_crash_native_settlement_history,
)
from .package_product_worker_windows_orphan_review import (
    review_coding_windows_product_worker_orphan_runtime,
)

_STALE_WITNESS: ActivationWitness = ("0" * 64, "0" * 64, "stale", 0, 0)


class _ClosedWindowsCrashRecoveryAuthority:
    """Provide Product serialization while refusing fresh activation authority."""

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
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
        raise ValueError("Windows crash recovery cannot change Worker admission")


def settle_coding_windows_product_worker_crash_c5(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Recheck a repaired crash, then retire and settle its exact C5 record."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows crash C5 settlement requires its Coding Product")
    runtime = review_coding_windows_product_worker_orphan_runtime(
        product, attempt_id=attempt_id
    )
    attempt = runtime.attempt
    record = runtime.receipt_record
    if (
        attempt is None
        or record is None
        or runtime.orphan_leases
        or runtime.native_job_absent is not True
        or attempt.supervisor_phase != "process_settled"
        or attempt.supervisor_process_settled is not True
        or attempt.native_phase != "settled"
        or not _valid_crash_native_settlement_history(attempt)
        or attempt.payload_directory_identity is not None
        or attempt.observed_debts != ("payload_missing", "launch_intent_retained")
        or attempt.launch_receipt_fingerprint != record.receipt.fingerprint
    ):
        raise ValueError("Windows crash C5 Product recovery is incomplete")
    receipt = record.receipt
    journal = CodingWindowsWorkerActivationStateJournal(product)
    retained = tuple(
        item
        for item in journal.retained_attempts_read_only()
        if item.attempt_id == attempt_id
    )
    if len(retained) != 1:
        raise ValueError("Windows crash C5 attempt is missing or ambiguous")
    [c5] = retained
    if (
        c5.receipt_fingerprint != receipt.fingerprint
        or c5.policy_fingerprint != receipt.policy.fingerprint
        or c5.owner_generation != receipt.policy.owner_selection_generation
        or c5.cleanup_contract_version != 2
        or not c5.current
    ):
        raise ValueError("Windows crash C5 attempt cannot be recovered")
    evidence = CodingWindowsWorkerCleanupEvidenceAuthority.for_crash_recovery(
        product=product, receipt=receipt, attempt_id=attempt_id
    )
    if (
        c5.host_identity != evidence.host_identity
        or c5.boot_identity != evidence.boot_identity
    ):
        raise ValueError("Windows crash C5 owner identity changed")
    state = journal.load()
    attempts = None if state is None else state.get("attempts")
    if not isinstance(attempts, Mapping):
        raise ValueError("Windows crash C5 owner state is unavailable")
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
        raise ValueError("Windows crash C5 evidence authority changed")
    if c5.phase == "settled":
        if exact[0].get("cleanupSettlement") is None:
            raise ValueError("Windows crash C5 settlement record is missing")
        return c5
    coordinator = ProductWorkerActivationCoordinator(
        authority=_ClosedWindowsCrashRecoveryAuthority(product),
        evidence_authority=evidence,
        trusted_evidence_authority_id=evidence.authority_id,
        trusted_evidence_authority_fingerprint=evidence.authority_fingerprint,
        state_store=open_coding_windows_product_worker_activation_state_store(product),
    )
    generation = receipt.policy.owner_selection_generation
    coordinator.retire_exact(
        receipt=receipt, attempt_id=attempt_id, owner_generation=generation
    )
    coordinator.record_protocol_terminal(
        receipt=receipt, attempt_id=attempt_id, owner_generation=generation
    )
    tree = evidence.current_tree_witness(attempt_id=attempt_id)
    coordinator.record_cleanup_settlement(
        WorkerCleanupSettlementV2(
            receipt_fingerprint=receipt.fingerprint,
            attempt_id=attempt_id,
            owner_generation=generation,
            host_identity=evidence.host_identity,
            boot_identity=evidence.boot_identity,
            protocol_terminal=True,
            domain_retired=True,
            tree_settled=True,
            native_containment_settled=True,
        ),
        witness=tree,
        native_containment_witness=evidence.current_native_witness(),
    )
    [settled] = (
        item
        for item in journal.retained_attempts_read_only()
        if item.attempt_id == attempt_id
    )
    if settled.phase != "settled":
        raise ValueError("Windows crash C5 settlement did not persist")
    return settled


__all__ = ["settle_coding_windows_product_worker_crash_c5"]
