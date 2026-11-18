"""Publish the six Windows Worker bases without switching history authority.

Each file is immutable and source-bound. Interrupted publication can finish
only the same bytes after the old Product evidence is reproved. Ordinary
readers and Package GC reject a remaining base stage.
"""

from __future__ import annotations

import os

from loushang.harness.package_product._windows_worker_history import (
    guard_windows_product_worker_history_bases,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_legacy_windows_receipt import (
    _receipt_io,
)
from .package_product_worker_windows_checkpoint import (
    _CHECKPOINT_NAME,
    CodingWindowsWorkerHistoryCheckpointV1,
    _current_checkpoint_under_guard,
)
from .package_product_worker_windows_checkpoint import (
    _MAX_BYTES as _MAX_CHECKPOINT_BYTES,
)
from .package_product_worker_windows_package_references import (
    _review_coding_windows_worker_package_references_under_guard,
)

_MAX_BASE_BYTES = 32 * 1024 * 1024


def _guarded_bases(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    publish: bool,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker bases require their Product")
    return guard_windows_product_worker_history_bases(
        product,
        publish=publish,
        record_type=CodingWindowsWorkerHistoryCheckpointV1,
        review_checkpoint=_current_checkpoint_under_guard,
        review_references=_review_coding_windows_worker_package_references_under_guard,
        io=_receipt_io,
        checkpoint_name=_CHECKPOINT_NAME,
        limits=lambda: (_MAX_CHECKPOINT_BYTES, _MAX_BASE_BYTES),
    )


def publish_coding_windows_worker_history_bases(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    """Write exact typed bases after the canonical checkpoint is published."""

    return _guarded_bases(product, publish=True)


def read_coding_windows_worker_history_bases(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    """Reprove all six published bases without writing Product state."""

    return _guarded_bases(product, publish=False)


__all__ = [
    "publish_coding_windows_worker_history_bases",
    "read_coding_windows_worker_history_bases",
]
