"""Shared bounded tree observation; native handles remain with readers."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from ._file_consumption import FileConsumptionError, consume_file

MetadataIdentity = tuple[int, int, int, int, int]


def metadata_identity(value: os.stat_result) -> MetadataIdentity:
    return value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns


class PrivateTreeMember(Protocol):
    @property
    def relative_path(self) -> str: ...

    @property
    def kind(self) -> Literal["directory", "file"]: ...

    @property
    def identity(self) -> MetadataIdentity: ...

    @property
    def content_sha256(self) -> str | None: ...


class PrivateTreeSnapshot(Protocol):
    @property
    def root_identity(self) -> MetadataIdentity | None: ...

    @property
    def members(self) -> Sequence[PrivateTreeMember]: ...


NativeIdentity: TypeAlias = tuple[int, int]
IdentityMap: TypeAlias = dict[tuple[str, ...], NativeIdentity]


def logical_tree_members(
    snapshot: PrivateTreeSnapshot,
) -> tuple[tuple[str, str, int, str | None], ...]:
    """Compare copied contents without treating fresh inode/mtime as provenance."""
    return tuple(
        (
            item.relative_path,
            item.kind,
            item.identity[3] if item.kind == "file" else 0,
            item.content_sha256,
        )
        for item in snapshot.members
    )


class ExpectedTreeFile(Protocol):
    @property
    def byte_count(self) -> int: ...

    @property
    def content_digest(self) -> str: ...


class TreeObservationError(OSError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class TreeDirectoryUnavailable(OSError):
    """A reader could not enter a child that its enumeration observed."""


ObservedContents = dict[str, tuple[int, str]]
CollectedTree = tuple[ObservedContents, IdentityMap, IdentityMap]


@dataclass(frozen=True, slots=True)
class TreeFileReadPolicy:
    """Explicit unverified-source read contract; manifest validation stays fixed."""

    max_bytes: int
    chunk_size: int = 64 * 1024
    require_single_link_after_read: bool = True


@dataclass(frozen=True, slots=True)
class TreeEntryObservation:
    name: str
    kind: Literal["directory", "file", "other"]
    identity: NativeIdentity
    link_count: int
    byte_count: int | None = None
    native_order: int | None = None
    read_policy: TreeFileReadPolicy | None = None


class TreeFileReadPort(Protocol):
    def read(self, max_bytes: int) -> bytes: ...

    def identity_and_links(self) -> tuple[NativeIdentity, int]: ...


class TreeDirectoryReadPort(Protocol):
    def identity(self) -> NativeIdentity: ...

    def entries(self) -> AbstractContextManager[Iterator[TreeEntryObservation]]: ...

    def open_directory(
        self,
        name: str,
    ) -> AbstractContextManager[TreeDirectoryReadPort]: ...

    def file_reader(self, name: str) -> AbstractContextManager[TreeFileReadPort]: ...


def collect_tree(
    root: TreeDirectoryReadPort,
    expected: dict[str, ExpectedTreeFile] | None,
    *,
    directory_identities: IdentityMap | None,
    file_identities: IdentityMap | None,
    allow_partial: bool = False,
    explicit_directories: set[str] | None = None,
    allow_empty: bool = False,
    max_entries: int | None = None,
    max_file_bytes: int | None = None,
    max_total_bytes: int | None = None,
    verify_contents: bool = False,
    defer_directory_reads: bool = False,
    observe_file: Callable[[str, int, str], None] | None = None,
) -> CollectedTree:
    observed: ObservedContents = {}
    observed_directories: IdentityMap = {}
    observed_files: IdentityMap = {}
    expected_directories = {
        "/".join(parts[:depth])
        for logical_path in (expected or {})
        for parts in (tuple(logical_path.split("/")),)
        for depth in range(1, len(parts))
    }

    if explicit_directories is not None:
        expected_directories = explicit_directories
    entry_count = 0
    total_bytes = 0

    def visit(directory: TreeDirectoryReadPort, prefix: tuple[str, ...]) -> None:
        nonlocal entry_count, total_bytes
        saw_entry = False
        children: list[tuple[TreeEntryObservation, tuple[str, ...]]] = []
        with directory.entries() as entries:
            for member in entries:
                saw_entry = True
                entry_count += 1
                if max_entries is not None and entry_count > max_entries:
                    raise TreeObservationError("entry_limit")
                parts = prefix + (member.name,)
                logical_path = "/".join(parts)
                if member.kind == "directory":
                    if (
                        expected is not None or explicit_directories is not None
                    ) and logical_path not in expected_directories:
                        raise TreeObservationError("unexpected_directory")
                    if (
                        directory_identities is not None
                        and member.identity != directory_identities.get(parts)
                    ):
                        raise TreeObservationError("directory_identity")
                    if defer_directory_reads:
                        children.append((member, parts))
                    else:
                        visit_child(directory, member, parts)
                elif member.kind == "file":
                    entry = None if expected is None else expected.get(logical_path)
                    if (
                        expected is not None and entry is None
                    ) or member.link_count != 1:
                        raise TreeObservationError("unexpected_file")
                    if (
                        file_identities is not None
                        and member.identity != file_identities.get(parts)
                    ):
                        raise TreeObservationError("file_identity")
                    policy = member.read_policy if entry is None else None
                    limit = (
                        policy.max_bytes
                        if policy is not None
                        else member.byte_count
                        if entry is None
                        else entry.byte_count
                    )
                    if limit is None or limit < 0:
                        raise TreeObservationError("file_size_missing")
                    if max_file_bytes is not None and limit > max_file_bytes:
                        raise TreeObservationError("byte_limit")
                    with directory.file_reader(member.name) as reader:
                        quotas = [
                            value
                            for value in (
                                max_file_bytes,
                                None
                                if max_total_bytes is None
                                else max_total_bytes - total_bytes,
                            )
                            if value is not None
                        ]
                        try:
                            byte_count, digest = consume_file(
                                reader,
                                max_bytes=limit,
                                quota_bytes=min(quotas) if quotas else None,
                                chunk_size=64 * 1024
                                if policy is None
                                else policy.chunk_size,
                            )
                        except FileConsumptionError as error:
                            code = (
                                "byte_limit"
                                if error.code == "quota"
                                else "file_size_exceeded"
                            )
                            raise TreeObservationError(code) from None
                        total_bytes += byte_count
                        if verify_contents and entry is not None:
                            if byte_count != entry.byte_count:
                                raise TreeObservationError("file_size_changed")
                            if digest != entry.content_digest:
                                raise TreeObservationError("content_changed")
                        identity, link_count = reader.identity_and_links()
                        if identity != member.identity or (
                            link_count != 1
                            and (
                                policy is None or policy.require_single_link_after_read
                            )
                        ):
                            raise TreeObservationError("file_identity")
                        if observe_file is not None:
                            observe_file(logical_path, byte_count, digest)
                    observed[logical_path] = (byte_count, digest)
                    observed_files[parts] = member.identity
                else:
                    raise TreeObservationError("entry_type")
        if not saw_entry and prefix and not allow_partial and not allow_empty:
            raise TreeObservationError("empty_directory")
        children.sort(
            key=lambda pair: (
                pair[0].native_order
                if pair[0].native_order is not None
                else len(children)
            )
        )
        for member, parts in children:
            visit_child(directory, member, parts)

    def visit_child(
        directory: TreeDirectoryReadPort,
        member: TreeEntryObservation,
        parts: tuple[str, ...],
    ) -> None:
        with ExitStack() as stack:
            try:
                child = stack.enter_context(directory.open_directory(member.name))
            except TreeDirectoryUnavailable:
                return
            if child.identity() != member.identity:
                raise TreeObservationError("directory_identity")
            observed_directories[parts] = member.identity
            visit(child, parts)

    visit(root, ())
    if (
        not allow_partial
        and directory_identities is not None
        and set(observed_directories) != set(directory_identities)
    ):
        raise TreeObservationError("directory_set")
    if (
        not allow_partial
        and file_identities is not None
        and set(observed_files) != set(file_identities)
    ):
        raise TreeObservationError("file_set")
    return observed, observed_directories, observed_files


def require_tree_subset(
    remaining: PrivateTreeSnapshot, original: PrivateTreeSnapshot, *, label: str
) -> None:
    """An owned partial deletion may retain only original members and identities."""
    if (
        remaining.root_identity is None
        or original.root_identity is None
        or remaining.root_identity[:3] != original.root_identity[:3]
    ):
        raise ValueError(f"{label} tombstone changed")
    expected = {member.relative_path: member for member in original.members}
    for member in remaining.members:
        prior = expected.get(member.relative_path)
        if (
            prior is None
            or member.kind != prior.kind
            or (
                member.identity != prior.identity
                if member.kind == "file"
                else member.identity[:3] != prior.identity[:3]
            )
            or member.content_sha256 != prior.content_sha256
        ):
            raise ValueError(f"{label} tombstone member changed")
