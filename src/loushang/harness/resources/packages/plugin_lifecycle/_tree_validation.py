"""Shared tree observation rules; native handles stay with platform readers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Protocol

from ._materialization_shared import IdentityMap
from .store_settlements import NativeIdentity
from .tree_transfer import PackageVerifiedTreeEntryV1, PackageVerifiedTreeManifestV1

ObservedContents = dict[str, tuple[int, str]]
CollectedTree = tuple[ObservedContents, IdentityMap, IdentityMap]


@dataclass(frozen=True, slots=True)
class TreeEntryObservation:
    name: str
    kind: Literal["directory", "file", "other"]
    identity: NativeIdentity
    link_count: int


class TreeFileReadPort(Protocol):
    def read(self, max_bytes: int) -> bytes: ...

    def identity_and_links(self) -> tuple[NativeIdentity, int]: ...


class TreeDirectoryReadPort(Protocol):
    def identity(self) -> NativeIdentity: ...

    def entries(self) -> AbstractContextManager[Iterator[TreeEntryObservation]]: ...

    def open_directory(
        self, name: str,
    ) -> AbstractContextManager[TreeDirectoryReadPort]: ...

    def file_reader(self, name: str) -> AbstractContextManager[TreeFileReadPort]: ...


def validate_tree_contents(
    root: TreeDirectoryReadPort,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    directory_identities: IdentityMap | None,
    file_identities: IdentityMap | None,
) -> tuple[IdentityMap, IdentityMap]:
    expected = {entry.logical_path: entry for entry in manifest.entries}
    observed, observed_directories, observed_files = collect_tree(
        root,
        expected,
        directory_identities=directory_identities,
        file_identities=file_identities,
    )
    if set(observed) != set(expected):
        raise OSError("Published Package tree members changed")
    for logical_path, entry in expected.items():
        byte_count, digest = observed[logical_path]
        if byte_count != entry.byte_count or digest != entry.content_digest:
            raise OSError("Published Package tree content changed")
    return observed_directories, observed_files


def collect_tree(
    root: TreeDirectoryReadPort,
    expected: dict[str, PackageVerifiedTreeEntryV1],
    *,
    directory_identities: IdentityMap | None,
    file_identities: IdentityMap | None,
    allow_partial: bool = False,
) -> CollectedTree:
    observed: ObservedContents = {}
    observed_directories: IdentityMap = {}
    observed_files: IdentityMap = {}
    expected_directories = {
        "/".join(parts[:depth])
        for logical_path in expected
        for parts in (tuple(logical_path.split("/")),)
        for depth in range(1, len(parts))
    }

    def visit(directory: TreeDirectoryReadPort, prefix: tuple[str, ...]) -> None:
        saw_entry = False
        with directory.entries() as entries:
            for member in entries:
                saw_entry = True
                parts = prefix + (member.name,)
                logical_path = "/".join(parts)
                if member.kind == "directory":
                    if logical_path not in expected_directories:
                        raise OSError("Published Package tree has an unexpected directory")
                    if (
                        directory_identities is not None
                        and member.identity != directory_identities.get(parts)
                    ):
                        raise OSError("Published Package directory identity changed")
                    with directory.open_directory(member.name) as child:
                        if child.identity() != member.identity:
                            raise OSError("Published Package directory identity changed")
                        observed_directories[parts] = member.identity
                        visit(child, parts)
                elif member.kind == "file":
                    entry = expected.get(logical_path)
                    if entry is None or member.link_count != 1:
                        raise OSError("Published Package tree has an unexpected file")
                    if (
                        file_identities is not None
                        and member.identity != file_identities.get(parts)
                    ):
                        raise OSError("Published Package file identity changed")
                    with directory.file_reader(member.name) as reader:
                        digest = sha256()
                        byte_count = 0
                        while chunk := reader.read(64 * 1024):
                            digest.update(chunk)
                            byte_count += len(chunk)
                            if byte_count > entry.byte_count:
                                raise OSError("Published Package file exceeds verified size")
                        identity, link_count = reader.identity_and_links()
                        if identity != member.identity or link_count != 1:
                            raise OSError("Published Package file identity changed")
                    observed[logical_path] = (byte_count, digest.hexdigest())
                    observed_files[parts] = member.identity
                else:
                    raise OSError("Published Package tree entry type changed")
        if not saw_entry and prefix and not allow_partial:
            raise OSError("Published Package tree contains an empty directory")

    visit(root, ())
    if (
        not allow_partial
        and directory_identities is not None
        and set(observed_directories) != set(directory_identities)
    ):
        raise OSError("Published Package directory set changed")
    if (
        not allow_partial
        and file_identities is not None
        and set(observed_files) != set(file_identities)
    ):
        raise OSError("Published Package file set changed")
    return observed, observed_directories, observed_files
