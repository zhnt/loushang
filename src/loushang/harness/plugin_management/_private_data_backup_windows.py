"""Windows private archives composed from existing native and codec owners.

The Product retains Installation/Desired/root-lineage admission and the offline
fence. This adapter owns only one call's native scopes; it has no journal,
transaction engine, retained handles or Product reference.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages._file_consumption import closing_descriptor
from loushang.harness.resources.packages._private_tree_windows import (
    PrivateWindowsTreeIO,
)
from loushang.harness.resources.packages._tree_observation import (
    MetadataIdentity,
    PrivateTreeMember,
    PrivateTreeSnapshot,
    logical_tree_members,
    metadata_identity,
    require_tree_subset,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_deletion_entry_at,
    open_windows_directory,
    windows_delete_open_entry,
    windows_flush_directory,
    windows_listdir_at,
    windows_rename_at,
    windows_stat_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from .private_data_backup import PrivateArchiveCodec, R, S
from .records import PluginInstallationKeyV1

_MemberT = TypeVar("_MemberT", bound=PrivateTreeMember)
_ArchiveT = TypeVar("_ArchiveT")


class WindowsPrivateArchiveSnapshot(Protocol):
    @property
    def root_identity(self) -> MetadataIdentity: ...
    @property
    def files(self) -> PrivateTreeSnapshot: ...
    @property
    def manifest(self) -> PrivateTreeMember: ...


class WindowsArchiveExpiryIO(Protocol):
    def require_expiry_tombstone_subset(
        self,
        parent_fd: int,
        tombstone_path: Path,
        tombstone: str,
        archive: WindowsPrivateArchiveSnapshot,
        acl: WindowsPrivateDirectoryAcl,
    ) -> PrivateTreeSnapshot | None: ...
    def remove_expired_archive(
        self,
        parent_fd: int,
        tombstone_path: Path,
        tombstone: str,
        archive: WindowsPrivateArchiveSnapshot,
        acl: WindowsPrivateDirectoryAcl,
    ) -> None: ...


@dataclass(frozen=True)
class WindowsPrivateArchiveIO(Generic[S, R]):
    io: PrivateWindowsTreeIO
    codec: PrivateArchiveCodec[S, R]
    capture: Callable[[Path, tuple[int, int]], S]

    def read_manifest(
        self, parent_fd: int, name: str, acl: WindowsPrivateDirectoryAcl
    ) -> tuple[R, S]:
        return self.codec.decode(
            self.io.read_manifest_bytes(
                parent_fd,
                name,
                acl,
                manifest_name=self.codec.manifest_name,
                maximum_bytes=self.codec.max_manifest_bytes,
            )
        )

    def write_manifest(
        self, stage_fd: int, source: S, receipt: R, acl: WindowsPrivateDirectoryAcl
    ) -> None:
        content = self.codec.encode(receipt.installation_key, source, receipt)
        if len(content) > self.codec.max_manifest_bytes:
            raise ValueError(f"{self.io.backup_label} backup manifest is too large")
        self.io.write_or_verify_archive_file(
            stage_fd, self.codec.manifest_name, content, acl, inherited_file=False
        )

    def verify_archive(
        self,
        parent_fd: int,
        parent_path: Path,
        name: str,
        key: PluginInstallationKeyV1,
        source: S,
        receipt: R,
        acl: WindowsPrivateDirectoryAcl,
    ) -> None:
        with closing_descriptor(
            open_windows_directory(
                name, dir_fd=parent_fd, share_delete=False, read_control=True
            )
        ) as archive_fd:
            acl.validate(archive_fd)
            archive_identity = self.io.directory_identity(archive_fd)
            if set(windows_listdir_at(archive_fd)) != {
                self.codec.files_name,
                self.codec.manifest_name,
            }:
                raise ValueError(
                    f"{self.io.backup_label} backup archive members changed"
                )
            actual_receipt, actual_source = self.read_manifest(parent_fd, name, acl)
            if (
                actual_receipt != receipt
                or actual_source != source
                or receipt.installation_key != key
            ):
                raise ValueError(f"{self.io.backup_label} backup manifest changed")
            with closing_descriptor(
                open_windows_directory(
                    self.codec.files_name,
                    dir_fd=archive_fd,
                    share_delete=False,
                    read_control=True,
                )
            ) as files_fd:
                acl.validate(files_fd)
                files_identity = self.io.directory_identity(files_fd)
                captured = self.capture(
                    parent_path / name / self.codec.files_name, files_identity
                )
                if logical_tree_members(captured) != logical_tree_members(source):
                    raise ValueError(f"{self.io.backup_label} backup files changed")
            if (
                self.io.directory_identity(archive_fd) != archive_identity
                or metadata_identity(windows_stat_at(parent_fd, name))[:2]
                != archive_identity
            ):
                raise ValueError(f"{self.io.backup_label} backup archive changed")

    def verify_retained(
        self,
        parent_path: Path,
        name: str,
        key: PluginInstallationKeyV1,
        acl: WindowsPrivateDirectoryAcl,
    ) -> R:
        parent_identity = inspect_windows_product_private_directory_identity(
            parent_path
        )

        def require_binding(receipt: R, source: S) -> None:
            if receipt.installation_key != key or receipt.backup_id != name:
                raise ValueError(f"{self.io.backup_label} backup Installation changed")

        receipt, _source = self._read_verified_source(
            parent_path,
            name,
            key,
            acl,
            parent_identity,
            require_binding=require_binding,
            label=self.io.backup_label,
            stage_error=f"{self.io.backup_label} backup stage needs recovery",
        )
        return receipt

    def read_restore_source(
        self,
        parent_path: Path,
        name: str,
        key: PluginInstallationKeyV1,
        *,
        source_matches: Callable[[S], bool],
        label: str,
    ) -> S:
        parent_identity = inspect_windows_product_private_directory_identity(
            parent_path
        )

        def require_binding(receipt: R, source: S) -> None:
            if (
                receipt.installation_key != key
                or receipt.backup_id != name
                or not source_matches(source)
            ):
                raise ValueError(f"{label} restore archive changed")

        with WindowsPrivateDirectoryAcl() as acl:
            _receipt, source = self._read_verified_source(
                parent_path,
                name,
                key,
                acl,
                parent_identity,
                require_binding=require_binding,
                label=label,
                stage_error=f"{label} backup parent changed",
            )
            return source

    def _read_verified_source(
        self,
        parent_path: Path,
        name: str,
        key: PluginInstallationKeyV1,
        acl: WindowsPrivateDirectoryAcl,
        parent_identity: tuple[int, int],
        *,
        require_binding: Callable[[R, S], None],
        stage_error: str,
        label: str,
    ) -> tuple[R, S]:
        """One original parent scope, shared by retained and restore queries."""
        with self._parent_scope(
            parent_path, parent_identity, acl, changed=f"{label} backup parent changed"
        ) as parent_fd:
            if any(
                name.endswith(self.codec.stage_suffix)
                for name in windows_listdir_at(parent_fd)
            ):
                raise ValueError(stage_error)
            receipt, source = self.read_manifest(parent_fd, name, acl)
            require_binding(receipt, source)
            self.verify_archive(parent_fd, parent_path, name, key, source, receipt, acl)
            return receipt, source

    def retain(
        self,
        source_root: Path,
        source: S,
        receipt: R,
        key: PluginInstallationKeyV1,
        parent_path: Path,
        *,
        source_is_current: Callable[[], bool],
    ) -> R:
        parent_identity = inspect_windows_product_private_directory_identity(
            parent_path
        )
        with (
            WindowsPrivateDirectoryAcl() as exact_acl,
            WindowsPrivateDirectoryAcl(inherit_children=True) as session_acl,
        ):
            with self._parent_scope(
                parent_path,
                parent_identity,
                exact_acl,
                changed=f"{self.io.backup_label} backup parent changed",
            ) as parent_fd:
                names = set(windows_listdir_at(parent_fd))
                stage_name = receipt.backup_id + self.codec.stage_suffix
                if any(
                    name.endswith(self.codec.stage_suffix) and name != stage_name
                    for name in names
                ):
                    raise ValueError(
                        f"Another {self.io.backup_label} backup stage needs recovery"
                    )
                if stage_name in names and receipt.backup_id in names:
                    raise ValueError(
                        f"{self.io.backup_label} backup stage needs recovery"
                    )
                if receipt.backup_id in names:
                    self.verify_archive(
                        parent_fd,
                        parent_path,
                        receipt.backup_id,
                        key,
                        source,
                        receipt,
                        exact_acl,
                    )
                    return receipt
                if stage_name in names:
                    stage_fd = open_windows_directory(
                        stage_name,
                        dir_fd=parent_fd,
                        share_delete=False,
                        read_control=True,
                    )
                else:
                    stage_fd = open_windows_directory(
                        stage_name,
                        dir_fd=parent_fd,
                        create_new=True,
                        security_descriptor=exact_acl.security_descriptor,
                        read_control=True,
                    )
                try:
                    exact_acl.validate(stage_fd)
                    if not set(windows_listdir_at(stage_fd)) <= {
                        self.codec.files_name,
                        self.codec.manifest_name,
                    }:
                        raise ValueError(
                            f"{self.io.backup_label} backup stage has extra members"
                        )
                    with closing_descriptor(
                        self.io.open_or_create_directory(
                            stage_fd, self.codec.files_name, exact_acl
                        )
                    ) as files_fd:
                        self.io.copy_members(
                            source_root, source, files_fd, exact_acl, session_acl
                        )
                        windows_flush_directory(files_fd)
                    self.write_manifest(stage_fd, source, receipt, exact_acl)
                    windows_flush_directory(stage_fd)
                finally:
                    os.close(stage_fd)
                if not source_is_current():
                    raise ValueError(f"{self.io.backup_label} backup source changed")
                try:
                    self.verify_archive(
                        parent_fd,
                        parent_path,
                        stage_name,
                        key,
                        source,
                        receipt,
                        exact_acl,
                    )
                except (OSError, ValueError) as exc:
                    raise ValueError(
                        f"{self.io.backup_label} backup stage needs recovery"
                    ) from exc
                windows_rename_at(parent_fd, stage_name, receipt.backup_id)
                windows_flush_directory(parent_fd)
                self.verify_archive(
                    parent_fd,
                    parent_path,
                    receipt.backup_id,
                    key,
                    source,
                    receipt,
                    exact_acl,
                )
                return receipt

    def copy_restore_source(
        self,
        parent_path: Path,
        name: str,
        source: S,
        stage_fd: int,
        *,
        label: str,
    ) -> None:
        parent_identity = inspect_windows_product_private_directory_identity(
            parent_path
        )
        with (
            WindowsPrivateDirectoryAcl() as exact_acl,
            WindowsPrivateDirectoryAcl(inherit_children=True) as session_acl,
        ):
            with closing_descriptor(
                open_windows_directory(
                    parent_path, share_delete=False, read_control=True
                )
            ) as parent_fd:
                exact_acl.validate(parent_fd)
                with closing_descriptor(
                    open_windows_directory(
                        name,
                        dir_fd=parent_fd,
                        share_delete=False,
                        read_control=True,
                    )
                ) as archive_fd:
                    exact_acl.validate(archive_fd)
                    with closing_descriptor(
                        open_windows_directory(
                            self.codec.files_name,
                            dir_fd=archive_fd,
                            share_delete=False,
                            read_control=True,
                        )
                    ) as files_fd:
                        exact_acl.validate(files_fd)
                        files_path = parent_path / name / self.codec.files_name
                        archived = self.capture(
                            files_path, self.io.directory_identity(files_fd)
                        )
                        if logical_tree_members(archived) != logical_tree_members(
                            source
                        ):
                            raise ValueError(f"{label} restore archive changed")
                        self.io.copy_members(
                            files_path, archived, stage_fd, exact_acl, session_acl
                        )
                        if (
                            self.capture(
                                files_path, self.io.directory_identity(files_fd)
                            )
                            != archived
                        ):
                            raise ValueError(f"{label} restore archive changed")
                if self.io.directory_identity(parent_fd) != parent_identity:
                    raise ValueError(f"{label} restore backup parent changed")

    def require_expiry_tombstone_subset(
        self,
        parent_fd: int,
        tombstone_path: Path,
        tombstone: str,
        archive: WindowsPrivateArchiveSnapshot,
        acl: WindowsPrivateDirectoryAcl,
    ) -> S | None:
        if archive.files.root_identity is None:
            raise ValueError(f"{self.io.label} expiry files identity is missing")
        with closing_descriptor(
            open_windows_directory(
                tombstone, dir_fd=parent_fd, share_delete=False, read_control=True
            )
        ) as descriptor:
            self.io.require_directory(descriptor, archive.root_identity[:2], acl)
            if (
                metadata_identity(windows_stat_at(parent_fd, tombstone))[:3]
                != archive.root_identity[:3]
            ):
                raise ValueError(f"{self.io.label} expiry tombstone changed")
            names = set(windows_listdir_at(descriptor))
            if not names <= {self.codec.files_name, self.codec.manifest_name}:
                raise ValueError(f"{self.io.label} expiry tombstone gained members")
            if self.codec.manifest_name in names:
                with closing_descriptor(
                    open_windows_deletion_entry_at(
                        descriptor, self.codec.manifest_name, directory=False
                    )
                ) as manifest_fd:
                    self.io.require_expiry_manifest(
                        manifest_fd,
                        descriptor,
                        archive.manifest,
                        acl,
                        manifest_name=self.codec.manifest_name,
                    )
            if self.codec.files_name in names:
                remaining = self.capture(
                    tombstone_path / self.codec.files_name,
                    archive.files.root_identity[:2],
                )
                require_tree_subset(remaining, archive.files, label=self.io.label)
                return remaining
            return None

    def remove_expired_archive(
        self,
        parent_fd: int,
        tombstone_path: Path,
        tombstone: str,
        archive: WindowsPrivateArchiveSnapshot,
        acl: WindowsPrivateDirectoryAcl,
    ) -> None:
        if archive.files.root_identity is None:
            raise ValueError(f"{self.io.label} expiry files identity is missing")
        remaining = self.require_expiry_tombstone_subset(
            parent_fd, tombstone_path, tombstone, archive, acl
        )
        if remaining is not None:
            self.io.remove_members(
                tombstone_path / self.codec.files_name, remaining.members, archive.files
            )
            with closing_descriptor(
                open_windows_directory(
                    tombstone, dir_fd=parent_fd, share_delete=False, read_control=True
                )
            ) as tombstone_fd:
                with closing_descriptor(
                    open_windows_deletion_entry_at(
                        tombstone_fd, self.codec.files_name, directory=True
                    )
                ) as files_fd:
                    self.io.require_directory(
                        files_fd, archive.files.root_identity[:2], acl
                    )
                    if windows_listdir_at(files_fd):
                        raise ValueError(f"{self.io.label} expiry files are not empty")
                    windows_delete_open_entry(
                        files_fd,
                        expected_identity=archive.files.root_identity,
                        directory=True,
                    )
                windows_flush_directory(tombstone_fd)
        with closing_descriptor(
            open_windows_directory(
                tombstone, dir_fd=parent_fd, share_delete=False, read_control=True
            )
        ) as tombstone_fd:
            if self.codec.manifest_name in windows_listdir_at(tombstone_fd):
                with closing_descriptor(
                    open_windows_deletion_entry_at(
                        tombstone_fd, self.codec.manifest_name, directory=False
                    )
                ) as manifest_fd:
                    self.io.require_expiry_manifest(
                        manifest_fd,
                        tombstone_fd,
                        archive.manifest,
                        acl,
                        manifest_name=self.codec.manifest_name,
                    )
                    windows_delete_open_entry(
                        manifest_fd,
                        expected_identity=archive.manifest.identity,
                        directory=False,
                    )
                windows_flush_directory(tombstone_fd)
            if windows_listdir_at(tombstone_fd):
                raise ValueError(f"{self.io.label} expiry tombstone is not empty")
        with closing_descriptor(
            open_windows_deletion_entry_at(parent_fd, tombstone, directory=True)
        ) as root_fd:
            self.io.require_directory(root_fd, archive.root_identity[:2], acl)
            if windows_listdir_at(root_fd):
                raise ValueError(f"{self.io.label} expiry tombstone is not empty")
            windows_delete_open_entry(
                root_fd, expected_identity=archive.root_identity, directory=True
            )
        windows_flush_directory(parent_fd)

    def capture_archive(
        self,
        parent_path: Path,
        name: str,
        key: PluginInstallationKeyV1,
        source: S,
        receipt: R,
        *,
        project_manifest: Callable[[MetadataIdentity, str], _MemberT],
        project: Callable[[MetadataIdentity, S, _MemberT], _ArchiveT],
    ) -> _ArchiveT:
        archive_path = parent_path / name
        parent_identity = inspect_windows_product_private_directory_identity(
            parent_path
        )
        with WindowsPrivateDirectoryAcl() as acl:
            with self._parent_scope(
                parent_path,
                parent_identity,
                acl,
                changed=f"{self.io.label} archive parent changed",
            ) as parent_fd:
                self.verify_archive(
                    parent_fd, parent_path, name, key, source, receipt, acl
                )
                with closing_descriptor(
                    open_windows_directory(
                        name, dir_fd=parent_fd, share_delete=False, read_control=True
                    )
                ) as archive_fd:
                    acl.validate(archive_fd)
                    self.io.require_no_named_directory_streams(archive_fd)
                    before = os.fstat(archive_fd)
                    self.io.require_simple_metadata(before, directory=True)
                    if set(windows_listdir_at(archive_fd)) != {
                        self.codec.files_name,
                        self.codec.manifest_name,
                    }:
                        raise ValueError(f"{self.io.label} archive members changed")
                    with closing_descriptor(
                        open_windows_directory(
                            self.codec.files_name,
                            dir_fd=archive_fd,
                            share_delete=False,
                            read_control=True,
                        )
                    ) as files_fd:
                        acl.validate(files_fd)
                        files_metadata = os.fstat(files_fd)
                        files = self.capture(
                            archive_path / self.codec.files_name,
                            self.io.directory_identity(files_fd),
                        )
                        if files.root_identity != metadata_identity(
                            files_metadata
                        ) or logical_tree_members(files) != logical_tree_members(
                            source
                        ):
                            raise ValueError(f"{self.io.label} archive files changed")
                        after_files = os.fstat(files_fd)
                        visible_files = windows_stat_at(
                            archive_fd, self.codec.files_name
                        )
                        self.io.require_same_metadata(
                            after_files, files_metadata, directory=True
                        )
                        self.io.require_same_metadata(
                            visible_files, files_metadata, directory=True
                        )
                        if metadata_identity(after_files) != metadata_identity(
                            files_metadata
                        ) or metadata_identity(visible_files) != metadata_identity(
                            files_metadata
                        ):
                            raise ValueError(f"{self.io.label} archive files changed")
                    manifest = self.io.capture_archive_manifest(
                        archive_fd,
                        acl,
                        manifest_name=self.codec.manifest_name,
                        maximum_bytes=self.codec.max_manifest_bytes,
                        expected_manifest=lambda: self.codec.encode(
                            key, source, receipt
                        ),
                        project=project_manifest,
                    )
                    self.verify_archive(
                        parent_fd, parent_path, name, key, source, receipt, acl
                    )
                    after = os.fstat(archive_fd)
                    visible = windows_stat_at(parent_fd, name)
                    self.io.require_same_metadata(after, before, directory=True)
                    self.io.require_same_metadata(visible, before, directory=True)
                    if (
                        metadata_identity(after) != metadata_identity(before)
                        or metadata_identity(visible) != metadata_identity(before)
                        or self.io.directory_identity(parent_fd) != parent_identity
                    ):
                        raise ValueError(f"{self.io.label} archive root changed")
                    return project(metadata_identity(before), files, manifest)

    @contextmanager
    def _parent_scope(
        self,
        path: Path,
        expected: tuple[int, int],
        acl: WindowsPrivateDirectoryAcl,
        *,
        changed: str,
    ) -> Iterator[int]:
        parent_fd = open_windows_directory(path, share_delete=False, read_control=True)
        try:
            acl.validate(parent_fd)
            if self.io.directory_identity(parent_fd) != expected:
                raise ValueError(changed)
            yield parent_fd
        finally:
            os.close(parent_fd)
            if inspect_windows_product_private_directory_identity(path) != expected:
                raise ValueError(changed)

    def retained_receipts(
        self,
        parent_path: Path,
        key: PluginInstallationKeyV1,
        *,
        package_root: Callable[[], Path],
        is_archive_name: Callable[[str], bool],
        allowed_tombstone: str | None = None,
        pending_backup_id: str | None = None,
    ) -> tuple[R, ...]:
        try:
            parent_identity = inspect_windows_product_private_directory_identity(
                parent_path
            )
        except FileNotFoundError:
            base_path = parent_path.parent
            try:
                inspect_windows_product_private_directory_identity(base_path)
            except FileNotFoundError:
                try:
                    base_path.lstat()
                except FileNotFoundError:
                    pass
                else:
                    raise ValueError(
                        f"{self.io.backup_label} backup base is unsafe"
                    ) from None
                inspect_windows_product_private_directory_identity(package_root())
                return ()
            try:
                parent_path.lstat()
            except FileNotFoundError:
                return ()
            raise ValueError(f"{self.io.backup_label} backup parent is unsafe")
        with WindowsPrivateDirectoryAcl() as acl:
            with self._parent_scope(
                parent_path,
                parent_identity,
                acl,
                changed=f"{self.io.backup_label} backup parent changed",
            ) as parent_fd:
                names = windows_listdir_at(parent_fd)
                if len(set(names)) != len(names):
                    raise ValueError(f"{self.io.backup_label} backup members repeat")
                if (
                    allowed_tombstone is not None
                    and allowed_tombstone in names
                    and pending_backup_id in names
                ):
                    raise ValueError(
                        f"{self.io.backup_label} backup expiry tombstone collides"
                    )
                receipts: list[R] = []
                for name in sorted(names):
                    if name == allowed_tombstone:
                        continue
                    if not is_archive_name(name):
                        raise ValueError(
                            f"{self.io.backup_label} backup member is unexpected"
                        )
                    receipt, source = self.read_manifest(parent_fd, name, acl)
                    if receipt.installation_key != key or receipt.backup_id != name:
                        raise ValueError(
                            f"{self.io.backup_label} backup identity changed"
                        )
                    self.verify_archive(
                        parent_fd, parent_path, name, key, source, receipt, acl
                    )
                    receipts.append(receipt)
                return tuple(receipts)
