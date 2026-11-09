"""Native append-file custody over existing Windows handles and Journal locks.

The caller retains the Product root, GC gate and history decisions. The
optional read scope holds ACL and shared-lock custody while the caller decodes.
It creates no files, repairs no markers, retains no descriptors between calls,
and never interprets records or compensates partial writes.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import journal_file_lock_at
from loushang.harness.journal._io_loops import write_all

from ._file_consumption import borrowed_binary_stream
from .plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    windows_flush_directory,
    windows_flush_file,
    windows_regular_file_stream_names,
    windows_stat_at,
)


@contextmanager
def _owned_stream(descriptor: int, mode: Literal["rb", "r+b"]) -> Iterator[BinaryIO]:
    # Keep native ownership even if constructing the Python wrapper fails.
    # A partially constructed wrapper may close itself before raising.
    try:
        with borrowed_binary_stream(descriptor, mode) as stream:
            yield stream
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class WindowsJournalFileIO:
    name: str
    max_bytes: int
    lock_error: Callable[[], Exception]
    change_error: Callable[[], Exception]
    stream_error: Callable[[], Exception]
    lock_write_error: str
    lock_commit_error: str
    append_error: str
    lock_stream_policy: Literal["before_metadata", "after_metadata"] = "before_metadata"

    def __post_init__(self) -> None:
        if self.lock_stream_policy not in ("before_metadata", "after_metadata"):
            raise ValueError("Unsupported Windows Journal lock stream policy")

    @contextmanager
    def read_snapshot(
        self,
        root: int,
        *,
        assert_visible_root: Callable[[], None],
        missing_lock_error: Callable[[], Exception],
        orphan_lock_error: Callable[[], Exception],
    ) -> Iterator[bytes | None]:
        """Borrow the admitted root; yield bytes under the original read lock."""
        with WindowsPrivateDirectoryAcl() as acl:
            acl.validate(root)
            assert_visible_root()
            lock_name = self.name + ".lock"
            try:
                windows_stat_at(root, lock_name)
            except FileNotFoundError:
                try:
                    windows_stat_at(root, self.name)
                except FileNotFoundError:
                    assert_visible_root()
                    yield None
                    return
                raise missing_lock_error() from None
            with journal_file_lock_at(root, lock_name, "shared") as lock_handle:
                initialized = self.validate_lock(root, acl, locked_handle=lock_handle)
                raw = self.read(root, acl)
                if raw is None:
                    if initialized:
                        raise orphan_lock_error()
                    assert_visible_root()
                    yield None
                    return
                if not initialized:
                    raise self.lock_error()
                yield raw
            assert_visible_root()

    def require_plain_stream(self, descriptor: int) -> None:
        if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
            raise self.stream_error()

    def prepare_lock(self, root: int, acl: WindowsPrivateDirectoryAcl) -> None:
        name = self.name + ".lock"
        try:
            descriptor = open_windows_regular_file_at(
                root,
                name,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
        except FileExistsError:
            descriptor = open_windows_regular_file_at(
                root,
                name,
                create_new=False,
                write=True,
                read_control=True,
            )
            created = False
        else:
            created = True
        try:
            acl.validate(descriptor)
            if self.lock_stream_policy == "before_metadata":
                self.require_plain_stream(descriptor)
            if created:
                if os.write(descriptor, b"\0") != 1:
                    raise OSError(self.lock_write_error)
                windows_flush_file(descriptor)
            elif os.fstat(descriptor).st_size != 1:
                raise self.lock_error()
        finally:
            os.close(descriptor)
        if created:
            windows_flush_directory(root)

    def validate_lock(
        self,
        root: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        locked_handle: BinaryIO | None = None,
    ) -> bool:
        descriptor = (
            locked_handle.fileno()
            if locked_handle is not None
            else open_windows_regular_file_at(
                root,
                self.name + ".lock",
                create_new=False,
                write=False,
                read_control=True,
            )
        )
        try:
            acl.validate(descriptor)
            if self.lock_stream_policy == "before_metadata":
                self.require_plain_stream(descriptor)
            opened = os.fstat(descriptor)
            visible = windows_stat_at(root, self.name + ".lock")
            if (
                opened.st_size != 1
                or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
                or (
                    self.lock_stream_policy == "after_metadata"
                    and windows_regular_file_stream_names(descriptor) != ("::$DATA",)
                )
            ):
                raise self.lock_error()
            if locked_handle is None:
                marker = os.read(descriptor, 1)
            else:
                locked_handle.seek(0)
                marker = locked_handle.read(1)
            if marker not in {b"\0", b"\1"}:
                raise self.lock_error()
            return marker == b"\1"
        finally:
            if locked_handle is None:
                os.close(descriptor)

    def mark_initialized(self, handle: BinaryIO) -> None:
        handle.seek(0)
        if handle.read(1) != b"\0":
            raise self.lock_error()
        handle.seek(0)
        if handle.write(b"\1") != 1:
            raise OSError(self.lock_commit_error)
        handle.flush()
        windows_flush_file(handle.fileno())

    def read(
        self, root: int, acl: WindowsPrivateDirectoryAcl, *, missing_ok: bool = True
    ) -> bytes | None:
        try:
            descriptor = open_windows_regular_file_at(
                root,
                self.name,
                create_new=False,
                write=False,
                read_control=True,
            )
        except FileNotFoundError:
            if not missing_ok:
                raise
            return None
        with _owned_stream(descriptor, "rb") as source:
            acl.validate(source.fileno())
            self.require_plain_stream(source.fileno())
            return source.read(self.max_bytes + 1)

    def append(
        self,
        root: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        expected: bytes | None = None,
        line: bytes,
        validate_observation: Callable[[bytes, bool], None] | None = None,
    ) -> None:
        try:
            descriptor = open_windows_regular_file_at(
                root,
                self.name,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
        except FileExistsError:
            descriptor = open_windows_regular_file_at(
                root,
                self.name,
                create_new=False,
                write=True,
                read_control=True,
            )
            created = False
        else:
            created = True
        with _owned_stream(descriptor, "r+b") as output:
            acl.validate(output.fileno())
            self.require_plain_stream(output.fileno())
            observed = output.read(self.max_bytes + 1)
            if validate_observation is not None:
                validate_observation(observed, created)
            elif (created and (expected is not None or observed)) or (
                not created and observed != expected
            ):
                raise self.change_error()
            output.seek(0, os.SEEK_END)

            def write(data: memoryview) -> int:
                written = output.write(data)
                return 0 if written is None else written

            write_all(write, line, message=self.append_error)
            output.flush()
            windows_flush_file(output.fileno())
        if created:
            windows_flush_directory(root)

    def prepare_history_lock(
        self,
        root: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        missing_lock_error: Callable[[], Exception],
    ) -> None:
        """Retain the original initialized-history missing-lock check."""
        try:
            windows_stat_at(root, self.name + ".lock")
        except FileNotFoundError:
            try:
                windows_stat_at(root, self.name)
            except FileNotFoundError:
                pass
            else:
                raise missing_lock_error() from None
        self.prepare_lock(root, acl)

    def assert_visible_parent(
        self, root: int, parent: Path, *, changed_error: Callable[[], Exception]
    ) -> None:
        try:
            if not os.path.samestat(os.fstat(root), parent.lstat()):
                raise changed_error()
        except OSError as exc:
            raise changed_error() from exc

    def bind_append_snapshot(
        self,
        root: int,
        *,
        custody: ExitStack,
        assert_visible_root: Callable[[], None],
        prepare_lock: Callable[[int, WindowsPrivateDirectoryAcl], None],
    ) -> tuple[WindowsPrivateDirectoryAcl, BinaryIO, bytes | None, bool]:
        """Bind the original scopes to caller custody without a generator boundary.

        The original initialized marker/read checks precede every record decision.
        The caller's ExitStack retains normal exception and nested cleanup behavior.
        """
        acl = custody.enter_context(WindowsPrivateDirectoryAcl())
        acl.validate(root)
        assert_visible_root()
        prepare_lock(root, acl)
        lock_handle = custody.enter_context(
            journal_file_lock_at(root, self.name + ".lock", "exclusive")
        )
        initialized = self.validate_lock(root, acl, locked_handle=lock_handle)
        raw = self.read(root, acl)
        if (raw is None and initialized) or (raw is not None and not initialized):
            raise self.lock_error()
        return acl, lock_handle, raw, initialized
