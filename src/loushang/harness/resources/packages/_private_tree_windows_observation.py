"""Private Windows admission views for the existing common tree collector.

Package's existing Windows reader uses different sharing/ACL/metadata contracts.
These views retain private handle admission and projection timing, and delegate
all recursive traversal and digest consumption to the same collector.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from re import Pattern
from typing import Generic, Literal, TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages._file_consumption import closing_descriptor

from ._private_tree_windows import PrivateWindowsTreeIO
from ._tree_observation import (
    MetadataIdentity,
    PrivateTreeMember,
    TreeDirectoryReadPort,
    TreeEntryObservation,
    TreeFileReadPolicy,
    TreeFileReadPort,
    TreeObservationError,
    collect_tree,
    metadata_identity,
)
from .plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
)

_MemberT = TypeVar("_MemberT", bound=PrivateTreeMember)
_SnapshotT = TypeVar("_SnapshotT")


@dataclass(frozen=True)
class PrivateWindowsTreeShape:
    """One named root directory, admitted child directories, and direct files."""

    root_directory: str
    child_names: Pattern[str]
    invalid_child_message: str
    max_entries: int
    max_file_bytes: int
    max_total_bytes: int


@dataclass
class _Capture(Generic[_MemberT]):
    io: PrivateWindowsTreeIO
    shape: PrivateWindowsTreeShape
    make_member: Callable[
        [str, Literal["directory", "file"], MetadataIdentity, str | None], _MemberT
    ]
    members: list[_MemberT] = field(default_factory=list)
    total_bytes: int = 0
    current_file: _File[_MemberT] | None = None

    def append(self, member: _MemberT) -> None:
        if len(self.members) >= self.shape.max_entries:
            raise ValueError(f"{self.io.label} private-data preview is too large")
        self.members.append(member)

    def observe_file(self, path: str, _size: int, digest: str) -> None:
        current = self.current_file
        if current is None or current.path != path:
            raise RuntimeError("Private Windows file observation escaped its view")
        current.member = self.make_member(
            path, "file", metadata_identity(current.before), digest
        )


@dataclass
class _File(Generic[_MemberT]):
    descriptor: int
    parent_fd: int
    name: str
    path: str
    before: os.stat_result
    capture: _Capture[_MemberT]
    size: int = 0
    member: _MemberT | None = None
    live: bool = True

    def read(self, max_bytes: int) -> bytes:
        chunk = os.read(self.descriptor, max_bytes)
        self.size += len(chunk)
        return chunk

    def identity_and_links(self) -> tuple[tuple[int, int], int]:
        io = self.capture.io
        current = os.fstat(self.descriptor)
        visible = windows_stat_at(self.parent_fd, self.name)
        io.require_same_metadata(current, self.before, directory=False)
        io.require_same_metadata(visible, self.before, directory=False)
        if (
            windows_regular_file_stream_names(self.descriptor) != ("::$DATA",)
            or self.size != self.before.st_size
            or metadata_identity(current) != metadata_identity(self.before)
            or metadata_identity(visible) != metadata_identity(self.before)
        ):
            raise ValueError(f"{io.label} private-data file changed")
        return (current.st_dev, current.st_ino), current.st_nlink

    def close(self) -> None:
        if self.live:
            self.live = False
            os.close(self.descriptor)


@dataclass
class _Directory(Generic[_MemberT]):
    descriptor: int
    before: os.stat_result
    prefix: tuple[str, ...]
    capture: _Capture[_MemberT]
    exact_acl: WindowsPrivateDirectoryAcl
    inherited_acl: WindowsPrivateDirectoryAcl
    current_child: _Directory[_MemberT] | None = None

    def identity(self) -> tuple[int, int]:
        return self.before.st_dev, self.before.st_ino

    @contextmanager
    def entries(self) -> Iterator[Iterator[TreeEntryObservation]]:
        iterator = self._entries()
        try:
            yield iterator
        finally:
            iterator.close()

    def _entries(self) -> Generator[TreeEntryObservation, None, None]:
        shape = self.capture.shape
        io = self.capture.io
        names = windows_listdir_at(self.descriptor)
        if not self.prefix:
            if any(name != shape.root_directory for name in names):
                raise ValueError(f"{io.label} private-data member is unsupported")
            names = (shape.root_directory,) if names else ()
        else:
            names = tuple(sorted(names))
        for name in names:
            parts = (*self.prefix, name)
            path = "/".join(parts)
            if len(self.prefix) < 2:
                if self.prefix and shape.child_names.fullmatch(name) is None:
                    raise ValueError(shape.invalid_child_message)
                acl = (
                    self.inherited_acl
                    if len(parts) == io.inherited_directory_depth
                    else self.exact_acl
                )
                descriptor, before = io.open_directory_child(self.descriptor, name, acl)
                try:
                    self.capture.append(
                        self.capture.make_member(
                            path, "directory", metadata_identity(before), None
                        )
                    )
                    self.current_child = _Directory(
                        descriptor,
                        before,
                        parts,
                        self.capture,
                        self.exact_acl,
                        self.inherited_acl,
                    )
                    yield TreeEntryObservation(
                        name,
                        "directory",
                        (before.st_dev, before.st_ino),
                        before.st_nlink,
                    )
                    io.require_directory_unchanged(
                        self.descriptor, name, descriptor, before
                    )
                finally:
                    self.current_child = None
                    os.close(descriptor)
            else:
                view = self._open_file(name, path)
                self.capture.current_file = view
                try:
                    yield TreeEntryObservation(
                        name,
                        "file",
                        (view.before.st_dev, view.before.st_ino),
                        view.before.st_nlink,
                        view.before.st_size,
                        read_policy=TreeFileReadPolicy(
                            shape.max_file_bytes,
                            io.read_chunk_size,
                            require_single_link_after_read=False,
                        ),
                    )
                finally:
                    self.capture.current_file = None
                    view.close()

    def _open_file(self, name: str, path: str) -> _File[_MemberT]:
        io = self.capture.io
        before = windows_stat_at(self.descriptor, name)
        descriptor = open_windows_regular_file_at(
            self.descriptor, name, create_new=False, write=False, read_control=True
        )
        try:
            self.inherited_acl.validate(descriptor, inherited_file=True)
            io.require_same_metadata(os.fstat(descriptor), before, directory=False)
            if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
                raise ValueError(f"{io.label} private-data file has a named stream")
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > self.capture.shape.max_file_bytes
                or metadata_identity(os.fstat(descriptor)) != metadata_identity(before)
            ):
                raise ValueError(f"{io.label} private-data file is unsafe")
            return _File(descriptor, self.descriptor, name, path, before, self.capture)
        except BaseException:
            os.close(descriptor)
            raise

    @contextmanager
    def open_directory(self, name: str) -> Iterator[TreeDirectoryReadPort]:
        child = self.current_child
        if child is None or child.prefix != (*self.prefix, name):
            raise RuntimeError("Private Windows directory escaped its observation")
        yield child

    @contextmanager
    def file_reader(self, name: str) -> Iterator[TreeFileReadPort]:
        current = self.capture.current_file
        if current is None or current.path != "/".join((*self.prefix, name)):
            raise RuntimeError("Private Windows file escaped its observation")
        try:
            yield current
        finally:
            current.close()
        if current.member is None:
            raise RuntimeError("Private Windows file has no completed observation")
        self.capture.total_bytes += current.size
        if self.capture.total_bytes > self.capture.shape.max_total_bytes:
            raise ValueError(
                f"{self.capture.io.label} private-data preview is too large"
            )
        self.capture.append(current.member)


def capture_private_windows_tree(
    root: Path,
    *,
    expected_root: tuple[int, int],
    io: PrivateWindowsTreeIO,
    shape: PrivateWindowsTreeShape,
    make_member: Callable[
        [str, Literal["directory", "file"], MetadataIdentity, str | None], _MemberT
    ],
    project_snapshot: Callable[[MetadataIdentity, tuple[_MemberT, ...]], _SnapshotT],
) -> _SnapshotT:
    with (
        WindowsPrivateDirectoryAcl() as exact_acl,
        WindowsPrivateDirectoryAcl(inherit_children=True) as inherited_acl,
    ):
        with closing_descriptor(
            open_windows_directory(root, share_delete=False, read_control=True)
        ) as descriptor:
            exact_acl.validate(descriptor)
            io.require_no_named_directory_streams(descriptor)
            before = os.fstat(descriptor)
            io.require_simple_metadata(before, directory=True)
            if (before.st_dev, before.st_ino) != expected_root:
                raise ValueError(f"{io.label} private-data root changed")
            capture = _Capture(io, shape, make_member)
            try:
                collect_tree(
                    _Directory(
                        descriptor, before, (), capture, exact_acl, inherited_acl
                    ),
                    None,
                    directory_identities=None,
                    file_identities=None,
                    allow_empty=True,
                    observe_file=capture.observe_file,
                )
            except TreeObservationError as error:
                if error.code == "file_size_exceeded":
                    raise ValueError(
                        f"{io.label} private-data file is too large"
                    ) from None
                raise
            io.require_no_named_directory_streams(descriptor)
            current = os.fstat(descriptor)
            visible = root.lstat()
            io.require_same_metadata(current, before, directory=True)
            io.require_same_metadata(visible, before, directory=True)
            if metadata_identity(current) != metadata_identity(
                before
            ) or metadata_identity(visible) != metadata_identity(before):
                raise ValueError(f"{io.label} private-data root changed")
            return project_snapshot(
                metadata_identity(before),
                tuple(sorted(capture.members, key=lambda member: member.relative_path)),
            )
