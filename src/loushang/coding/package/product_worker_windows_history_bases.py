"""Publish the six Windows Worker bases without switching history authority.

Each file is immutable and source-bound. Interrupted publication can finish
only the same bytes after the old Product evidence is reproved. Ordinary
readers and Package GC reject a remaining base stage.
"""

from __future__ import annotations

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .product_worker_windows_checkpoint import (
    _HISTORY_COMMANDS,
    CodingWindowsWorkerHistoryCheckpointV1,
)


def publish_coding_windows_worker_history_bases(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    """Write exact typed bases after the canonical checkpoint is published."""

    return _HISTORY_COMMANDS.history_bases(product, publish=True)


def read_coding_windows_worker_history_bases(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCheckpointV1:
    """Reprove all six published bases without writing Product state."""

    return _HISTORY_COMMANDS.history_bases(product, publish=False)


__all__ = [
    "publish_coding_windows_worker_history_bases",
    "read_coding_windows_worker_history_bases",
]
