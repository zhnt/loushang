"""Private Windows member IO over the original native handle and ACL owners.

This stateless adapter does not choose an Installation, admit a Product action,
capture an Arch-shaped tree, or publish action history. Product supplies the
original attribute/layout policy; callers keep their existing fences and ACLs.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal._io_loops import write_all
from loushang.harness.resources.packages._file_consumption import closing_descriptor

from ._file_consumption import (
    DescriptorReader,
    FileConsumptionError,
    consume_file,
    read_bounded_prefix,
)
from ._tree_observation import (
    MetadataIdentity,
    PrivateTreeMember,
    PrivateTreeSnapshot,
    logical_tree_members,
    metadata_identity,
)
from .plugin_lifecycle.windows_quarantine import (
    open_windows_deletion_entry_at,
    open_windows_directory,
    open_windows_regular_file_at,
    windows_delete_open_entry,
    windows_directory_stream_names,
    windows_flush_directory,
    windows_flush_file,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_rename_open_directory_at,
    windows_stat_at,
)

_ProjectionT = TypeVar("_ProjectionT")


@contextmanager
def private_windows_directory(
    path: Path,
    *,
    acl: WindowsPrivateDirectoryAcl | None = None,
    revalidate_on_success: bool = False,
) -> Iterator[int]:
    """Own a directory handle, borrowing an ACL when its lifetime is external."""
    with WindowsPrivateDirectoryAcl() if acl is None else nullcontext(acl) as owner:
        with closing_descriptor(
            open_windows_directory(path, share_delete=False, read_control=True)
        ) as descriptor:
            owner.validate(descriptor)
            yield descriptor
            if revalidate_on_success:
                owner.validate(descriptor)


def supports_simple_windows_attributes(
    attributes: object,
    *,
    directory: bool,
    file_mask: int,
    directory_mask: int,
) -> bool:
    allowed = directory_mask if directory else file_mask
    return (
        type(attributes) is int
        and attributes != 0
        and not attributes & ~allowed
        and bool(attributes & 0x00000010) == directory
    )


@dataclass(frozen=True)
class PrivateWindowsTreeIO:
    label: str
    backup_label: str
    simple_file_attributes: int
    simple_directory_attributes: int
    max_read_bytes: int
    read_chunk_size: int
    inherited_directory_depth: int
    exact_directory_name: str

    def read_manifest_bytes(
        self,
        parent_fd: int,
        name: str,
        acl: WindowsPrivateDirectoryAcl,
        *,
        manifest_name: str,
        maximum_bytes: int,
    ) -> bytes:
        """Keep archive manifest admission separate from source-file budgets."""
        with closing_descriptor(
            open_windows_directory(
                name, dir_fd=parent_fd, share_delete=False, read_control=True
            )
        ) as archive_fd:
            acl.validate(archive_fd)
            with closing_descriptor(
                open_windows_regular_file_at(
                    archive_fd,
                    manifest_name,
                    create_new=False,
                    write=False,
                    read_control=True,
                )
            ) as descriptor:
                acl.validate(descriptor)
                before = os.fstat(descriptor)
                self.require_simple_metadata(before, directory=False)
                if (
                    before.st_nlink != 1
                    or before.st_size > maximum_bytes
                    or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
                ):
                    raise ValueError(f"{self.backup_label} backup manifest is unsafe")
                raw = read_bounded_prefix(descriptor, maximum_bytes, chunk_size=65536)
                after = os.fstat(descriptor)
                self.require_same_metadata(after, before, directory=False)
                if (
                    len(raw) != before.st_size
                    or len(raw) > maximum_bytes
                    or metadata_identity(after) != metadata_identity(before)
                    or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
                ):
                    raise ValueError(f"{self.backup_label} backup manifest changed")
        return raw

    def open_directory_child(
        self, parent_fd: int, name: str, acl: WindowsPrivateDirectoryAcl
    ) -> tuple[int, os.stat_result]:
        metadata = windows_stat_at(parent_fd, name)
        descriptor = open_windows_directory(
            name, dir_fd=parent_fd, share_delete=False, read_control=True
        )
        try:
            acl.validate(descriptor)
            self.require_no_named_directory_streams(descriptor)
            self.require_same_metadata(os.fstat(descriptor), metadata, directory=True)
            if metadata_identity(os.fstat(descriptor)) != metadata_identity(metadata):
                raise ValueError(f"{self.label} private-data directory changed")
            return descriptor, metadata
        except BaseException:
            os.close(descriptor)
            raise

    def require_directory_unchanged(
        self, parent_fd: int, name: str, descriptor: int, expected: os.stat_result
    ) -> None:
        self.require_no_named_directory_streams(descriptor)
        current_directory = os.fstat(descriptor)
        current_path = windows_stat_at(parent_fd, name)
        self.require_same_metadata(current_directory, expected, directory=True)
        self.require_same_metadata(current_path, expected, directory=True)
        if metadata_identity(current_directory) != metadata_identity(
            expected
        ) or metadata_identity(current_path) != metadata_identity(expected):
            raise ValueError(f"{self.label} private-data directory changed")

    def require_no_named_directory_streams(self, descriptor: int) -> None:
        if any(
            name.casefold().endswith(":$data") and name.casefold() != "::$data"
            for name in windows_directory_stream_names(descriptor)
        ):
            raise ValueError(f"{self.label} private-data directory has a named stream")

    def require_simple_metadata(
        self, metadata: os.stat_result, *, directory: bool
    ) -> None:
        self.require_simple_attributes(
            getattr(metadata, "st_file_attributes", None), directory=directory
        )

    def require_simple_attributes(self, attributes: object, *, directory: bool) -> None:
        if not supports_simple_windows_attributes(
            attributes,
            directory=directory,
            file_mask=self.simple_file_attributes,
            directory_mask=self.simple_directory_attributes,
        ):
            raise ValueError(f"{self.label} private-data attributes are unsupported")

    def require_same_metadata(
        self, current: os.stat_result, expected: os.stat_result, *, directory: bool
    ) -> None:
        self.require_simple_metadata(expected, directory=directory)
        self.require_simple_metadata(current, directory=directory)
        if getattr(current, "st_file_attributes") != getattr(
            expected, "st_file_attributes"
        ):
            raise ValueError(f"{self.label} private-data attributes changed")

    def directory_identity(self, descriptor: int) -> tuple[int, int]:
        metadata = os.fstat(descriptor)
        self.require_simple_metadata(metadata, directory=True)
        self.require_no_named_directory_streams(descriptor)
        return metadata.st_dev, metadata.st_ino

    def open_or_create_directory(
        self, parent_fd: int, name: str, acl: WindowsPrivateDirectoryAcl
    ) -> int:
        created = False
        try:
            child_fd = open_windows_directory(
                name,
                dir_fd=parent_fd,
                create_new=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
            created = True
        except FileExistsError:
            child_fd = open_windows_directory(
                name, dir_fd=parent_fd, share_delete=False, read_control=True
            )
        try:
            acl.validate(child_fd)
            self.directory_identity(child_fd)
            if created:
                windows_flush_directory(parent_fd)
            return child_fd
        except BaseException:
            os.close(child_fd)
            raise

    def open_relative_directory(
        self,
        root_fd: int,
        parts: list[str],
        expected: dict[str, PrivateTreeMember] | None,
        exact_acl: WindowsPrivateDirectoryAcl,
        session_acl: WindowsPrivateDirectoryAcl,
    ) -> int:
        current_fd = os.dup(root_fd)
        path = ""
        try:
            for depth, part in enumerate(parts, start=1):
                path = part if not path else path + "/" + part
                next_fd, metadata = self.open_directory_child(
                    current_fd,
                    part,
                    session_acl
                    if depth == self.inherited_directory_depth
                    else exact_acl,
                )
                if expected is not None:
                    member = expected.get(path)
                    if (
                        member is None
                        or member.kind != "directory"
                        or metadata_identity(metadata) != member.identity
                    ):
                        os.close(next_fd)
                        raise ValueError(
                            f"{self.backup_label} backup source directory changed"
                        )
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except BaseException:
            os.close(current_fd)
            raise

    def copy_members(
        self,
        source_root: Path,
        source: PrivateTreeSnapshot,
        destination_fd: int,
        exact_acl: WindowsPrivateDirectoryAcl,
        session_acl: WindowsPrivateDirectoryAcl,
    ) -> None:
        with closing_descriptor(
            open_windows_directory(source_root, share_delete=False, read_control=True)
        ) as source_fd:
            exact_acl.validate(source_fd)
            if metadata_identity(os.fstat(source_fd)) != source.root_identity:
                raise ValueError(f"{self.backup_label} backup source root changed")
            expected = {item.relative_path: item for item in source.members}
            for item in sorted(
                source.members,
                key=lambda member: (
                    member.relative_path.count("/"),
                    member.relative_path,
                ),
            ):
                parts = item.relative_path.split("/")
                if item.kind == "directory":
                    with closing_descriptor(
                        self.open_relative_directory(
                            destination_fd, parts[:-1], None, exact_acl, session_acl
                        )
                    ) as parent_fd:
                        acl = (
                            session_acl
                            if len(parts) == self.inherited_directory_depth
                            else exact_acl
                        )
                        child_fd = self.open_or_create_directory(
                            parent_fd, parts[-1], acl
                        )
                        os.close(child_fd)
                        windows_flush_directory(parent_fd)
                    continue
                source_parent = self.open_relative_directory(
                    source_fd, parts[:-1], expected, exact_acl, session_acl
                )
                destination_parent: int | None = None
                try:
                    destination_parent = self.open_relative_directory(
                        destination_fd, parts[:-1], None, exact_acl, session_acl
                    )
                    content = self.read_source_file(
                        source_parent, parts[-1], item, session_acl
                    )
                    self.write_or_verify_archive_file(
                        destination_parent,
                        parts[-1],
                        content,
                        session_acl,
                        inherited_file=True,
                    )
                    windows_flush_directory(destination_parent)
                finally:
                    os.close(source_parent)
                    if destination_parent is not None:
                        os.close(destination_parent)

    def write_or_verify_archive_file(
        self,
        parent_fd: int,
        name: str,
        content: bytes,
        acl: WindowsPrivateDirectoryAcl,
        *,
        inherited_file: bool,
    ) -> None:
        try:
            descriptor = open_windows_regular_file_at(
                parent_fd,
                name,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
        except FileExistsError:
            with closing_descriptor(
                open_windows_regular_file_at(
                    parent_fd, name, create_new=False, write=True, read_control=True
                )
            ) as descriptor:
                acl.validate(descriptor, inherited_file=inherited_file)
                before = os.fstat(descriptor)
                self.require_simple_metadata(before, directory=False)
                if (
                    before.st_nlink != 1
                    or before.st_size > len(content)
                    or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
                ):
                    raise ValueError(f"{self.backup_label} backup stage file changed")
                raw = self.read_bounded(descriptor, len(content))
                current = os.fstat(descriptor)
                visible = windows_stat_at(parent_fd, name)
                self.require_same_metadata(current, before, directory=False)
                self.require_same_metadata(visible, before, directory=False)
                if (
                    len(raw) != before.st_size
                    or raw != content[: len(raw)]
                    or metadata_identity(current) != metadata_identity(before)
                    or metadata_identity(visible) != metadata_identity(before)
                    or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
                ):
                    raise ValueError(f"{self.backup_label} backup stage file changed")
                if len(raw) < len(content):
                    if os.lseek(descriptor, 0, os.SEEK_END) != len(raw):
                        raise ValueError(
                            f"{self.backup_label} backup stage file changed"
                        )
                    write_all(
                        lambda view: os.write(descriptor, view),
                        content[len(raw) :],
                        message=f"{self.backup_label} backup write stopped",
                    )
                    windows_flush_file(descriptor)
                os.lseek(descriptor, 0, os.SEEK_SET)
                complete = self.read_bounded(descriptor, len(content))
                after = os.fstat(descriptor)
                path_after = windows_stat_at(parent_fd, name)
                self.require_simple_metadata(after, directory=False)
                self.require_same_metadata(path_after, after, directory=False)
                if (
                    complete != content
                    or after.st_size != len(content)
                    or after.st_nlink != 1
                    or (after.st_dev, after.st_ino, after.st_mode)
                    != (before.st_dev, before.st_ino, before.st_mode)
                    or metadata_identity(path_after) != metadata_identity(after)
                    or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
                ):
                    raise ValueError(f"{self.backup_label} backup stage file changed")
                acl.validate(descriptor, inherited_file=inherited_file)
                return
        try:
            acl.validate(descriptor, inherited_file=inherited_file)
            write_all(
                lambda view: os.write(descriptor, view),
                content,
                message=f"{self.backup_label} backup write stopped",
            )
            windows_flush_file(descriptor)
        finally:
            os.close(descriptor)

    def read_bounded(self, descriptor: int, maximum_bytes: int) -> bytes:
        raw = read_bounded_prefix(descriptor, maximum_bytes)
        if len(raw) > maximum_bytes:
            raise ValueError(f"{self.backup_label} backup file is too large")
        return raw

    def read_source_file(
        self,
        parent_fd: int,
        name: str,
        item: PrivateTreeMember,
        acl: WindowsPrivateDirectoryAcl,
    ) -> bytes:
        metadata = windows_stat_at(parent_fd, name)
        with closing_descriptor(
            open_windows_regular_file_at(
                parent_fd, name, create_new=False, write=False, read_control=True
            )
        ) as descriptor:
            acl.validate(descriptor, inherited_file=True)
            self.require_same_metadata(os.fstat(descriptor), metadata, directory=False)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size > self.max_read_bytes
                or metadata_identity(metadata) != item.identity
                or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            ):
                raise ValueError(f"{self.backup_label} backup source file changed")
            chunks = read_bounded_prefix(descriptor, self.max_read_bytes)
            current = os.fstat(descriptor)
            visible = windows_stat_at(parent_fd, name)
            self.require_same_metadata(current, metadata, directory=False)
            self.require_same_metadata(visible, metadata, directory=False)
            if (
                len(chunks) != metadata.st_size
                or len(chunks) > self.max_read_bytes
                or sha256(chunks).hexdigest() != item.content_sha256
                or metadata_identity(current) != item.identity
                or metadata_identity(visible) != item.identity
                or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            ):
                raise ValueError(f"{self.backup_label} backup source file changed")
            return bytes(chunks)

    def remove_members(
        self,
        tombstone: Path,
        members: Sequence[PrivateTreeMember],
        original: PrivateTreeSnapshot,
    ) -> None:
        expected = {member.relative_path: member for member in original.members}
        with (
            WindowsPrivateDirectoryAcl() as exact_acl,
            WindowsPrivateDirectoryAcl(inherit_children=True) as inherited_acl,
        ):
            with closing_descriptor(
                open_windows_directory(tombstone, share_delete=False, read_control=True)
            ) as tombstone_fd:
                if original.root_identity is None:
                    raise ValueError(f"{self.label} tombstone has no root")
                self.require_directory(
                    tombstone_fd, original.root_identity[:2], exact_acl
                )
                for member in sorted(
                    members,
                    key=lambda item: (
                        item.relative_path.count("/"),
                        item.relative_path,
                    ),
                    reverse=True,
                ):
                    parts = member.relative_path.split("/")
                    parent_fd = os.dup(tombstone_fd)
                    try:
                        path = ""
                        for part in parts[:-1]:
                            path = part if not path else path + "/" + part
                            prior = expected[path]
                            next_fd = open_windows_directory(
                                part,
                                dir_fd=parent_fd,
                                share_delete=False,
                                read_control=True,
                            )
                            try:
                                self.require_directory(
                                    next_fd,
                                    prior.identity[:2],
                                    exact_acl
                                    if path == self.exact_directory_name
                                    else inherited_acl,
                                )
                            except BaseException:
                                os.close(next_fd)
                                raise
                            os.close(parent_fd)
                            parent_fd = next_fd
                        with closing_descriptor(
                            open_windows_deletion_entry_at(
                                parent_fd,
                                parts[-1],
                                directory=member.kind == "directory",
                            )
                        ) as entry_fd:
                            if member.kind == "directory":
                                self.require_directory(
                                    entry_fd,
                                    member.identity[:2],
                                    exact_acl
                                    if member.relative_path == self.exact_directory_name
                                    else inherited_acl,
                                )
                                if windows_listdir_at(entry_fd):
                                    raise ValueError(
                                        f"{self.label} directory is not empty"
                                    )
                            else:
                                self.require_file(
                                    entry_fd,
                                    parent_fd,
                                    parts[-1],
                                    member,
                                    inherited_acl,
                                )
                            windows_delete_open_entry(
                                entry_fd,
                                expected_identity=member.identity,
                                directory=member.kind == "directory",
                            )
                        windows_flush_directory(parent_fd)
                    finally:
                        os.close(parent_fd)
                if windows_listdir_at(tombstone_fd):
                    raise ValueError(f"{self.label} tombstone is not empty")
                windows_flush_directory(tombstone_fd)

    def require_tombstone_view(
        self,
        root: Path,
        *,
        expected_parent: tuple[int, int],
        root_identity: MetadataIdentity,
        original: PrivateTreeSnapshot,
        present: bool,
        make_tombstone_name: Callable[[], str],
        capture: Callable[[Path], PrivateTreeSnapshot],
    ) -> None:
        """Verify the original ACL/name/identity view without choosing a Product root."""
        with WindowsPrivateDirectoryAcl() as acl:
            with closing_descriptor(
                open_windows_directory(
                    root.parent, share_delete=False, read_control=True
                )
            ) as parent_fd:
                acl.validate(parent_fd)
                metadata = os.fstat(parent_fd)
                if (metadata.st_dev, metadata.st_ino) != expected_parent:
                    raise ValueError(f"{self.label} tombstone parent changed")
                names = set(windows_listdir_at(parent_fd))
                tombstone_name = make_tombstone_name()
                if root.name in names or (tombstone_name in names) != present:
                    raise ValueError(f"{self.label} tombstone state changed")
                if present:
                    remaining = capture(root.parent / tombstone_name)
                    if (
                        remaining.root_identity is None
                        or remaining.root_identity[:3] != root_identity[:3]
                        or remaining.members != original.members
                    ):
                        raise ValueError(f"{self.label} tombstone bytes changed")
                acl.validate(parent_fd)
                current = os.fstat(parent_fd)
                if (current.st_dev, current.st_ino) != expected_parent:
                    raise ValueError(f"{self.label} tombstone parent changed")

    def require_directory(
        self,
        descriptor: int,
        expected_identity: tuple[int, int],
        acl: WindowsPrivateDirectoryAcl,
    ) -> None:
        acl.validate(descriptor)
        metadata = os.fstat(descriptor)
        self.require_simple_metadata(metadata, directory=True)
        self.require_no_named_directory_streams(descriptor)
        if (metadata.st_dev, metadata.st_ino) != expected_identity:
            raise ValueError(f"{self.label} directory identity changed")

    def require_file(
        self,
        descriptor: int,
        parent_fd: int,
        name: str,
        member: PrivateTreeMember,
        acl: WindowsPrivateDirectoryAcl,
    ) -> None:
        acl.validate(descriptor, inherited_file=True)
        before = os.fstat(descriptor)
        self.require_simple_metadata(before, directory=False)
        if (
            windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            or metadata_identity(before) != member.identity
        ):
            raise ValueError(f"{self.label} file identity changed")
        try:
            size, digest = consume_file(
                DescriptorReader(descriptor),
                max_bytes=member.identity[3],
                chunk_size=self.read_chunk_size,
            )
        except FileConsumptionError:
            raise ValueError(f"{self.label} file bytes changed") from None
        after = os.fstat(descriptor)
        visible = windows_stat_at(parent_fd, name)
        self.require_simple_metadata(after, directory=False)
        self.require_simple_metadata(visible, directory=False)
        if (
            size != member.identity[3]
            or digest != member.content_sha256
            or metadata_identity(after) != member.identity
            or metadata_identity(visible) != member.identity
            or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
        ):
            raise ValueError(f"{self.label} file bytes changed")
        acl.validate(descriptor, inherited_file=True)

    def publish_restore_stage(
        self,
        parent_fd: int,
        root: Path,
        source: PrivateTreeSnapshot,
        stage_name: str,
        stage_identity: MetadataIdentity,
        acl: WindowsPrivateDirectoryAcl,
        *,
        capture: Callable[[Path], PrivateTreeSnapshot],
    ) -> None:
        stage = root.parent / stage_name
        staged = capture(stage)
        if staged.root_identity != stage_identity or logical_tree_members(
            staged
        ) != logical_tree_members(source):
            raise ValueError(f"{self.label} restore stage changed")
        with closing_descriptor(
            open_windows_deletion_entry_at(parent_fd, stage_name, directory=True)
        ) as descriptor:
            acl.validate(descriptor)
            self.require_simple_metadata(os.fstat(descriptor), directory=True)
            self.require_no_named_directory_streams(descriptor)
            if metadata_identity(os.fstat(descriptor)) != stage_identity:
                raise ValueError(f"{self.label} restore stage identity changed")
            windows_rename_open_directory_at(
                parent_fd,
                descriptor,
                root.name,
                expected_identity=stage_identity,
            )
        windows_flush_directory(parent_fd)

    def require_restore_target_absent(
        self,
        root: Path,
        parent_identity: tuple[int, int],
        acl: WindowsPrivateDirectoryAcl,
        *,
        stage_prefix: str,
        parent_changed: str,
        state_debt: str,
    ) -> None:
        with private_windows_directory(
            root.parent, acl=acl, revalidate_on_success=True
        ) as descriptor:
            if self.directory_identity(descriptor) != parent_identity:
                raise ValueError(parent_changed)
            names = windows_listdir_at(descriptor)
            if root.name in names or any(
                name.startswith(stage_prefix) for name in names
            ):
                raise ValueError(state_debt)

    def require_recovery_parent_view(
        self,
        root: Path,
        parent_identity: tuple[int, int],
        *,
        stage_prefix: str,
        changed: str,
    ) -> None:
        with private_windows_directory(root.parent) as descriptor:
            if (
                self.directory_identity(descriptor) != parent_identity
                or root.name not in windows_listdir_at(descriptor)
                or any(
                    name.startswith(stage_prefix)
                    for name in windows_listdir_at(descriptor)
                )
            ):
                raise ValueError(changed)

    def require_restore_published_view(
        self,
        root: Path,
        source: PrivateTreeSnapshot,
        stage_identity: MetadataIdentity,
        *,
        stage_prefix: str,
        capture: Callable[[Path], PrivateTreeSnapshot],
    ) -> None:
        with private_windows_directory(root.parent) as parent_fd:
            names = set(windows_listdir_at(parent_fd))
            if root.name not in names or any(
                name.startswith(stage_prefix) for name in names
            ):
                raise ValueError(f"{self.label} restore publication has stage debt")
        restored = capture(root)
        if restored.root_identity != stage_identity or logical_tree_members(
            restored
        ) != logical_tree_members(source):
            raise ValueError(f"{self.label} restored root changed")

    def require_expiry_manifest(
        self,
        descriptor: int,
        parent_fd: int,
        manifest: PrivateTreeMember,
        acl: WindowsPrivateDirectoryAcl,
        *,
        manifest_name: str,
    ) -> None:
        acl.validate(descriptor)
        before = os.fstat(descriptor)
        self.require_simple_metadata(before, directory=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or metadata_identity(before) != manifest.identity
            or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
        ):
            raise ValueError(f"{self.label} expiry manifest changed")
        size, digest = consume_file(
            DescriptorReader(descriptor),
            max_bytes=manifest.identity[3],
            chunk_size=self.read_chunk_size,
            size_error=lambda: ValueError(f"{self.label} expiry manifest changed"),
        )
        after = os.fstat(descriptor)
        visible = windows_stat_at(parent_fd, manifest_name)
        if (
            size != manifest.identity[3]
            or digest != manifest.content_sha256
            or metadata_identity(after) != manifest.identity
            or metadata_identity(visible) != manifest.identity
        ):
            raise ValueError(f"{self.label} expiry manifest changed")

    def capture_archive_manifest(
        self,
        archive_fd: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        manifest_name: str,
        maximum_bytes: int,
        expected_manifest: Callable[[], bytes],
        project: Callable[[MetadataIdentity, str], _ProjectionT],
    ) -> _ProjectionT:
        with closing_descriptor(
            open_windows_regular_file_at(
                archive_fd,
                manifest_name,
                create_new=False,
                write=False,
                read_control=True,
            )
        ) as descriptor:
            acl.validate(descriptor)
            before = os.fstat(descriptor)
            self.require_simple_metadata(before, directory=False)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > maximum_bytes
                or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            ):
                raise ValueError(f"{self.label} archive manifest is unsafe")
            raw = read_bounded_prefix(descriptor, maximum_bytes, chunk_size=65536)
            after = os.fstat(descriptor)
            visible = windows_stat_at(archive_fd, manifest_name)
            self.require_same_metadata(after, before, directory=False)
            self.require_same_metadata(visible, before, directory=False)
            expected = expected_manifest()
            if (
                raw != expected
                or len(raw) != before.st_size
                or metadata_identity(after) != metadata_identity(before)
                or metadata_identity(visible) != metadata_identity(before)
                or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            ):
                raise ValueError(f"{self.label} archive manifest changed")
            return project(metadata_identity(before), sha256(raw).hexdigest())
