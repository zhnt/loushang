"""Read-only Product evidence for one Linux Worker history-retention decision.

This inventory grants no journal deletion authority. The current Product
backup type authority attests that Worker backups are unsupported; GC still
lacks an attempt-level closure decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loushang.harness.package_product._linux_worker_history import (
    _PAYLOAD_REPAIR as _PAYLOAD_REPAIR,
)
from loushang.harness.package_product._linux_worker_history import (
    _REGISTERED_REPAIR_STAGING as _REGISTERED_REPAIR_STAGING,
)
from loushang.harness.package_product._linux_worker_history import (
    HistoryProofBindings,
    review_history,
    review_history_under_guard,
)
from loushang.harness.package_product._linux_worker_history import (
    known_worker_state_name as _known_worker_state_name,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.worker.history._retention import (
    RetentionReviewMethods,
    matching_attempt_gc_refs,
    receipt_gate_reference_issue,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1

from .product_backup_types import (
    CodingWorkerBackupReferenceObservationV1,
    observe_coding_worker_backup_references_under_gc_guard,
)
from .product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
    CodingProductWorkerRetainedAttemptV1,
)
from .product_worker_history_stream_snapshot import CodingWorkerHistoryStreamSnapshotV1
from .product_worker_opt_in import CodingWorkerOptInDecisionV1, CodingWorkerOptInJournal
from .product_worker_opt_in_owner import CodingWorkerProductOptInOwner
from .product_worker_payload import open_coding_product_worker_supervisor_journal
from .product_worker_receipt import CodingWorkerReceiptRecordV1
from .product_worker_start_gate_journal import (
    CodingWorkerStartGateJournal,
    CodingWorkerStartGateRecordV1,
)
from .product_worker_start_gate_recovery import GatedGroupStatus


@dataclass(frozen=True, slots=True)
class CodingWorkerAttemptReferenceV1:
    """One retained Linux gate intent joined to its exact Product receipt.

    The start-gate journal supplies a durable reference for the ordinary
    pending Host and the explicit operator query. C5 attempt state remains a
    separate authority. This projection grants no closure or pruning power.
    """

    attempt_id: str
    plugin_id: str
    receipt_fingerprint: str
    selected_package_revision_digest: str
    selected_locator_revision: str
    native_platform: Literal["linux"]
    gate_revision: int
    gate_phase: Literal["intent", "bound"]


_matching_gc_revision_refs = matching_attempt_gc_refs


def _receipt_gate_reference_issue(
    gate: CodingWorkerStartGateRecordV1,
    receipt: CodingWorkerReceiptRecordV1 | None,
    supervisor: WorkerAttemptRecordV1 | None,
    group_status: GatedGroupStatus,
    activation: CodingProductWorkerRetainedAttemptV1 | None = None,
) -> str | None:
    """Require every attempt naming a receipt to have settled native custody."""

    return receipt_gate_reference_issue(
        gate, receipt, supervisor, group_status, activation, product_id="coding"
    )


@dataclass(frozen=True, slots=True)
class CodingWorkerHistoryRetentionReviewV1(
    RetentionReviewMethods[CodingWorkerAttemptReferenceV1]
):
    attempt_id: str
    gate_record: CodingWorkerStartGateRecordV1 | None
    attempt_record: WorkerAttemptRecordV1 | None
    receipt_record: CodingWorkerReceiptRecordV1 | None
    current_opt_in: CodingWorkerOptInDecisionV1 | None
    historical_opt_in_verified: bool
    group_status: GatedGroupStatus
    opt_in_history_revision: int
    retained_opt_in_operation_ids: tuple[str, ...]
    opt_in_generation_high_water: tuple[tuple[str, int, int, str, str], ...]
    start_gate_history_revision: int
    supervisor_history_revision: int
    receipt_history_revision: int
    retained_start_gate_attempt_ids: tuple[str, ...]
    retained_supervisor_attempt_ids: tuple[str, ...]
    retained_receipt_fingerprints: tuple[str, ...]
    history_stream_snapshots: tuple[CodingWorkerHistoryStreamSnapshotV1, ...]
    history_stream_revisions_match: bool
    supervisor_epoch_high_water: tuple[tuple[str, int], ...]
    unbound_supervisor_attempt_ids: tuple[str, ...]
    activation_state_revision: int | None
    active_activation_references: tuple[tuple[str, str], ...]
    retained_activation_references: tuple[CodingProductWorkerRetainedAttemptV1, ...]
    global_activation_reference_ids_match: bool
    unverified_activation_references: tuple[tuple[str, str], ...]
    global_unverified_activation_references: tuple[tuple[str, str], ...]
    global_unverified_opt_in_references: tuple[tuple[str, str], ...]
    receipt_gate_references: tuple[str, ...]
    unsettled_receipt_gate_references: tuple[str, ...]
    unverified_receipt_gate_references: tuple[tuple[str, str], ...]
    global_unverified_receipt_gate_references: tuple[tuple[str, str], ...]
    receipt_references_verified: bool
    payload_stage_names: tuple[str, ...]
    retained_payload_repair_reference_names: tuple[str, ...]
    registered_repair_reference_verified: bool
    unrecognized_worker_state_names: tuple[str, ...]
    active_runtime_lease_ids: tuple[str, ...]
    active_gc_reservation_count: int
    gc_reservation_revision: int
    gc_matching_revision_refs: tuple[PluginPackageRevisionRefV1, ...]
    worker_backup_references: CodingWorkerBackupReferenceObservationV1 | None

    _product_id = "coding"
    _reference_type = CodingWorkerAttemptReferenceV1


def review_coding_product_worker_history_retention(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerHistoryRetentionReviewV1:
    """Join fresh Product facts while runtime and GC owner locks are held."""
    return review_history(_history_proof_bindings(), product, attempt_id=attempt_id)


def _review_coding_product_worker_history_under_guard(
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    active_runtime_lease_ids: tuple[str, ...],
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
) -> CodingWorkerHistoryRetentionReviewV1:
    """Read exact history while the caller owns runtime and GC locks."""

    return review_history_under_guard(
        _history_proof_bindings(),
        product,
        attempt_id=attempt_id,
        active_runtime_lease_ids=active_runtime_lease_ids,
        gc_snapshot=gc_snapshot,
    )


__all__ = [
    "CodingWorkerAttemptReferenceV1",
    "CodingWorkerHistoryRetentionReviewV1",
    "review_coding_product_worker_history_retention",
]


def _history_proof_bindings() -> HistoryProofBindings[
    CodingWorkerHistoryRetentionReviewV1
]:
    """Bind actual existing owners and pure Product data without reading history."""

    def receipts(product):
        from .product_worker_receipt import _receipt_history_for_product

        return _receipt_history_for_product(product)

    def snapshots():
        from .product_worker_history_stream_snapshot import _snapshot_source

        return _snapshot_source()

    def access(product):
        from loushang.coding.package.worker_history_access import _CodingHistoryAccess

        return _CodingHistoryAccess(product)

    def reader():
        from .product_worker_history_read_v2 import _HISTORY_READER

        return _HISTORY_READER

    def preparation():
        from .product_worker_history_stage_v2 import _PREPARATION_HISTORY

        return _PREPARATION_HISTORY

    def preparation_limits():
        from . import product_worker_history_stage_v2 as stage

        return dict(
            max_intent_bytes=stage._MAX_INTENT_BYTES,
            max_base_bytes=stage._MAX_BASE_BYTES,
            max_stream_bytes=stage._MAX_STREAM_BYTES,
            max_index_bytes=stage._MAX_INDEX_BYTES,
        )

    def checkpoints():
        from .product_worker_history_checkpoint import _checkpoint_commands

        return _checkpoint_commands()

    def registered():
        from .product_worker_registered_payload_repair import _repair_journal

        return _repair_journal()

    def payload():
        from .product_worker_payload import _STORAGE

        return _STORAGE

    def native_custody():
        from .product_worker_installed_native import _product_native_release_custody

        return _product_native_release_custody()

    def native_error():
        from .product_worker_start_gate_recovery import CodingWorkerNativeReleaseError

        return CodingWorkerNativeReleaseError

    def gated_error():
        from .product_worker_start_gate_recovery import CodingWorkerGatedRecoveryError

        return CodingWorkerGatedRecoveryError

    def gated_review():
        from .product_worker_start_gate_recovery import (
            CodingWorkerGatedRecoveryReviewV1,
        )

        return CodingWorkerGatedRecoveryReviewV1

    return HistoryProofBindings(
        product_id="coding",
        product_label="Coding",
        gates=lambda product: CodingWorkerStartGateJournal(product),
        supervisor=lambda product: open_coding_product_worker_supervisor_journal(
            product
        ),
        receipts=receipts,
        opt_in_type=lambda: CodingWorkerOptInJournal,
        admitted_opt_in=lambda product: CodingWorkerProductOptInOwner(product),
        activation_type=lambda: CodingProductWorkerActivationStateJournal,
        snapshots=snapshots,
        access=access,
        reader=reader,
        preparation=preparation,
        preparation_limits=preparation_limits,
        checkpoints=checkpoints,
        registered=registered,
        payload=payload,
        native_custody=native_custody,
        native_error=native_error,
        gated_error=gated_error,
        gated_review=gated_review,
        review=lambda: CodingWorkerHistoryRetentionReviewV1,
        reference=lambda: CodingWorkerAttemptReferenceV1,
        known_state_name=lambda name: _known_worker_state_name(name),
        payload_repair=_PAYLOAD_REPAIR,
        registered_staging=_REGISTERED_REPAIR_STAGING,
        backup_attestation=lambda product, *, attempt_id: (
            observe_coding_worker_backup_references_under_gc_guard(
                product, attempt_id=attempt_id
            )
        ),
    )
