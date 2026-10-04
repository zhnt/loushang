"""Native, single-record Product receipt I/O for a fenced Windows state root."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_directory_stream_names,
    windows_flush_directory,
    windows_flush_file,
    windows_regular_file_stream_names,
    windows_rename_at,
    windows_stat_at,
)

_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_MAX_EXTENDED_RECEIPT_BYTES = 64 * 1024 * 1024
_MAX_DESIRED_BYTES = 32 * 1024 * 1024
_SIMPLE_FILE_ATTRIBUTES = 0x00000020 | 0x00000080 | 0x00002000
_SIMPLE_DIRECTORY_ATTRIBUTES = 0x00000010 | 0x00000020 | 0x00002000


class CodingWindowsPrivateReceiptError(RuntimeError):
    """A Windows Product receipt or its unpublished stage is unsafe."""


@contextmanager
def _private_state_directory(
    path: Path,
) -> Iterator[tuple[int, WindowsPrivateDirectoryAcl]]:
    if os.name != "nt" or not isinstance(path, Path) or not path.is_absolute():
        raise CodingWindowsPrivateReceiptError(
            "Windows Product state root is unavailable"
        )
    with WindowsPrivateDirectoryAcl() as acl:
        descriptor = open_windows_directory(path, share_delete=False, read_control=True)
        try:
            acl.validate(descriptor)
            _require_simple_attributes(os.fstat(descriptor), directory=True)
            _require_no_named_directory_streams(descriptor)
            yield descriptor, acl
            acl.validate(descriptor)
            _require_simple_attributes(os.fstat(descriptor), directory=True)
            _require_no_named_directory_streams(descriptor)
        finally:
            os.close(descriptor)


def _read_file(
    directory_fd: int,
    acl: WindowsPrivateDirectoryAcl,
    name: str,
    *,
    maximum_bytes: int,
    validate_file_acl: bool = True,
) -> bytes | None:
    try:
        descriptor = open_windows_regular_file_at(
            directory_fd, name, create_new=False, write=False, read_control=True
        )
    except FileNotFoundError:
        return None
    try:
        if validate_file_acl:
            acl.validate(descriptor)
        before = os.fstat(descriptor)
        if validate_file_acl:
            _require_simple_attributes(before, directory=False)
            if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
                raise CodingWindowsPrivateReceiptError(
                    "Windows Product receipt has a named stream"
                )
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > maximum_bytes
        ):
            raise CodingWindowsPrivateReceiptError("Windows Product receipt is unsafe")
        raw = bytearray()
        while len(raw) <= maximum_bytes:
            chunk = os.read(descriptor, min(65536, maximum_bytes + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        visible = windows_stat_at(directory_fd, name)
        if validate_file_acl:
            _require_simple_attributes(after, directory=False)
            _require_simple_attributes(visible, directory=False)
            if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
                raise CodingWindowsPrivateReceiptError(
                    "Windows Product receipt has a named stream"
                )
        if (
            len(raw) > maximum_bytes
            or before.st_size != len(raw)
            or (
                before.st_dev,
                before.st_ino,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
            )
            or (
                after.st_dev,
                after.st_ino,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
            )
            != (
                visible.st_dev,
                visible.st_ino,
                visible.st_nlink,
                visible.st_size,
                visible.st_mtime_ns,
            )
            or (
                validate_file_acl
                and getattr(before, "st_file_attributes", None)
                != getattr(after, "st_file_attributes", None)
            )
            or (
                validate_file_acl
                and getattr(after, "st_file_attributes", None)
                != getattr(visible, "st_file_attributes", None)
            )
        ):
            raise CodingWindowsPrivateReceiptError("Windows Product receipt changed")
        if validate_file_acl:
            acl.validate(descriptor)
        return bytes(raw)
    finally:
        os.close(descriptor)


def _require_simple_attributes(metadata: os.stat_result, *, directory: bool) -> None:
    attributes = getattr(metadata, "st_file_attributes", None)
    allowed = _SIMPLE_DIRECTORY_ATTRIBUTES if directory else _SIMPLE_FILE_ATTRIBUTES
    if (
        type(attributes) is not int
        or attributes == 0
        or attributes & ~allowed
        or bool(attributes & 0x00000010) != directory
    ):
        raise CodingWindowsPrivateReceiptError(
            "Windows Product receipt attributes are unsupported"
        )


def _require_no_named_directory_streams(descriptor: int) -> None:
    if any(
        name.casefold().endswith(":$data") and name.casefold() != "::$data"
        for name in windows_directory_stream_names(descriptor)
    ):
        raise CodingWindowsPrivateReceiptError(
            "Windows Product receipt directory has a named stream"
        )


def read_windows_private_receipt(
    path: Path, *, maximum_bytes: int, allow_unpublished_stage: bool = False
) -> bytes | None:
    """Read one ACL-verified regular child without following a reparse point."""

    if maximum_bytes <= 0 or maximum_bytes > _MAX_EXTENDED_RECEIPT_BYTES:
        raise ValueError("Windows Product receipt bound is invalid")
    if type(allow_unpublished_stage) is not bool:
        raise TypeError("Windows Product receipt stage policy must be explicit")
    try:
        with _private_state_directory(path.parent) as (directory_fd, acl):
            published = _read_file(
                directory_fd, acl, path.name, maximum_bytes=maximum_bytes
            )
            staged = _read_file(
                directory_fd,
                acl,
                f"{path.name}.stage",
                maximum_bytes=maximum_bytes,
            )
            if published is not None and staged is not None:
                raise CodingWindowsPrivateReceiptError(
                    "Windows Product receipt has an unexpected stage"
                )
            if published is None and staged is not None and not allow_unpublished_stage:
                raise CodingWindowsPrivateReceiptError(
                    "Windows Product receipt has an unpublished stage"
                )
            return published
    except FileNotFoundError:
        return None


def read_windows_product_desired_bytes(path: Path) -> bytes | None:
    """Read the Product ledger through its private, pinned Windows parent."""

    with _private_state_directory(path.parent) as (directory_fd, acl):
        return _read_file(
            directory_fd,
            acl,
            path.name,
            maximum_bytes=_MAX_DESIRED_BYTES,
            validate_file_acl=False,
        )


def write_windows_private_receipt(
    path: Path, payload: bytes, *, maximum_bytes: int = _MAX_RECEIPT_BYTES
) -> None:
    """Publish complete bytes once; exact staged retries may finish a crash."""

    if maximum_bytes <= 0 or maximum_bytes > _MAX_EXTENDED_RECEIPT_BYTES:
        raise ValueError("Windows Product receipt bound is invalid")
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > maximum_bytes
    ):
        raise ValueError("Windows Product receipt payload is invalid")
    stage = f"{path.name}.stage"
    with _private_state_directory(path.parent) as (directory_fd, acl):
        if (
            _read_file(directory_fd, acl, path.name, maximum_bytes=maximum_bytes)
            is not None
        ):
            raise CodingWindowsPrivateReceiptError(
                "Windows Product receipt already exists"
            )
        staged = _read_file(directory_fd, acl, stage, maximum_bytes=maximum_bytes)
        if staged is None:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                stage,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
            try:
                acl.validate(descriptor)
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise CodingWindowsPrivateReceiptError(
                            "Windows Product receipt stage write stopped"
                        )
                    view = view[written:]
                windows_flush_file(descriptor)
            finally:
                os.close(descriptor)
            staged = _read_file(
                directory_fd, acl, stage, maximum_bytes=maximum_bytes
            )
        if staged != payload:
            raise CodingWindowsPrivateReceiptError(
                "Windows Product receipt stage conflicts with review"
            )
        windows_rename_at(directory_fd, stage, path.name)
        windows_flush_directory(directory_fd)
        if (
            _read_file(directory_fd, acl, path.name, maximum_bytes=maximum_bytes)
            != payload
        ):
            raise CodingWindowsPrivateReceiptError(
                "Windows Product receipt publication changed"
            )


__all__ = [
    "CodingWindowsPrivateReceiptError",
    "read_windows_private_receipt",
    "read_windows_product_desired_bytes",
    "write_windows_private_receipt",
]
