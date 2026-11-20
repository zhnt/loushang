"""Canonical Windows Worker history checkpoint record.

The record binds source bytes, semantic bases, and Product reference closure.
Publication and an eventual owner switch must provide separate authority.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loushang.coding.harness.worker.windows_admission import is_windows_product
from loushang.harness.package_product._windows_worker_history import (
    publish_windows_product_worker_checkpoint,
    read_current_windows_product_worker_checkpoint_under_guard,
    read_windows_product_worker_checkpoint,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.worker.history._base_codec import _unchanged
from loushang.harness.worker.history._windows_checkpoint import (
    _WindowsHistoryCheckpointMethods,
)

from .legacy_windows_receipt import _receipt_io
from .product_worker_native_approval import CodingWorkerNativeApprovalDecisionV1
from .product_worker_windows_history_join import (
    CodingWindowsWorkerHistorySemanticJoinV1,
)
from .product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
)
from .product_worker_windows_native_approval_journal import (
    CodingWindowsWorkerNativeApprovalJournal,
)
from .product_worker_windows_package_references import (
    CodingWindowsWorkerPackageReferenceReviewV1,
    _review_coding_windows_worker_package_references_under_guard,
)

_MAX_BYTES = 8 * 1024 * 1024
_CHECKPOINT_NAME = "worker-history-checkpoint-v1.json"
_PREPARATION_NAME = "worker-history-preparation-v1.json"
_BASE_NAMES = (
    "optIn",
    "receipt",
    "supervisor",
    "c5",
    "launchIntent",
    "nativeProvisioning",
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistoryCheckpointV1(_WindowsHistoryCheckpointMethods):
    _join_type = CodingWindowsWorkerHistorySemanticJoinV1
    """An exact pre-cutover commitment to six source-bound semantic bases."""

    _source_snapshot_type = CodingWindowsWorkerHistorySourceSnapshotV1
    _package_reference_type = CodingWindowsWorkerPackageReferenceReviewV1
    _native_approval_type = CodingWorkerNativeApprovalDecisionV1
    _backup_topology_prefix = "coding-product-backup-types:"
    _base_names = _BASE_NAMES
    _wire_label = "Windows Worker history checkpoint"
    _wire_lists = ()
    _wire_invalid_bytes = _wire_invalid_fields = _wire_invalid_encoding = "is invalid"
    _wire_errors = (TypeError, UnicodeError, ValueError)

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_BYTES

    source_snapshot: CodingWindowsWorkerHistorySourceSnapshotV1
    preparation_digest: str
    package_reference_digest: str
    desired_history_digest: str
    backup_topology_revision: str
    gc_reservation_revision: int
    base_digests: tuple[tuple[str, str], ...]
    native_approval_record_digests: tuple[str, ...]
    native_approval_operation_ids: tuple[str, ...]
    native_approval_generation: int
    opt_in_operation_ids: tuple[str, ...]
    receipt_fingerprints: tuple[str, ...]
    attempt_ids: tuple[str, ...]
    native_provisioning_attempt_ids: tuple[str, ...]
    record_digest: str
    record_version: int = 1

    @classmethod
    def from_guarded_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
        package_review: CodingWindowsWorkerPackageReferenceReviewV1,
        native_approvals: tuple[CodingWorkerNativeApprovalDecisionV1, ...],
    ) -> CodingWindowsWorkerHistoryCheckpointV1:
        return cls._from_guarded_history(
            prepared, semantic, package_review, native_approvals
        )


CodingWindowsWorkerHistoryCheckpointV1._wire_schema = RecordSchema.for_dataclass(
    CodingWindowsWorkerHistoryCheckpointV1,
    _unchanged,
    RecordField(
        "source_snapshot",
        decoder=lambda value: CodingWindowsWorkerHistorySourceSnapshotV1.from_dict(
            value
        ),
    ),
    RecordField(
        "base_digests", decoder=lambda value: tuple(tuple(item) for item in value)
    ),
    RecordField("native_approval_record_digests", decoder=tuple),
    RecordField("native_approval_operation_ids", decoder=tuple),
    RecordField("opt_in_operation_ids", decoder=tuple),
    RecordField("receipt_fingerprints", decoder=tuple),
    RecordField("attempt_ids", decoder=tuple),
    RecordField("native_provisioning_attempt_ids", decoder=tuple),
)


def _current_checkpoint_under_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    quiescence: PackageWindowsRuntimeQuiescenceV1,
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
    allow_checkpoint_stage: bool,
    allow_base_stage: bool = False,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    return read_current_windows_product_worker_checkpoint_under_guard(
        product,
        record_type=CodingWindowsWorkerHistoryCheckpointV1,
        review_references=_review_coding_windows_worker_package_references_under_guard,
        approval_journal=CodingWindowsWorkerNativeApprovalJournal,
        io=_receipt_io,
        preparation_name=_PREPARATION_NAME,
        quiescence=quiescence,
        gc_snapshot=gc_snapshot,
        allow_checkpoint_stage=allow_checkpoint_stage,
        allow_base_stage=allow_base_stage,
    )


def read_coding_windows_worker_history_checkpoint(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    """Reprove published checkpoint bytes against the current guarded Product."""

    if not is_windows_product(product, "coding", os.name):
        raise ValueError("Windows Worker checkpoint requires its Product")
    return read_windows_product_worker_checkpoint(
        product,
        record_type=CodingWindowsWorkerHistoryCheckpointV1,
        review_checkpoint=_current_checkpoint_under_guard,
        io=_receipt_io,
        name=_CHECKPOINT_NAME,
    )


def publish_coding_windows_worker_history_checkpoint(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    """Publish exact pre-cutover bytes under Package quiescence and the GC gate.

    The old journals remain authoritative. A staged retry is completed only
    when its full record still equals the freshly joined Product state.
    """

    if not is_windows_product(product, "coding", os.name):
        raise ValueError("Windows Worker checkpoint requires its Product")
    return publish_windows_product_worker_checkpoint(
        product,
        record_type=CodingWindowsWorkerHistoryCheckpointV1,
        review_checkpoint=_current_checkpoint_under_guard,
        io=_receipt_io,
        name=_CHECKPOINT_NAME,
    )


__all__ = [
    "CodingWindowsWorkerHistoryCheckpointV1",
    "read_coding_windows_worker_history_checkpoint",
    "publish_coding_windows_worker_history_checkpoint",
]
