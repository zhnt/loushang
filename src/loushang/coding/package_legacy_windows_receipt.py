"""Coding compatibility and policy binding for original native Windows receipts."""

from __future__ import annotations

from pathlib import Path

from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_rename_at,
)

_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_MAX_EXTENDED_RECEIPT_BYTES = 64 * 1024 * 1024
_MAX_DESIRED_BYTES = 32 * 1024 * 1024
_RECEIPT_STAGE_SUFFIX = ".stage"
_SIMPLE_FILE_ATTRIBUTES = 0x00000020 | 0x00000080 | 0x00002000
_SIMPLE_DIRECTORY_ATTRIBUTES = 0x00000010 | 0x00000020 | 0x00002000


class CodingWindowsPrivateReceiptError(RuntimeError):
    """A Windows Product receipt or its unpublished stage is unsafe."""


_receipt_io = WindowsPrivateReceiptIO(
    maximum_allowed_bytes=_MAX_EXTENDED_RECEIPT_BYTES,
    simple_file_attributes=_SIMPLE_FILE_ATTRIBUTES,
    simple_directory_attributes=_SIMPLE_DIRECTORY_ATTRIBUTES,
    error_type=CodingWindowsPrivateReceiptError,
    stage_suffix=_RECEIPT_STAGE_SUFFIX,
    rename=lambda directory_fd, old, new: windows_rename_at(directory_fd, old, new),
)
_read_file = _receipt_io._read_file
_require_simple_attributes = _receipt_io._require_simple_attributes
_require_no_named_directory_streams = _receipt_io._require_no_named_directory_streams


def read_windows_private_receipt(
    path: Path, *, maximum_bytes: int, allow_unpublished_stage: bool = False
) -> bytes | None:
    """Read one ACL-verified regular child without following a reparse point."""
    return _receipt_io.read_private_receipt(
        path,
        maximum_bytes=maximum_bytes,
        allow_unpublished_stage=allow_unpublished_stage,
    )


def read_windows_product_desired_bytes(path: Path) -> bytes | None:
    """Read the Product ledger through its private, pinned Windows parent."""
    return _receipt_io.read_ledger_bytes(path, maximum_bytes=_MAX_DESIRED_BYTES)


def write_windows_private_receipt(
    path: Path, payload: bytes, *, maximum_bytes: int = _MAX_RECEIPT_BYTES
) -> None:
    """Publish complete bytes once; exact staged retries may finish a crash."""
    _receipt_io.write_private_receipt(path, payload, maximum_bytes=maximum_bytes)


__all__ = [
    "CodingWindowsPrivateReceiptError",
    "read_windows_private_receipt",
    "read_windows_product_desired_bytes",
    "write_windows_private_receipt",
]
