"""Canonical Windows Worker history preparation, without cutover authority.

The record binds a complete guarded source inventory to one semantic read. It
cannot replace the original journals, permit a fresh attempt, or delete bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_history import (
    prepare_windows_product_worker_history,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.worker.history._base_codec import _unchanged
from loushang.harness.worker.history._windows_checkpoint import (
    _WindowsHistoryPreparationMethods,
)

from .legacy_windows_receipt import _receipt_io
from .product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
    _capture_coding_windows_worker_semantics_under_gc_guard,
)

_MAX_RECORD_BYTES = 8 * 1024 * 1024
_PREPARATION_NAME = "worker-history-preparation-v1.json"


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistoryPreparationV1(_WindowsHistoryPreparationMethods):
    """A no-authority commitment to exact source and semantic identities."""

    _source_snapshot_type = CodingWindowsWorkerHistorySourceSnapshotV1
    _semantic_read_type = CodingWindowsWorkerHistorySemanticReadV1
    _wire_label = "Windows Worker history preparation"
    _wire_lists = ()
    _wire_invalid_bytes = _wire_invalid_fields = _wire_invalid_encoding = "is invalid"
    _wire_errors = (TypeError, UnicodeError, ValueError)

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_RECORD_BYTES

    source_snapshot: CodingWindowsWorkerHistorySourceSnapshotV1
    semantic_digest: str
    record_digest: str
    record_version: int = 1

    @classmethod
    def create(
        cls, semantic: CodingWindowsWorkerHistorySemanticReadV1
    ) -> CodingWindowsWorkerHistoryPreparationV1:
        return super(
            CodingWindowsWorkerHistoryPreparationV1, cls
        )._create_from_semantic_read(semantic)

    def require_semantic_read(
        self, semantic: CodingWindowsWorkerHistorySemanticReadV1
    ) -> None:
        return super(
            CodingWindowsWorkerHistoryPreparationV1, self
        )._require_semantic_read(semantic)


CodingWindowsWorkerHistoryPreparationV1._wire_schema = RecordSchema.for_dataclass(
    CodingWindowsWorkerHistoryPreparationV1,
    _unchanged,
    RecordField(
        "source_snapshot",
        decoder=lambda value: CodingWindowsWorkerHistorySourceSnapshotV1.from_dict(
            value
        ),
    ),
)


def prepare_coding_windows_worker_history(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryPreparationV1:
    """Durably bind guarded source/semantic proof without switching authority."""

    return prepare_windows_product_worker_history(
        product,
        product_id="coding",
        record_type=CodingWindowsWorkerHistoryPreparationV1,
        capture_semantic=_capture_coding_windows_worker_semantics_under_gc_guard,
        io=_receipt_io,
        name=_PREPARATION_NAME,
    )


__all__ = [
    "CodingWindowsWorkerHistoryPreparationV1",
    "prepare_coding_windows_worker_history",
]
