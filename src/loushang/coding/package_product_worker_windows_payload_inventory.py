"""Read-only Product inventory of Windows Worker payload attempt directories.

An inventory entry is debt, not evidence that its contents may be launched or
deleted. The future materializer and recovery owner must join its attempt ID
to the Supervisor, native provisioning, Job, and Package lease histories.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.package_product._worker_windows_attempt import (
    read_windows_product_worker_attempts,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.payload._windows_stage_io import (
    inventory_windows_payload_stages,
)

_NAME = re.compile(r"worker-payload-([0-9a-f]{32})\Z")
_MAX_ATTEMPTS = 1024


class CodingWindowsWorkerPayloadInventoryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerPayloadAttemptV1:
    attempt_id: str
    directory_identity: tuple[int, int]


def inspect_coding_windows_product_worker_payload_attempts(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerPayloadAttemptV1, ...]:
    """List every retained payload attempt through the current Product root."""
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise OSError("Windows Worker payload inventory requires a Product owner")
    return read_windows_product_worker_attempts(
        product,
        inspect_attempts=lambda state_root, root: inspect_windows_worker_payload_stages(
            state_root, directory_fd=root
        ),
    )


def inspect_windows_worker_payload_stages(
    state_root: Path, *, directory_fd: int
) -> tuple[CodingWindowsWorkerPayloadAttemptV1, ...]:
    """Inventory names and direct directory identities without trusting content."""
    if (
        os.name != "nt"
        or not isinstance(state_root, Path)
        or not state_root.is_absolute()
        or type(directory_fd) is not int
        or directory_fd < 0
    ):
        raise OSError("Windows Worker payload inventory requires a pinned root")
    return inventory_windows_payload_stages(
        state_root,
        directory_fd=directory_fd,
        record_type=CodingWindowsWorkerPayloadAttemptV1,
        maximum_attempts=lambda: _MAX_ATTEMPTS,
        name_pattern=_NAME,
        error_type=CodingWindowsWorkerPayloadInventoryError,
        error_prefix="coding_worker_payload",
    )


__all__ = [
    "CodingWindowsWorkerPayloadAttemptV1",
    "CodingWindowsWorkerPayloadInventoryError",
    "inspect_coding_windows_product_worker_payload_attempts",
]
