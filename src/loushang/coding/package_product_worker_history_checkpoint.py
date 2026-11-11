"""Durable Linux Product Worker history checkpoint, without pruning authority."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from loushang.coding._worker_history_access import _CodingHistoryAccess
from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._checkpoint import _CheckpointMethods
from loushang.harness.worker.history._checkpoint_commands import (
    CheckpointCommands,
    CheckpointStoreIdentity,
)
from loushang.harness.worker.history._checkpoint_history import (
    _MAX_ACTIVE_RECORDS as _MAX_ACTIVE_RECORDS,
)
from loushang.harness.worker.history._checkpoint_history import (
    _MAX_RECORD_BYTES as _MAX_RECORD_BYTES,
)
from loushang.harness.worker.history._checkpoint_history import (
    _MAX_SEGMENT_BYTES as _MAX_SEGMENT_BYTES,
)
from loushang.harness.worker.history._checkpoint_history import (
    _STEM as _STEM,
)
from loushang.harness.worker.history._checkpoint_history import (
    CheckpointHistory,
)
from loushang.harness.worker.history._checkpoint_history import (
    _is_empty_seal_successor as _is_empty_seal_successor,
)

from .package_product_worker_history_checkpoint_anchor import (
    CodingWorkerCheckpointAnchorV1,
)
from .package_product_worker_history_retention import (
    _review_coding_product_worker_history_under_guard,
)
from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)
from .package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS as CODING_WORKER_HISTORY_STREAM_STEMS,
)
from .package_product_worker_history_stream_snapshot import (
    CodingWorkerHistoryStreamSnapshotV1,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


class CodingWorkerHistoryCheckpointError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerHistoryCheckpointV1(_CheckpointMethods):
    journal_revision: int
    scope_id: str
    store_id: str
    attempt_id: str
    receipt_fingerprint: str
    previous_digest: str
    gc_reservation_revision: int
    backup_topology_revision: str
    stream_snapshots: tuple[CodingWorkerHistoryStreamSnapshotV1, ...]
    new_opt_in_operation_ids: tuple[str, ...]
    new_attempt_ids: tuple[str, ...]
    new_receipt_fingerprints: tuple[str, ...]
    opt_in_generation_high_water: tuple[tuple[str, int, int, str, str], ...]
    supervisor_epoch_high_water: tuple[tuple[str, int], ...]
    record_digest: str
    record_version: int = 1

    _snapshot_type = CodingWorkerHistoryStreamSnapshotV1

    @staticmethod
    def _valid_backup_topology_revision(value: str) -> bool:
        return value.startswith("coding-product-backup-types:")


_CHECKPOINT_HISTORY = CheckpointHistory(
    CodingWorkerHistoryCheckpointV1,
    CodingWorkerCheckpointAnchorV1,
    CodingWorkerHistoryCheckpointError,
)


def _read_records(
    rooted: RootedFile,
    *,
    scope_id: str,
    store_id: str,
    history: CodingWorkerSegmentedHistoryV1 | None = None,
) -> tuple[tuple[CodingWorkerHistoryCheckpointV1, ...], CodingWorkerSegmentedHistoryV1]:
    return _CHECKPOINT_HISTORY.read_records(
        rooted,
        scope_id=scope_id,
        store_id=store_id,
        history=history,
        max_record_bytes=_MAX_RECORD_BYTES,
        max_segment_bytes=_MAX_SEGMENT_BYTES,
        max_active_records=_MAX_ACTIVE_RECORDS,
    )


def _read_records_or_repair_empty_bootstrap(
    rooted: RootedFile, *, scope_id: str, store_id: str
) -> tuple[tuple[CodingWorkerHistoryCheckpointV1, ...], CodingWorkerSegmentedHistoryV1]:
    return _checkpoint_commands().read_or_repair_empty_bootstrap(
        rooted, scope_id=scope_id, store_id=store_id
    )


def _anchor_for_records(
    rooted: RootedFile,
    *,
    scope_id: str,
    store_id: str,
    records: tuple[CodingWorkerHistoryCheckpointV1, ...],
    settle_lag: bool,
) -> CodingWorkerCheckpointAnchorV1 | None:
    return _CHECKPOINT_HISTORY.anchor_for_records(
        rooted,
        scope_id=scope_id,
        store_id=store_id,
        records=records,
        settle_lag=settle_lag,
    )


@contextmanager
def _bound_checkpoint(
    product: PosixLocalWheelProductSessionOwner,
) -> Iterator[RootedFile]:
    with _checkpoint_commands().bound(_CodingHistoryAccess(product)) as rooted:
        yield rooted


def read_coding_product_worker_history_checkpoints_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerHistoryCheckpointV1, ...]:
    """Strictly replay Product checkpoints; this grants no pruning authority."""
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker checkpoint requires its Product")
    with _bound_checkpoint(product) as rooted:
        return _checkpoint_commands().read(rooted, access=_CodingHistoryAccess(product))


def read_coding_worker_checkpoint_writer_fence(
    rooted: RootedFile, *, scope_id: str, store_id: str
) -> tuple[CodingWorkerHistoryCheckpointV1, ...]:
    "Read the anchored tip while the Product GC write gate excludes publishers.\n\n    The caller owns a pinned Product state root and the GC write gate. This\n    check never repairs an anchor or grants history-retirement authority.\n"

    return _CHECKPOINT_HISTORY.read_writer_fence(
        rooted,
        scope_id=scope_id,
        store_id=store_id,
        max_record_bytes=_MAX_RECORD_BYTES,
        max_segment_bytes=_MAX_SEGMENT_BYTES,
        max_active_records=_MAX_ACTIVE_RECORDS,
    )


def publish_coding_product_worker_history_checkpoint(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerHistoryCheckpointV1:
    """Publish a closed Product snapshot under runtime and GC writer custody."""
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or (_ATTEMPT.fullmatch(attempt_id) is None)
    ):
        raise ValueError("Coding Worker checkpoint requires one exact attempt")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        with product.gc_gate.guard(require_write=True):
            review = _review_coding_product_worker_history_under_guard(
                product,
                attempt_id=attempt_id,
                active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )
            if (
                review.missing_proofs
                or review.receipt_record is None
                or review.worker_backup_references is None
            ):
                raise CodingWorkerHistoryCheckpointError(
                    "coding_worker_checkpoint_closure_unproven"
                )
            with _bound_checkpoint(product) as rooted:
                return _checkpoint_commands().publish(
                    rooted,
                    access=_CodingHistoryAccess(product),
                    captured_store=_CapturedStoreIdentity(registry),
                    attempt_id=attempt_id,
                    review=review,
                )


def repair_coding_product_worker_history_checkpoint_append(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerHistoryCheckpointV1:
    """Commit one complete interrupted append only if its Product inputs still match."""
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or (_ATTEMPT.fullmatch(attempt_id) is None)
    ):
        raise ValueError("Coding Worker checkpoint repair requires one exact attempt")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        with product.gc_gate.guard(require_write=True):
            review = _review_coding_product_worker_history_under_guard(
                product,
                attempt_id=attempt_id,
                active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )
            if review.missing_proofs:
                raise CodingWorkerHistoryCheckpointError(
                    "coding_worker_checkpoint_closure_unproven"
                )
            with _bound_checkpoint(product) as rooted:
                return _checkpoint_commands().repair(
                    rooted,
                    access=_CodingHistoryAccess(product),
                    captured_store=_CapturedStoreIdentity(registry),
                    attempt_id=attempt_id,
                    review=review,
                )


def rollback_coding_product_worker_history_checkpoint_tail(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerHistoryCheckpointV1, ...]:
    """Discard only bytes after the last committed checkpoint head."""
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker checkpoint rollback requires its Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id):
        with product.gc_gate.guard(require_write=True):
            with _bound_checkpoint(product) as rooted:
                return _checkpoint_commands().rollback(
                    rooted,
                    access=_CodingHistoryAccess(product),
                    captured_store=_CapturedStoreIdentity(registry),
                )


__all__ = [
    "CodingWorkerHistoryCheckpointError",
    "CodingWorkerHistoryCheckpointV1",
    "publish_coding_product_worker_history_checkpoint",
    "read_coding_product_worker_history_checkpoints_under_gc_guard",
    "read_coding_worker_checkpoint_writer_fence",
    "repair_coding_product_worker_history_checkpoint_append",
    "rollback_coding_product_worker_history_checkpoint_tail",
]


@dataclass(frozen=True, slots=True)
class _CapturedStoreIdentity:
    registry: CheckpointStoreIdentity

    @property
    def store_id(self) -> str:
        return self.registry.store_id


def _checkpoint_commands() -> CheckpointCommands[
    CodingWorkerHistoryCheckpointV1, CodingWorkerCheckpointAnchorV1
]:
    from .package_product_worker_history_stream_snapshot import _snapshot_source

    return CheckpointCommands(
        _CHECKPOINT_HISTORY,
        _snapshot_source(),
        _MAX_RECORD_BYTES,
        _MAX_SEGMENT_BYTES,
        _MAX_ACTIVE_RECORDS,
    )
