"""POSIX-native rooted Store materialization for PLC9B3e-3c1.

The Store path is configuration held only by the role-specific Store owner.
Every operation pins the complete visible ancestor chain, writes through
descriptor-relative no-follow calls, and returns only an existing typed ref.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

from loushang.harness.resources.packages.plugin_lifecycle import _materialization_shared
from loushang.harness.resources.packages.plugin_lifecycle._file_sinks import (
    VerifiedFileSink as _PosixFileSink,
)
from loushang.harness.resources.packages.plugin_lifecycle._materialization_shared import (
    ObservedTree,
    PackageDependencyMaterializationStore,
    PackageDependencyReadOnlyStore,
    PackagePluginRootMaterializationStore,
    PackagePluginRootReadOnlyStore,
    PackageRoleStore,
)
from loushang.harness.resources.packages.plugin_lifecycle._materialization_shared import (
    settlement_record_present as _settlement_record_present,
)
from loushang.harness.resources.packages.plugin_lifecycle._tree_sink import (
    PackageVerifiedTreeSink,
)
from loushang.harness.resources.packages.plugin_lifecycle._tree_validation import (
    TreeDirectoryReadPort,
    TreeEntryObservation,
    TreeFileReadPort,
)
from loushang.harness.resources.packages.plugin_lifecycle._tree_validation import (
    collect_tree as _collect_observed_tree,
)
from loushang.harness.resources.packages.plugin_lifecycle._tree_validation import (
    validate_tree_contents as _validate_observed_tree_contents,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_gc import (
    PackageStoreGcResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
    PackageVerifiedTreeEntryV1,
    PackageVerifiedTreeManifestV1,
)

_Role = Literal["dependency", "root"]
_Identity = tuple[int, int]

# Retain the native modules' existing identity and completion helpers.
_stable_ref = _materialization_shared.stable_ref
finish_verified_tree = _materialization_shared.finish_verified_tree


class _PosixRoleStore(PackageRoleStore["_PinnedPosixRoot", "_PosixVerifiedTreeSink"]):
    def _check_available(self) -> None:
        if os.name != "posix" or not _supports_posix_rooted_io():
            raise PackagePhysicalStagingError(
                "POSIX rooted Store operations are unavailable",
                code="package_publication_root_untrusted",
            )

    def _open_root(
        self,
        *,
        expected_identities: tuple[_Identity, ...] | None = None,
        read_only: bool = False,
    ) -> _PinnedPosixRoot:
        return _PinnedPosixRoot.open(
            self._root, expected_identities=expected_identities
        )

    def _create_sink(
        self,
        root: _PinnedPosixRoot,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
        release_owner_lock: Callable[[], None],
    ) -> _PosixVerifiedTreeSink:
        return _PosixVerifiedTreeSink(
            root=root,
            role=self._role,
            store_identity=self._store_identity,
            request=request,
            manifest=manifest,
            commit_probe=self._commit_probe,
            receipt_probe=self._receipt_probe,
            settlement_journal=self._settlement_journal,
            release_owner_lock=release_owner_lock,
        )

    def delete_settlement(
        self, settlement: PackageStoreSettlementRecordV1
    ) -> PackageStoreGcResultV1:
        """Delete only the exact recorded tree; support a partial-delete retry."""

        if (
            not isinstance(settlement, PackageStoreSettlementRecordV1)
            or settlement.store_role != self._role
            or settlement.store_identity != self._store_identity
        ):
            raise _collision()
        self._lock.acquire()
        owner_lock = self._settlement_journal.owner_lock()
        owner_locked = False
        try:
            owner_lock.__enter__()
            owner_locked = True
            root = _PinnedPosixRoot.open(
                self._root, expected_identities=self._root_identities
            )
            try:
                if tuple(
                    identity.to_native() for identity in settlement.root_identities
                ) != root.identities or not _settlement_record_present(
                    self._settlement_journal.records(), settlement
                ):
                    raise _collision()
                self._settlement_journal.tombstone(settlement)
                try:
                    tree_fd = _open_directory(
                        settlement.final_name, dir_fd=root.descriptor
                    )
                except FileNotFoundError:
                    root.validate_visible()
                    return PackageStoreGcResultV1.create(
                        settlement, disposition="already_absent"
                    )
                try:
                    if (
                        _identity(os.fstat(tree_fd))
                        != settlement.tree_identity.to_native()
                    ):
                        raise _collision()
                    directories = {
                        tuple(
                            item.logical_path.split("/")
                        ): item.native_identity.to_native()
                        for item in settlement.directory_identities
                    }
                    files = {
                        tuple(
                            item.logical_path.split("/")
                        ): item.native_identity.to_native()
                        for item in settlement.file_identities
                    }
                    expected = {
                        item.logical_path: item for item in settlement.manifest.entries
                    }
                    observed, present_directories, present_files = _collect_tree(
                        tree_fd,
                        expected,
                        directory_identities=directories,
                        file_identities=files,
                        allow_partial=True,
                    )
                    if any(
                        observed[path]
                        != (expected[path].byte_count, expected[path].content_digest)
                        for path in observed
                    ):
                        raise _collision()
                    for parts in sorted(present_files, reverse=True):
                        parent_fd = _open_relative_directory(tree_fd, parts[:-1])
                        try:
                            current = os.stat(
                                parts[-1], dir_fd=parent_fd, follow_symlinks=False
                            )
                            if (
                                not stat.S_ISREG(current.st_mode)
                                or _identity(current) != present_files[parts]
                            ):
                                raise _collision()
                            os.unlink(parts[-1], dir_fd=parent_fd)
                        finally:
                            os.close(parent_fd)
                    for parts in sorted(
                        present_directories,
                        key=lambda value: (len(value), value),
                        reverse=True,
                    ):
                        parent_fd = _open_relative_directory(tree_fd, parts[:-1])
                        try:
                            current = os.stat(
                                parts[-1], dir_fd=parent_fd, follow_symlinks=False
                            )
                            if (
                                not stat.S_ISDIR(current.st_mode)
                                or _identity(current) != present_directories[parts]
                            ):
                                raise _collision()
                            os.rmdir(parts[-1], dir_fd=parent_fd)
                        finally:
                            os.close(parent_fd)
                    os.fsync(tree_fd)
                finally:
                    os.close(tree_fd)
                root.validate_visible()
                os.rmdir(settlement.final_name, dir_fd=root.descriptor)
                os.fsync(root.descriptor)
                root.validate_visible()
                return PackageStoreGcResultV1.create(settlement, disposition="deleted")
            finally:
                root.close()
        except PackagePhysicalStagingError:
            raise
        except Exception:
            raise _root_untrusted() from None
        finally:
            try:
                if owner_locked:
                    owner_lock.__exit__(None, None, None)
            finally:
                self._lock.release()


class _PinnedPosixRoot:
    def __init__(
        self,
        *,
        path: Path,
        components: tuple[str, ...],
        descriptors: list[int],
        identities: tuple[_Identity, ...],
    ) -> None:
        self.path = path
        self.components = components
        self._descriptors = descriptors
        self.identities = identities
        self._closed = False

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        expected_identities: tuple[_Identity, ...] | None = None,
    ) -> _PinnedPosixRoot:
        components = path.parts[1:]
        descriptors: list[int] = []
        try:
            current = _open_directory("/")
            descriptors.append(current)
            for component in components:
                current = _open_directory(component, dir_fd=current)
                descriptors.append(current)
            identities = tuple(_identity(os.fstat(fd)) for fd in descriptors)
            if expected_identities is not None and identities != expected_identities:
                raise OSError("Configured Package Store root identity changed")
            metadata = os.fstat(descriptors[-1])
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) & 0o077
                or metadata.st_uid != os.geteuid()
            ):
                raise OSError("Package Store root must be a private directory")
            pinned = cls(
                path=path,
                components=components,
                descriptors=descriptors,
                identities=identities,
            )
            pinned.validate_visible()
            return pinned
        except Exception:
            for descriptor in reversed(descriptors):
                with suppress(OSError):
                    os.close(descriptor)
            raise _root_untrusted() from None

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise RuntimeError("Package Store root handle is closed")
        return self._descriptors[-1]

    def validate_visible(self) -> None:
        if self._closed:
            raise OSError("Package Store root handle is closed")
        for descriptor, expected in zip(
            self._descriptors, self.identities, strict=True
        ):
            if _identity(os.fstat(descriptor)) != expected:
                raise OSError("Pinned Package Store ancestor identity changed")
        root_metadata = os.fstat(self._descriptors[-1])
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or stat.S_IMODE(root_metadata.st_mode) & 0o077
            or root_metadata.st_uid != os.geteuid()
        ):
            raise OSError("Pinned Package Store root permissions changed")
        visible = _open_directory("/")
        try:
            if _identity(os.fstat(visible)) != self.identities[0]:
                raise OSError("Package Store filesystem root identity changed")
            for component, expected in zip(
                self.components,
                self.identities[1:],
                strict=True,
            ):
                child = _open_directory(component, dir_fd=visible)
                os.close(visible)
                visible = child
                if _identity(os.fstat(visible)) != expected:
                    raise OSError("Package Store ancestor path identity changed")
        finally:
            os.close(visible)

    def validate_tree(
        self,
        final_name: str,
        manifest: PackageVerifiedTreeManifestV1,
    ) -> ObservedTree:
        return _validate_existing_tree(self, final_name, manifest)

    def close(self) -> None:
        if self._closed:
            return
        for descriptor in reversed(self._descriptors):
            with suppress(OSError):
                os.close(descriptor)
        self._descriptors.clear()
        self._closed = True

    def read_file(
        self,
        settlement: PackageStoreSettlementRecordV1,
        entry: PackageVerifiedTreeEntryV1,
    ) -> bytes:
        return _read_existing_tree_file(self, settlement, entry)


class _PosixVerifiedTreeSink(PackageVerifiedTreeSink["_PinnedPosixRoot"]):
    def _entry_exists(self, name: str) -> bool:
        return _entry_exists(self._root.descriptor, name)

    def _create_staging(self) -> None:
        os.mkdir(
            self._staging_name,
            mode=0o700,
            dir_fd=self._root.descriptor,
        )
        self._staging_fd = _open_directory(
            self._staging_name,
            dir_fd=self._root.descriptor,
        )
        self._staging_identity = _identity(os.fstat(self._staging_fd))

    def _create_file_sink(self, entry: PackageVerifiedTreeEntryV1) -> _PosixFileSink:
        if self._staging_fd is None:
            raise RuntimeError("Package Store staging root is unavailable")
        parts = tuple(entry.logical_path.split("/"))
        self._ensure_directories(parts[:-1])
        parent_fd = self._open_staging_directory(parts[:-1])
        try:
            descriptor = _open_regular_file(
                parent_fd,
                parts[-1],
                create_new=True,
                write=True,
            )
        except Exception:
            os.close(parent_fd)
            raise _root_untrusted() from None
        os.close(parent_fd)
        identity = _identity(os.fstat(descriptor))
        self._file_identities[parts] = identity
        return _PosixFileSink(
            entry=entry,
            writer=_PosixFileWriter(descriptor=descriptor, identity=identity),
            on_finished=self._file_finished,
        )

    def _ensure_directories(self, parts: tuple[str, ...]) -> None:
        for depth in range(1, len(parts) + 1):
            current = parts[:depth]
            if current in self._directory_identities:
                continue
            parent_fd = self._open_staging_directory(current[:-1])
            try:
                os.mkdir(current[-1], mode=0o700, dir_fd=parent_fd)
                child_fd = _open_directory(current[-1], dir_fd=parent_fd)
            except Exception:
                os.close(parent_fd)
                raise _root_untrusted() from None
            os.close(parent_fd)
            try:
                self._directory_identities[current] = _identity(os.fstat(child_fd))
            finally:
                os.close(child_fd)

    def _open_staging_directory(self, parts: tuple[str, ...]) -> int:
        if self._staging_fd is None or self._staging_identity is None:
            raise RuntimeError("Package Store staging root is unavailable")
        if _identity(os.fstat(self._staging_fd)) != self._staging_identity:
            raise _root_untrusted()
        current_fd = os.dup(self._staging_fd)
        try:
            for depth, part in enumerate(parts, start=1):
                child_fd = _open_directory(part, dir_fd=current_fd)
                expected = self._directory_identities.get(parts[:depth])
                if expected is None or _identity(os.fstat(child_fd)) != expected:
                    os.close(child_fd)
                    raise OSError("Package Store staging ancestor changed")
                os.close(current_fd)
                current_fd = child_fd
            return current_fd
        except PackagePhysicalStagingError:
            os.close(current_fd)
            raise
        except Exception:
            os.close(current_fd)
            raise _root_untrusted() from None

    def observe_reused_tree(self) -> ObservedTree:
        self._root.validate_visible()
        return _validate_existing_tree(self._root, self._final_name, self._manifest)

    def prepare_new_tree(self) -> ObservedTree:
        if self._staging_fd is None or self._staging_identity is None:
            raise RuntimeError("Package Store staging root is unavailable")
        for parts in sorted(
            self._directory_identities,
            key=lambda value: (len(value), value),
            reverse=True,
        ):
            descriptor = self._open_staging_directory(parts)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(self._staging_fd)
        visible = _open_directory(self._staging_name, dir_fd=self._root.descriptor)
        try:
            if _identity(os.fstat(visible)) != self._staging_identity:
                raise OSError("Package Store staging path identity changed")
        finally:
            os.close(visible)
        os.close(self._staging_fd)
        self._staging_fd = None
        if self._commit_probe is not None:
            self._commit_probe()
        try:
            self._root.validate_visible()
            visible = _open_directory(
                self._staging_name,
                dir_fd=self._root.descriptor,
            )
            try:
                _validate_owned_tree(
                    visible,
                    self._staging_identity,
                    self._manifest,
                    directory_identities=self._directory_identities,
                    file_identities=self._file_identities,
                )
            finally:
                os.close(visible)
        except Exception:
            raise _root_untrusted() from None
        if _entry_exists(self._root.descriptor, self._final_name):
            raise PackagePhysicalStagingError(
                "Package Store final identity already exists",
                code="package_publication_collision",
            )
        return (
            self._staging_identity,
            self._directory_identities,
            self._file_identities,
        )

    def publish_authorized_tree(self) -> None:
        self._authorized = True
        try:
            _rename_directory_noreplace(
                self._root.descriptor,
                self._staging_name,
                self._root.descriptor,
                self._final_name,
            )
            self._renamed = True
            os.fsync(self._root.descriptor)
            self._root.validate_visible()
            _validate_existing_tree(
                self._root,
                self._final_name,
                self._manifest,
                expected_tree_identity=self._staging_identity,
                directory_identities=self._directory_identities,
                file_identities=self._file_identities,
            )
            if self._receipt_probe is not None:
                self._receipt_probe()
        except FileExistsError:
            raise _collision() from None
        except PackagePhysicalStagingError:
            raise
        except Exception:
            raise _root_untrusted() from None

    def _remove_owned_tree(self, name: str, expected: _Identity) -> None:
        if self._staging_fd is not None:
            os.close(self._staging_fd)
            self._staging_fd = None
        tree_fd = _open_directory(name, dir_fd=self._root.descriptor)
        try:
            if _identity(os.fstat(tree_fd)) != expected:
                raise OSError("Package Store owned tree identity changed")
            for parts in sorted(self._file_identities, reverse=True):
                parent_fd = _open_relative_directory(tree_fd, parts[:-1])
                try:
                    metadata = os.stat(
                        parts[-1],
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    if _identity(metadata) != self._file_identities[
                        parts
                    ] or not stat.S_ISREG(metadata.st_mode):
                        raise OSError("Package Store owned file identity changed")
                    os.unlink(parts[-1], dir_fd=parent_fd)
                finally:
                    os.close(parent_fd)
            for parts in sorted(
                self._directory_identities,
                key=lambda value: (len(value), value),
                reverse=True,
            ):
                parent_fd = _open_relative_directory(tree_fd, parts[:-1])
                try:
                    metadata = os.stat(
                        parts[-1],
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    if _identity(metadata) != self._directory_identities[
                        parts
                    ] or not stat.S_ISDIR(metadata.st_mode):
                        raise OSError("Package Store owned directory identity changed")
                    os.rmdir(parts[-1], dir_fd=parent_fd)
                finally:
                    os.close(parent_fd)
        finally:
            os.close(tree_fd)
        os.rmdir(name, dir_fd=self._root.descriptor)

class _PosixFileWriter:
    def __init__(self, *, descriptor: int, identity: _Identity) -> None:
        self._descriptor: int | None = descriptor
        self._identity = identity

    def require_open(self) -> None:
        self._require_descriptor()

    def write(self, view: memoryview) -> int:
        return os.write(self._require_descriptor(), view)

    def identity_matches(self) -> bool:
        metadata = os.fstat(self._require_descriptor())
        return _identity(metadata) == self._identity and metadata.st_nlink == 1

    def flush(self) -> None:
        os.fsync(self._require_descriptor())

    def close(self) -> None:
        os.close(self._require_descriptor())
        self._descriptor = None

    def abort(self) -> None:
        if self._descriptor is not None:
            with suppress(OSError):
                os.close(self._descriptor)
            self._descriptor = None

    def _require_descriptor(self) -> int:
        if self._descriptor is None:
            raise RuntimeError("Package Store file sink is closed")
        return self._descriptor


def _validate_existing_tree(
    root: _PinnedPosixRoot,
    final_name: str,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    expected_tree_identity: _Identity | None = None,
    directory_identities: dict[tuple[str, ...], _Identity] | None = None,
    file_identities: dict[tuple[str, ...], _Identity] | None = None,
) -> tuple[
    _Identity,
    dict[tuple[str, ...], _Identity],
    dict[tuple[str, ...], _Identity],
]:
    try:
        root.validate_visible()
    except Exception:
        raise _root_untrusted() from None
    try:
        tree_fd = _open_directory(final_name, dir_fd=root.descriptor)
        try:
            tree_identity = _identity(os.fstat(tree_fd))
            if (
                expected_tree_identity is not None
                and tree_identity != expected_tree_identity
            ):
                raise OSError("Published Package tree identity changed")
            observed_directories, observed_files = _validate_tree_contents(
                tree_fd,
                manifest,
                directory_identities=directory_identities,
                file_identities=file_identities,
            )
        finally:
            os.close(tree_fd)
    except Exception:
        raise PackagePhysicalStagingError(
            "Existing Package Store object conflicts with verified identity",
            code="package_publication_collision",
        ) from None
    try:
        root.validate_visible()
    except Exception:
        raise _root_untrusted() from None
    return tree_identity, observed_directories, observed_files


def _read_existing_tree_file(
    root: _PinnedPosixRoot,
    settlement: PackageStoreSettlementRecordV1,
    entry: PackageVerifiedTreeEntryV1,
) -> bytes:
    directories = {
        tuple(item.logical_path.split("/")): item.native_identity.to_native()
        for item in settlement.directory_identities
    }
    files = {
        tuple(item.logical_path.split("/")): item.native_identity.to_native()
        for item in settlement.file_identities
    }
    tree_identity = settlement.tree_identity.to_native()
    _validate_existing_tree(
        root,
        settlement.final_name,
        settlement.manifest,
        expected_tree_identity=tree_identity,
        directory_identities=directories,
        file_identities=files,
    )
    try:
        tree_fd = _open_directory(settlement.final_name, dir_fd=root.descriptor)
        try:
            if _identity(os.fstat(tree_fd)) != tree_identity:
                raise OSError("Published Package tree identity changed")
            parts = tuple(entry.logical_path.split("/"))
            parent_fd = _open_relative_directory(tree_fd, parts[:-1])
            try:
                expected_parent = (
                    directories.get(parts[:-1]) if len(parts) > 1 else tree_identity
                )
                if _identity(os.fstat(parent_fd)) != expected_parent:
                    raise OSError("Published Package directory identity changed")
                file_fd = os.open(
                    parts[-1],
                    os.O_RDONLY
                    | os.O_NONBLOCK
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=parent_fd,
                )
                try:
                    metadata = os.fstat(file_fd)
                    if (
                        not stat.S_ISREG(metadata.st_mode)
                        or metadata.st_nlink != 1
                        or _identity(metadata) != files.get(parts)
                        or metadata.st_size != entry.byte_count
                    ):
                        raise OSError("Published Package file identity changed")
                    data = bytearray()
                    while chunk := os.read(
                        file_fd, min(64 * 1024, entry.byte_count + 1 - len(data))
                    ):
                        data.extend(chunk)
                        if len(data) > entry.byte_count:
                            raise OSError(
                                "Published Package file exceeds verified size"
                            )
                    if (
                        _identity(os.fstat(file_fd)) != files[parts]
                        or len(data) != entry.byte_count
                        or sha256(data).hexdigest() != entry.content_digest
                    ):
                        raise OSError("Published Package file content changed")
                finally:
                    os.close(file_fd)
            finally:
                os.close(parent_fd)
        finally:
            os.close(tree_fd)
        root.validate_visible()
        visible = os.stat(
            settlement.final_name,
            dir_fd=root.descriptor,
            follow_symlinks=False,
        )
        if _identity(visible) != tree_identity:
            raise OSError("Published Package tree visibility changed")
        return bytes(data)
    except Exception:
        raise _collision() from None


def _validate_owned_tree(
    tree_fd: int,
    expected_tree_identity: _Identity,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    directory_identities: dict[tuple[str, ...], _Identity],
    file_identities: dict[tuple[str, ...], _Identity],
) -> None:
    if _identity(os.fstat(tree_fd)) != expected_tree_identity:
        raise _root_untrusted()
    try:
        _validate_tree_contents(
            tree_fd,
            manifest,
            directory_identities=directory_identities,
            file_identities=file_identities,
        )
    except PackagePhysicalStagingError:
        raise
    except Exception:
        raise _root_untrusted() from None


def _validate_tree_contents(
    root_fd: int,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    directory_identities: dict[tuple[str, ...], _Identity] | None,
    file_identities: dict[tuple[str, ...], _Identity] | None,
) -> tuple[
    dict[tuple[str, ...], _Identity],
    dict[tuple[str, ...], _Identity],
]:
    return _validate_observed_tree_contents(
        _PosixTreeDirectoryReader(root_fd),
        manifest,
        directory_identities=directory_identities,
        file_identities=file_identities,
    )


def _collect_tree(
    root_fd: int,
    expected: dict[str, PackageVerifiedTreeEntryV1],
    *,
    directory_identities: dict[tuple[str, ...], _Identity] | None,
    file_identities: dict[tuple[str, ...], _Identity] | None,
    allow_partial: bool = False,
) -> tuple[
    dict[str, tuple[int, str]],
    dict[tuple[str, ...], _Identity],
    dict[tuple[str, ...], _Identity],
]:
    return _collect_observed_tree(
        _PosixTreeDirectoryReader(root_fd),
        expected,
        directory_identities=directory_identities,
        file_identities=file_identities,
        allow_partial=allow_partial,
    )


@dataclass(frozen=True)
class _PosixTreeFileReader:
    descriptor: int

    def read(self, max_bytes: int) -> bytes:
        return os.read(self.descriptor, max_bytes)

    def identity_and_links(self) -> tuple[_Identity, int]:
        metadata = os.fstat(self.descriptor)
        return _identity(metadata), metadata.st_nlink


@dataclass(frozen=True)
class _PosixTreeDirectoryReader:
    descriptor: int

    def identity(self) -> _Identity:
        return _identity(os.fstat(self.descriptor))

    @contextmanager
    def entries(self) -> Iterator[Iterator[TreeEntryObservation]]:
        with os.scandir(self.descriptor) as directory_entries:

            def observe() -> Iterator[TreeEntryObservation]:
                for entry in directory_entries:
                    name = entry.name
                    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
                        raise OSError("Published Package tree entry name is invalid")
                    metadata = os.stat(
                        name, dir_fd=self.descriptor, follow_symlinks=False
                    )
                    yield TreeEntryObservation(
                        name,
                        "directory"
                        if stat.S_ISDIR(metadata.st_mode)
                        else ("file" if stat.S_ISREG(metadata.st_mode) else "other"),
                        _identity(metadata),
                        metadata.st_nlink,
                    )

            yield observe()

    @contextmanager
    def open_directory(self, name: str) -> Iterator[TreeDirectoryReadPort]:
        descriptor = _open_directory(name, dir_fd=self.descriptor)
        try:
            yield _PosixTreeDirectoryReader(descriptor)
        finally:
            os.close(descriptor)

    @contextmanager
    def file_reader(self, name: str) -> Iterator[TreeFileReadPort]:
        descriptor = _open_regular_file(
            self.descriptor, name, create_new=False, write=False
        )
        try:
            yield _PosixTreeFileReader(descriptor)
        finally:
            os.close(descriptor)


def _supports_posix_rooted_io() -> bool:
    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and _noreplace_rename_function() is not None
        and os.rmdir in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
    )


_RenameAt = Callable[[int, bytes, int, bytes, int], int]


def _noreplace_rename_function() -> tuple[_RenameAt, int] | None:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except OSError:
        return None
    if sys.platform.startswith("linux"):
        function = getattr(libc, "renameat2", None)
        flag = 1  # RENAME_NOREPLACE
    elif sys.platform == "darwin":
        function = getattr(libc, "renameatx_np", None)
        flag = 0x00000004  # RENAME_EXCL
    else:
        return None
    if function is None:
        return None
    return cast(_RenameAt, function), flag


def _rename_directory_noreplace(
    source_directory_fd: int,
    source_name: str,
    target_directory_fd: int,
    target_name: str,
) -> None:
    resolved = _noreplace_rename_function()
    if resolved is None:
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is unavailable")
    function, flag = resolved
    ctypes.set_errno(0)
    result = function(
        source_directory_fd,
        os.fsencode(source_name),
        target_directory_fd,
        os.fsencode(target_name),
        flag,
    )
    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, os.strerror(error_number), target_name)


def _open_directory(path: str | Path, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags, dir_fd=dir_fd)


def _open_regular_file(
    directory_fd: int,
    name: str,
    *,
    create_new: bool,
    write: bool,
) -> int:
    flags = (os.O_WRONLY if write else os.O_RDONLY) | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    if create_new:
        flags |= os.O_CREAT | os.O_EXCL
    return os.open(name, flags, 0o600, dir_fd=directory_fd)


def _open_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            child_fd = _open_directory(part, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _entry_exists(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _identity(metadata: os.stat_result) -> _Identity:
    return (metadata.st_dev, metadata.st_ino)


def _root_untrusted() -> PackagePhysicalStagingError:
    return PackagePhysicalStagingError(
        "Package Store root or owned staging identity changed",
        code="package_publication_root_untrusted",
    )


def _collision() -> PackagePhysicalStagingError:
    return PackagePhysicalStagingError(
        "Package Store settlement evidence does not authorize this tree",
        code="package_publication_collision",
    )


__all__ = [
    "PackagePhysicalStagingError",
    "PosixPackageDependencyMaterializationStore",
    "PosixPackagePluginRootMaterializationStore",
    "PosixPackagePluginRootReadOnlyStore",
]


class PosixPackageDependencyMaterializationStore(PackageDependencyMaterializationStore):
    """Dependency-only adapter over one configured immutable Store root."""

    _store_type = _PosixRoleStore


class PosixPackageDependencyReadOnlyStore(PackageDependencyReadOnlyStore):
    """Store-verified dependency bytes for Product-owned execution proof."""

    _store_type = _PosixRoleStore


class PosixPackagePluginRootMaterializationStore(PackagePluginRootMaterializationStore):
    """Designated-Plugin-root adapter over one configured revision Store root."""

    _store_type = _PosixRoleStore


class PosixPackagePluginRootReadOnlyStore(PackagePluginRootReadOnlyStore):
    """Store-verified root reads for inert Product explanation and preview."""

    _store_type = _PosixRoleStore
