"""Private Windows receipt IO over the original handle, ACL and file primitives.

Configuration carries original caller bounds and exception identity. This object
holds no descriptors or transaction state; each call retains its native lifetime.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal._io_loops import write_all
from loushang.harness.resources.packages._file_consumption import closing_descriptor

from ._file_consumption import read_bounded_prefix
from ._private_tree_windows import supports_simple_windows_attributes
from .plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_directory_stream_names,
    windows_flush_directory,
    windows_flush_file,
    windows_regular_file_stream_names,
    windows_stat_at,
)


@dataclass(frozen=True)
class WindowsPrivateReceiptIO:
    maximum_allowed_bytes: int
    simple_file_attributes: int
    simple_directory_attributes: int
    error_type: type[RuntimeError]
    stage_suffix: str
    rename: Callable[[int, str, str], None]

    @contextmanager
    def _private_state_directory(
        self,
        path: Path,
    ) -> Iterator[tuple[int, WindowsPrivateDirectoryAcl]]:
        if os.name != "nt" or not isinstance(path, Path) or not path.is_absolute():
            raise self.error_type("Windows Product state root is unavailable")
        with WindowsPrivateDirectoryAcl() as acl:
            with closing_descriptor(
                open_windows_directory(path, share_delete=False, read_control=True)
            ) as descriptor:
                acl.validate(descriptor)
                self._require_simple_attributes(os.fstat(descriptor), directory=True)
                self._require_no_named_directory_streams(descriptor)
                yield descriptor, acl
                acl.validate(descriptor)
                self._require_simple_attributes(os.fstat(descriptor), directory=True)
                self._require_no_named_directory_streams(descriptor)

    def _read_file(
        self,
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
                self._require_simple_attributes(before, directory=False)
                if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
                    raise self.error_type("Windows Product receipt has a named stream")
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > maximum_bytes
            ):
                raise self.error_type("Windows Product receipt is unsafe")
            raw = read_bounded_prefix(descriptor, maximum_bytes, chunk_size=65536)
            after = os.fstat(descriptor)
            visible = windows_stat_at(directory_fd, name)
            if validate_file_acl:
                self._require_simple_attributes(after, directory=False)
                self._require_simple_attributes(visible, directory=False)
                if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
                    raise self.error_type("Windows Product receipt has a named stream")
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
                raise self.error_type("Windows Product receipt changed")
            if validate_file_acl:
                acl.validate(descriptor)
            return bytes(raw)
        finally:
            os.close(descriptor)

    def _require_simple_attributes(
        self, metadata: os.stat_result, *, directory: bool
    ) -> None:
        attributes = getattr(metadata, "st_file_attributes", None)
        if not supports_simple_windows_attributes(
            attributes,
            directory=directory,
            file_mask=self.simple_file_attributes,
            directory_mask=self.simple_directory_attributes,
        ):
            raise self.error_type("Windows Product receipt attributes are unsupported")

    def _require_no_named_directory_streams(self, descriptor: int) -> None:
        if any(
            name.casefold().endswith(":$data") and name.casefold() != "::$data"
            for name in windows_directory_stream_names(descriptor)
        ):
            raise self.error_type(
                "Windows Product receipt directory has a named stream"
            )

    def read_private_receipt(
        self, path: Path, *, maximum_bytes: int, allow_unpublished_stage: bool = False
    ) -> bytes | None:
        """Read one ACL-verified regular child without following a reparse point."""

        if maximum_bytes <= 0 or maximum_bytes > self.maximum_allowed_bytes:
            raise ValueError("Windows Product receipt bound is invalid")
        if type(allow_unpublished_stage) is not bool:
            raise TypeError("Windows Product receipt stage policy must be explicit")
        try:
            with self._private_state_directory(path.parent) as (directory_fd, acl):
                published = self._read_file(
                    directory_fd, acl, path.name, maximum_bytes=maximum_bytes
                )
                staged = self._read_file(
                    directory_fd,
                    acl,
                    path.name + self.stage_suffix,
                    maximum_bytes=maximum_bytes,
                )
                if published is not None and staged is not None:
                    raise self.error_type(
                        "Windows Product receipt has an unexpected stage"
                    )
                if (
                    published is None
                    and staged is not None
                    and not allow_unpublished_stage
                ):
                    raise self.error_type(
                        "Windows Product receipt has an unpublished stage"
                    )
                return published
        except FileNotFoundError:
            return None

    def read_ledger_bytes(self, path: Path, *, maximum_bytes: int) -> bytes | None:
        """Read the Product ledger through its private, pinned Windows parent."""

        with self._private_state_directory(path.parent) as (directory_fd, acl):
            return self._read_file(
                directory_fd,
                acl,
                path.name,
                maximum_bytes=maximum_bytes,
                validate_file_acl=False,
            )

    def write_private_receipt(
        self, path: Path, payload: bytes, *, maximum_bytes: int
    ) -> None:
        """Publish complete bytes once; exact staged retries may finish a crash."""

        if maximum_bytes <= 0 or maximum_bytes > self.maximum_allowed_bytes:
            raise ValueError("Windows Product receipt bound is invalid")
        if (
            not isinstance(payload, bytes)
            or not payload
            or len(payload) > maximum_bytes
        ):
            raise ValueError("Windows Product receipt payload is invalid")
        stage = path.name + self.stage_suffix
        with self._private_state_directory(path.parent) as (directory_fd, acl):
            if (
                self._read_file(
                    directory_fd, acl, path.name, maximum_bytes=maximum_bytes
                )
                is not None
            ):
                raise self.error_type("Windows Product receipt already exists")
            staged = self._read_file(
                directory_fd, acl, stage, maximum_bytes=maximum_bytes
            )
            if staged is None:
                with closing_descriptor(
                    open_windows_regular_file_at(
                        directory_fd,
                        stage,
                        create_new=True,
                        write=True,
                        security_descriptor=acl.security_descriptor,
                        read_control=True,
                    )
                ) as descriptor:
                    acl.validate(descriptor)
                    write_all(
                        lambda view: os.write(descriptor, view),
                        payload,
                        message="Windows Product receipt stage write stopped",
                        error_factory=self.error_type,
                    )
                    windows_flush_file(descriptor)
                staged = self._read_file(
                    directory_fd, acl, stage, maximum_bytes=maximum_bytes
                )
            if staged != payload:
                raise self.error_type(
                    "Windows Product receipt stage conflicts with review"
                )
            self.rename(directory_fd, stage, path.name)
            windows_flush_directory(directory_fd)
            if (
                self._read_file(
                    directory_fd, acl, path.name, maximum_bytes=maximum_bytes
                )
                != payload
            ):
                raise self.error_type("Windows Product receipt publication changed")
