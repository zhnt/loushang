"""Private-tree metadata policy over the existing native and observation ports."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal

from loushang.harness.journal._io_loops import write_all
from loushang.harness.resources.packages._file_consumption import closing_descriptor

from ._file_consumption import DescriptorReader, FileConsumptionError, consume_file
from ._tree_observation import (
    ExpectedTreeFile,
    MetadataIdentity,
    PrivateTreeMember,
    PrivateTreeSnapshot,
    TreeDirectoryReadPort,
    TreeDirectoryUnavailable,
    TreeEntryObservation,
    TreeFileReadPort,
    TreeObservationError,
    collect_tree,
    metadata_identity,
)
from .plugin_lifecycle.posix_materialization import (
    _entry_exists,
    _open_directory,
    _open_regular_file,
    _rename_directory_noreplace,
)


@dataclass(frozen=True)
class ObservedPrivateMember:
    relative_path: str
    kind: Literal["directory", "file"]
    identity: MetadataIdentity
    content_sha256: str | None


@dataclass(frozen=True)
class _File:
    byte_count: int
    content_digest: str


@dataclass(frozen=True)
class _Reader:
    descriptor: int
    metadata: dict[str, os.stat_result]
    label: str
    expected: dict[str, PrivateTreeMember] | None = None
    prefix: tuple[str, ...] = ()

    def identity(self) -> tuple[int, int]:
        value = os.fstat(self.descriptor)
        return value.st_dev, value.st_ino

    @contextmanager
    def entries(self) -> Iterator[Iterator[TreeEntryObservation]]:
        with os.scandir(self.descriptor) as entries:
            ordered = list(entries)
            native_order = {entry.name: index for index, entry in enumerate(ordered)}
            directories: list[os.DirEntry[str]] = []
            files: list[os.DirEntry[str]] = []
            for item in ordered:
                try:
                    (directories if item.is_dir() else files).append(item)
                except OSError:
                    try:
                        if item.is_symlink():
                            files.append(item)
                    except OSError:
                        pass
            if self.expected is None:
                ordered = sorted(directories + files, key=lambda item: item.name)
            else:
                ordered = directories + files

            def observe() -> Iterator[TreeEntryObservation]:
                for entry in ordered:
                    value = os.stat(
                        entry.name, dir_fd=self.descriptor, follow_symlinks=False
                    )
                    path = "/".join((*self.prefix, entry.name))
                    directory = stat.S_ISDIR(value.st_mode)
                    if self.expected is not None:
                        target = self.expected.get(path)
                        if target is None:
                            raise ValueError(
                                f"{self.label} backup has an unexpected member"
                            )
                        if (
                            (target.kind == "directory") != directory
                            or (
                                not directory
                                and (
                                    not stat.S_ISREG(value.st_mode)
                                    or value.st_nlink != 1
                                )
                            )
                            or value.st_uid != os.geteuid()
                            or value.st_mode & 0o077
                        ):
                            raise ValueError(
                                f"{self.label} backup {target.kind} changed"
                            )
                    elif not directory and (
                        not stat.S_ISREG(value.st_mode) or value.st_nlink != 1
                    ):
                        raise ValueError(f"{self.label} private-data member is unsafe")
                    self.metadata[path] = value
                    yield TreeEntryObservation(
                        entry.name,
                        "directory" if directory else "file",
                        (value.st_dev, value.st_ino),
                        value.st_nlink,
                        value.st_size,
                        native_order[entry.name],
                    )

            yield observe()

    @contextmanager
    def open_directory(self, name: str) -> Iterator[TreeDirectoryReadPort]:
        try:
            descriptor = _open_directory(name, dir_fd=self.descriptor)
        except OSError as error:
            raise TreeDirectoryUnavailable() from error
        try:
            yield _Reader(
                descriptor,
                self.metadata,
                self.label,
                self.expected,
                (*self.prefix, name),
            )
        finally:
            os.close(descriptor)

    @contextmanager
    def file_reader(self, name: str) -> Iterator[TreeFileReadPort]:
        descriptor = _open_regular_file(
            self.descriptor, name, create_new=False, write=False
        )
        expected = self.metadata["/".join((*self.prefix, name))]
        try:
            if metadata_identity(os.fstat(descriptor)) != metadata_identity(expected):
                self._changed("open")
            yield _PrivateFileReader(descriptor, expected, self)
            if self.expected is None and metadata_identity(
                os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
            ) != metadata_identity(expected):
                self._changed("read")
        finally:
            os.close(descriptor)

    def _changed(self, when: str) -> None:
        if self.expected is None:
            raise ValueError(f"{self.label} private-data member changed")
        raise ValueError(f"{self.label} backup file changed during {when}")


@dataclass(frozen=True)
class _PrivateFileReader:
    descriptor: int
    expected: os.stat_result
    owner: _Reader

    def read(self, max_bytes: int) -> bytes:
        return os.read(self.descriptor, max_bytes)

    def identity_and_links(self) -> tuple[tuple[int, int], int]:
        current = os.fstat(self.descriptor)
        if metadata_identity(current) != metadata_identity(self.expected):
            self.owner._changed("read")
        return (current.st_dev, current.st_ino), current.st_nlink


def capture_private_tree(
    root: Path,
    *,
    private_base: Path,
    label: str,
    max_entries: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> tuple[MetadataIdentity | None, tuple[ObservedPrivateMember, ...]]:
    base = private_base.absolute()
    relative = root.absolute().relative_to(base)
    current = base
    try:
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise ValueError(f"{label} private-data root is unsafe")
        for part in relative.parts:
            current /= part
            value = current.lstat()
            if (
                not stat.S_ISDIR(value.st_mode)
                or value.st_uid != os.geteuid()
                or value.st_mode & 0o077
            ):
                raise ValueError(f"{label} private-data root is unsafe")
    except FileNotFoundError:
        return None, ()
    with closing_descriptor(_open_directory(root)) as descriptor:
        identity = metadata_identity(os.fstat(descriptor))
        if identity != metadata_identity(root.lstat()):
            raise ValueError(f"{label} private-data root changed")
        metadata: dict[str, os.stat_result] = {}
        try:
            observed, _, _ = collect_tree(
                _Reader(descriptor, metadata, label),
                None,
                directory_identities=None,
                file_identities=None,
                allow_empty=True,
                max_entries=max_entries,
                max_file_bytes=max_file_bytes,
                max_total_bytes=max_total_bytes,
                defer_directory_reads=True,
            )
        except TreeObservationError as error:
            if error.code in {"entry_limit", "byte_limit"}:
                raise ValueError(f"{label} private-data preview is too large") from None
            raise ValueError(f"{label} private-data member changed") from None
        for path, value in metadata.items():
            if stat.S_ISREG(value.st_mode) and observed[path][0] != value.st_size:
                raise ValueError(f"{label} private-data member changed")
        if identity != metadata_identity(root.lstat()):
            raise ValueError(f"{label} private-data root changed")
        members = tuple(
            ObservedPrivateMember(
                path,
                "directory" if stat.S_ISDIR(value.st_mode) else "file",
                metadata_identity(value),
                None if stat.S_ISDIR(value.st_mode) else observed[path][1],
            )
            for path, value in sorted(metadata.items())
        )
        return identity, members


def verify_private_tree(
    root_fd: int,
    members: Sequence[PrivateTreeMember],
    *,
    label: str,
    max_read_bytes: int,
) -> None:
    expected = {item.relative_path: item for item in members}
    files: dict[str, ExpectedTreeFile] = {
        path: _File(item.identity[3], item.content_sha256 or "")
        for path, item in expected.items()
        if item.kind == "file"
    }
    metadata: dict[str, os.stat_result] = {}
    try:
        observed, _, _ = collect_tree(
            _Reader(root_fd, metadata, label, expected),
            files,
            directory_identities=None,
            file_identities=None,
            allow_empty=True,
            explicit_directories={
                item.relative_path for item in members if item.kind == "directory"
            },
            max_file_bytes=max_read_bytes,
            verify_contents=True,
            defer_directory_reads=True,
        )
    except TreeObservationError as error:
        reason = {
            "file_size_exceeded": "file grew",
            "file_size_changed": "file size changed",
            "content_changed": "content changed",
            "byte_limit": "file exceeds its limit",
            "directory_identity": "directory changed",
            "file_identity": "file changed during read",
            "unexpected_directory": "has an unexpected member",
            "unexpected_file": "has an unexpected member",
        }.get(error.code, "file changed")
        raise ValueError(f"{label} backup {reason}") from None
    if set(metadata) != set(expected):
        raise ValueError(f"{label} backup is incomplete")


def read_private_bytes(
    descriptor: int,
    maximum: int,
    *,
    label: str,
    max_read_bytes: int,
    exact_size: int | None = None,
) -> bytes:
    if maximum < 0 or maximum > max_read_bytes:
        raise ValueError(f"{label} backup file exceeds its limit")
    output = BytesIO()
    try:
        size, _ = consume_file(
            DescriptorReader(descriptor),
            max_bytes=maximum,
            destination=output,
            chunk_size=min(1024 * 1024, maximum + 1),
            hash_content=False,
        )
    except FileConsumptionError:
        raise ValueError(f"{label} backup file grew") from None
    if exact_size is not None and size != exact_size:
        raise ValueError(f"{label} backup file size changed")
    return output.getvalue()


def write_or_verify_private_file(
    parent_fd: int,
    name: str,
    content: bytes,
    *,
    label: str,
    max_read_bytes: int,
) -> None:
    resumed = False
    try:
        descriptor = _open_regular_file(parent_fd, name, create_new=True, write=True)
    except FileExistsError:
        resumed = True
        descriptor = _open_regular_file(
            parent_fd,
            name,
            create_new=False,
            write=True,
            read_write=True,
        )
    try:
        offset = 0
        if resumed:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or before.st_mode & 0o077
            ):
                raise ValueError(f"{label} backup file is unsafe")
            prefix = read_private_bytes(
                descriptor, len(content), label=label, max_read_bytes=max_read_bytes
            )
            if prefix != content[: len(prefix)]:
                raise ValueError(f"{label} backup existing content changed")
            if metadata_identity(os.fstat(descriptor)) != metadata_identity(before):
                raise ValueError(f"{label} backup file changed during read")
            offset = len(prefix)
        write_all(
            lambda view: os.write(descriptor, view),
            memoryview(content)[offset:],
            message=f"{label} backup write made no progress",
        )
        os.fsync(descriptor)
        if resumed:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if (
                read_private_bytes(
                    descriptor,
                    len(content),
                    label=label,
                    exact_size=len(content),
                    max_read_bytes=max_read_bytes,
                )
                != content
            ):
                raise ValueError(f"{label} backup file changed during write")
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class PrivatePosixTreeIO:
    """Native private-data operations; caller retains Product and record authority."""

    label: str
    max_read_bytes: int

    def require_private(self, descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
            raise ValueError(f"{self.label} backup directory is not private")

    def open_directory(self, parent_fd: int, name: str) -> int:
        descriptor = _open_directory(name, dir_fd=parent_fd)
        try:
            self.require_private(descriptor)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def mkdir(self, parent_fd: int, name: str) -> None:
        with suppress(FileExistsError):
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        os.close(self.open_directory(parent_fd, name))

    def open_chain(self, root_fd: int, parts: list[str], *, create: bool) -> int:
        descriptor = os.dup(root_fd)
        try:
            for part in parts:
                if create:
                    self.mkdir(descriptor, part)
                child = self.open_directory(descriptor, part)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def open_path(self, private_base: Path, path: Path) -> int:
        base = private_base.absolute()
        parts = path.absolute().relative_to(base).parts
        with closing_descriptor(_open_directory(base)) as descriptor:
            self.require_private(descriptor)
            return self.open_chain(descriptor, list(parts), create=False)

    def open_member_parent(
        self,
        root_fd: int,
        parts: list[str],
        expected: dict[str, PrivateTreeMember],
        *,
        private_permissions: bool,
        error_context: str,
    ) -> int:
        descriptor = os.dup(root_fd)
        path = ""
        try:
            for part in parts:
                path = part if not path else path + "/" + part
                child = (
                    self.open_directory(descriptor, part)
                    if private_permissions
                    else _open_directory(part, dir_fd=descriptor)
                )
                try:
                    item = expected[path]
                    if (
                        item.kind != "directory"
                        or metadata_identity(os.fstat(child))[:3] != item.identity[:3]
                    ):
                        raise ValueError(
                            f"{self.label} {error_context} directory changed"
                        )
                except BaseException:
                    os.close(child)
                    raise
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def read_bytes(
        self, descriptor: int, maximum: int, *, exact_size: int | None = None
    ) -> bytes:
        return read_private_bytes(
            descriptor,
            maximum,
            exact_size=exact_size,
            label=self.label,
            max_read_bytes=self.max_read_bytes,
        )

    def write_file(self, parent_fd: int, name: str, content: bytes) -> None:
        write_or_verify_private_file(
            parent_fd,
            name,
            content,
            label=self.label,
            max_read_bytes=self.max_read_bytes,
        )

    def read_manifest_bytes(
        self, parent_fd: int, name: str, manifest_name: str, maximum: int
    ) -> bytes:
        with closing_descriptor(self.open_directory(parent_fd, name)) as archive_fd:
            with closing_descriptor(
                _open_regular_file(
                    archive_fd, manifest_name, create_new=False, write=False
                )
            ) as descriptor:
                metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_nlink != 1
                    or metadata.st_uid != os.geteuid()
                    or metadata.st_mode & 0o077
                ):
                    raise ValueError(f"{self.label} backup manifest is unsafe")
                return self.read_bytes(descriptor, maximum)

    def copy_members(
        self,
        source_root: Path,
        root_identity: MetadataIdentity | None,
        members: Sequence[PrivateTreeMember],
        destination_fd: int,
        *,
        private_base: Path,
        write_file: Callable[[int, str, bytes], None],
    ) -> None:
        with closing_descriptor(self.open_path(private_base, source_root)) as source_fd:
            if metadata_identity(os.fstat(source_fd)) != root_identity:
                raise ValueError(f"{self.label} backup source root changed")
            expected = {item.relative_path: item for item in members}
            for item in members:
                parts = item.relative_path.split("/")
                if item.kind == "directory":
                    with closing_descriptor(
                        self.open_chain(destination_fd, parts[:-1], create=True)
                    ) as parent_fd:
                        self.mkdir(parent_fd, parts[-1])
                        os.fsync(parent_fd)
                    continue
                with closing_descriptor(
                    self.open_member_parent(
                        source_fd,
                        parts[:-1],
                        expected,
                        private_permissions=True,
                        error_context="backup source",
                    )
                ) as parent_fd:
                    with closing_descriptor(
                        self.open_chain(destination_fd, parts[:-1], create=False)
                    ) as target_fd:
                        with closing_descriptor(
                            _open_regular_file(
                                parent_fd, parts[-1], create_new=False, write=False
                            )
                        ) as descriptor:
                            if metadata_identity(os.fstat(descriptor)) != item.identity:
                                raise ValueError(
                                    f"{self.label} backup source file changed"
                                )
                            output = BytesIO()
                            if not 0 <= item.identity[3] <= self.max_read_bytes:
                                raise ValueError(
                                    f"{self.label} backup file exceeds its limit"
                                )
                            try:
                                count, digest = consume_file(
                                    DescriptorReader(descriptor),
                                    destination=output,
                                    max_bytes=item.identity[3],
                                    chunk_size=1024 * 1024,
                                )
                            except FileConsumptionError:
                                raise ValueError(
                                    f"{self.label} backup file grew"
                                ) from None
                            if count != item.identity[3]:
                                raise ValueError(
                                    f"{self.label} backup file size changed"
                                )
                            if digest != item.content_sha256:
                                raise ValueError(
                                    f"{self.label} backup source content changed"
                                )
                            if metadata_identity(os.fstat(descriptor)) != item.identity:
                                raise ValueError(
                                    f"{self.label} backup source file changed"
                                )
                        write_file(target_fd, parts[-1], output.getvalue())
                        os.fsync(target_fd)

    def restore_verified_tree(
        self,
        private_base: Path,
        target: Path,
        members: Sequence[PrivateTreeMember],
        files_fd: int,
        *,
        stage_name: str,
        stage_prefix: str,
        stage_suffix: str,
        write_file: Callable[[int, str, bytes], None],
    ) -> str:
        with closing_descriptor(
            self.open_path(private_base, target.parent)
        ) as parent_fd:
            if self.inspect_restore_target(
                parent_fd,
                target.name,
                stage_name=stage_name,
                stage_prefix=stage_prefix,
                stage_suffix=stage_suffix,
            ):
                with closing_descriptor(
                    self.open_directory(parent_fd, target.name)
                ) as existing_fd:
                    verify_private_tree(
                        existing_fd,
                        members,
                        label=self.label,
                        max_read_bytes=self.max_read_bytes,
                    )
                return "already_present"
            self.mkdir(parent_fd, stage_name)
            with closing_descriptor(
                self.open_directory(parent_fd, stage_name)
            ) as stage_fd:
                for item in members:
                    parts = item.relative_path.split("/")
                    with closing_descriptor(
                        self.open_chain(stage_fd, parts[:-1], create=True)
                    ) as destination_parent:
                        if item.kind == "directory":
                            self.mkdir(destination_parent, parts[-1])
                        else:
                            with closing_descriptor(
                                self.open_chain(files_fd, parts[:-1], create=False)
                            ) as archive_parent:
                                with closing_descriptor(
                                    _open_regular_file(
                                        archive_parent,
                                        parts[-1],
                                        create_new=False,
                                        write=False,
                                    )
                                ) as file_fd:
                                    content = self.read_bytes(
                                        file_fd,
                                        item.identity[3],
                                        exact_size=item.identity[3],
                                    )
                            if sha256(content).hexdigest() != item.content_sha256:
                                raise ValueError(
                                    f"{self.label} restore content changed"
                                )
                            write_file(destination_parent, parts[-1], content)
                        os.fsync(destination_parent)
                verify_private_tree(
                    stage_fd,
                    members,
                    label=self.label,
                    max_read_bytes=self.max_read_bytes,
                )
                os.fsync(stage_fd)
                visible_stage = os.stat(
                    stage_name, dir_fd=parent_fd, follow_symlinks=False
                )
                opened_stage = os.fstat(stage_fd)
                visible_parent = target.parent.lstat()
                opened_parent = os.fstat(parent_fd)
                if (
                    not stat.S_ISDIR(visible_stage.st_mode)
                    or (visible_stage.st_dev, visible_stage.st_ino)
                    != (opened_stage.st_dev, opened_stage.st_ino)
                    or (visible_parent.st_dev, visible_parent.st_ino)
                    != (opened_parent.st_dev, opened_parent.st_ino)
                ):
                    raise ValueError(f"{self.label} restore stage or parent changed")
                _rename_directory_noreplace(
                    parent_fd, stage_name, parent_fd, target.name
                )
                published = os.stat(
                    target.name, dir_fd=parent_fd, follow_symlinks=False
                )
                if (published.st_dev, published.st_ino) != (
                    os.fstat(stage_fd).st_dev,
                    os.fstat(stage_fd).st_ino,
                ):
                    raise ValueError(f"{self.label} restored root changed")
                os.fsync(parent_fd)
            with closing_descriptor(
                self.open_directory(parent_fd, target.name)
            ) as restored_fd:
                verify_private_tree(
                    restored_fd,
                    members,
                    label=self.label,
                    max_read_bytes=self.max_read_bytes,
                )
            return "restored"

    def preflight_restore_target(
        self,
        private_base: Path,
        target: Path,
        members: Sequence[PrivateTreeMember],
        *,
        stage_name: str,
        stage_prefix: str,
        stage_suffix: str,
    ) -> bool:
        with closing_descriptor(
            self.open_path(private_base, target.parent)
        ) as parent_fd:
            if self.inspect_restore_target(
                parent_fd,
                target.name,
                stage_name=stage_name,
                stage_prefix=stage_prefix,
                stage_suffix=stage_suffix,
            ):
                with closing_descriptor(
                    self.open_path(private_base, target)
                ) as target_fd:
                    verify_private_tree(
                        target_fd,
                        members,
                        label=self.label,
                        max_read_bytes=self.max_read_bytes,
                    )
                return True
            return False

    def inspect_restore_target(
        self,
        parent_fd: int,
        target_name: str,
        *,
        stage_name: str,
        stage_prefix: str,
        stage_suffix: str,
    ) -> bool:
        if any(
            name.startswith(stage_prefix)
            and name.endswith(stage_suffix)
            and name != stage_name
            for name in os.listdir(parent_fd)
        ):
            raise ValueError(f"{self.label} restore has foreign staging debt")
        if _entry_exists(parent_fd, target_name):
            if _entry_exists(parent_fd, stage_name):
                raise ValueError(f"{self.label} restore has unsettled staging debt")
            return True
        return False

    def require_no_foreign_restore_stage(
        self,
        private_base: Path,
        target: Path,
        *,
        stage_name: str,
        stage_prefix: str,
        stage_suffix: str,
        target_present: bool,
    ) -> None:
        try:
            parent_fd = self.open_path(private_base, target.parent)
        except FileNotFoundError:
            return
        try:
            for name in os.listdir(parent_fd):
                if not (name.startswith(stage_prefix) and name.endswith(stage_suffix)):
                    continue
                if name != stage_name:
                    raise ValueError(f"{self.label} restore has foreign staging debt")
                if target_present:
                    raise ValueError(f"{self.label} restore has unsettled staging debt")
        finally:
            os.close(parent_fd)

    def remove_members(
        self,
        tombstone_fd: int,
        members: Sequence[PrivateTreeMember],
        original: PrivateTreeSnapshot,
    ) -> None:
        expected = {member.relative_path: member for member in original.members}
        for member in sorted(
            members,
            key=lambda item: (item.relative_path.count("/"), item.relative_path),
            reverse=True,
        ):
            parts = member.relative_path.split("/")
            with closing_descriptor(
                self.open_member_parent(
                    tombstone_fd,
                    parts[:-1],
                    expected,
                    private_permissions=False,
                    error_context="private-data",
                )
            ) as parent_fd:
                metadata = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                if member.kind == "file":
                    if metadata_identity(metadata) != member.identity:
                        raise ValueError(f"{self.label} private-data file changed")
                    os.unlink(parts[-1], dir_fd=parent_fd)
                else:
                    if metadata_identity(metadata)[:3] != member.identity[:3]:
                        raise ValueError(f"{self.label} private-data directory changed")
                    os.rmdir(parts[-1], dir_fd=parent_fd)
                os.fsync(parent_fd)
