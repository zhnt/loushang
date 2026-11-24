"""Durable Linux Product Worker history checkpoint, without pruning authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.package_product._linux_worker_history import (
    publish_product_worker_history_checkpoint,
    read_product_worker_history_checkpoints,
    repair_product_worker_history_checkpoint_append,
    rollback_product_worker_history_checkpoint_tail,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._checkpoint import _CheckpointMethods
from loushang.harness.worker.history._checkpoint_commands import (
    CheckpointCommands,
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

from .product_worker_history_checkpoint_anchor import CodingWorkerCheckpointAnchorV1
from .product_worker_history_retention import _history_proof_bindings
from .product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS as CODING_WORKER_HISTORY_STREAM_STEMS,
)
from .product_worker_history_stream_snapshot import CodingWorkerHistoryStreamSnapshotV1

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


class CodingWorkerHistoryCheckpointError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerHistoryCheckpointV1(_CheckpointMethods):
    stream_snapshots: tuple[CodingWorkerHistoryStreamSnapshotV1, ...]

    _snapshot_type = CodingWorkerHistoryStreamSnapshotV1

    @staticmethod
    def _valid_backup_topology_revision(value: str) -> bool:
        return value.startswith("coding-product-backup-types:")


_CHECKPOINT_HISTORY = CheckpointHistory(
    CodingWorkerHistoryCheckpointV1,
    CodingWorkerCheckpointAnchorV1,
    CodingWorkerHistoryCheckpointError,
)


def read_coding_product_worker_history_checkpoints_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerHistoryCheckpointV1, ...]:
    """Strictly replay Product checkpoints; this grants no pruning authority."""
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker checkpoint requires its Product")
    return read_product_worker_history_checkpoints(
        product, commands=lambda: _checkpoint_commands()
    )


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
    return _write_checkpoint(product, attempt_id=attempt_id, repair=False)


def repair_coding_product_worker_history_checkpoint_append(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerHistoryCheckpointV1:
    """Commit one complete interrupted append only if its Product inputs still match."""
    return _write_checkpoint(product, attempt_id=attempt_id, repair=True)


def _write_checkpoint(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str, repair: bool
) -> CodingWorkerHistoryCheckpointV1:
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or (_ATTEMPT.fullmatch(attempt_id) is None)
    ):
        action_label = "checkpoint repair" if repair else "checkpoint"
        raise ValueError(f"Coding Worker {action_label} requires one exact attempt")
    write = (
        repair_product_worker_history_checkpoint_append
        if repair
        else publish_product_worker_history_checkpoint
    )
    return cast(
        "CodingWorkerHistoryCheckpointV1",
        write(
            _history_proof_bindings(),
            product,
            attempt_id=attempt_id,
            closure_error=lambda: CodingWorkerHistoryCheckpointError(
                "coding_worker_checkpoint_closure_unproven"
            ),
        ),
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
    return cast(
        "tuple[CodingWorkerHistoryCheckpointV1, ...]",
        rollback_product_worker_history_checkpoint_tail(
            _history_proof_bindings(), product
        ),
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


def _checkpoint_commands() -> CheckpointCommands[
    CodingWorkerHistoryCheckpointV1, CodingWorkerCheckpointAnchorV1
]:
    from .product_worker_history_stream_snapshot import _snapshot_source

    return CheckpointCommands(
        _CHECKPOINT_HISTORY,
        _snapshot_source(),
        _MAX_RECORD_BYTES,
        _MAX_SEGMENT_BYTES,
        _MAX_ACTIVE_RECORDS,
    )
