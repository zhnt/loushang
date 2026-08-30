from __future__ import annotations

import errno
import io
import os
import shutil
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import BinaryIO, Literal, cast

from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.types import (
    PluginSource,
    ResolvedPluginPackage,
    VerifiedPluginRevision,
)

_TREE_DIGEST_FORMAT = b"loushang.plugin-tree/v1\0"
_IGNORED_ROOT_ENTRIES = frozenset({".git"})
_FROZEN_DIRECTORY_MODE = 0o500
_FROZEN_FILE_MODE = 0o400
_FROZEN_EXECUTABLE_MODE = 0o500
_STAGING_DIRECTORY_MODE = 0o700
_WINDOWS_REPARSE_POINT_ATTRIBUTE = 0x400


class PluginRevisionError(RuntimeError):
    """Structured failure at the immutable Plugin revision boundary."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True)
class _RevisionEntry:
    kind: str
    digest: str | None = None
    size: int | None = None
    executable: bool = False


class VerifiedRevisionHandle:
    """Lease one verified revision root and provide checked relative file opens."""

    def __init__(
        self,
        *,
        root: Path,
        content_digest: str,
        entries: dict[str, _RevisionEntry],
    ) -> None:
        self.root = root.resolve()
        self.content_digest = content_digest
        self._entries = MappingProxyType(dict(entries))
        self._descriptor_backed = _supports_descriptor_relative_revision_io()
        self._closed = False
        if self._descriptor_backed:
            self._root_fd: int | None = _open_directory(self.root)
            self._root_identity = _stat_identity(os.fstat(self._root_fd))
        else:
            self._root_fd = None
            self._root_identity = _stat_identity(
                _portable_directory_metadata(self.root)
            )

    @property
    def closed(self) -> bool:
        return self._closed

    def verify(self) -> None:
        self._require_open()
        try:
            if self._descriptor_backed:
                root_fd = self._require_root_fd()
                current_fd = _open_directory(self.root)
                try:
                    current_identity = _stat_identity(os.fstat(current_fd))
                finally:
                    os.close(current_fd)
                entries = _capture_tree(root_fd)
            else:
                current_identity = _stat_identity(
                    _portable_directory_metadata(self.root)
                )
                entries = _capture_tree_portable(self.root)
            if current_identity != self._root_identity:
                raise OSError(
                    errno.ESTALE,
                    "Plugin revision publication path identity changed",
                    self.root,
                )
        except Exception as exc:
            raise PluginRevisionError(
                f"Plugin revision could not be verified: {self.root}: {exc}",
                code="plugin_revision_changed",
                path=self.root,
            ) from exc
        digest = _tree_digest(entries)
        if digest != self.content_digest or entries != self._entries:
            raise PluginRevisionError(
                f"Plugin revision content changed after publication: {self.root}",
                code="plugin_revision_changed",
                path=self.root,
            )

    def open_file(self, relative_path: str | PurePosixPath) -> BinaryIO:
        logical_path = _logical_relative_path(relative_path, root=self.root)
        key = logical_path.as_posix()
        expected = self._entries.get(key)
        if expected is None or expected.kind != "file" or expected.digest is None:
            raise PluginRevisionError(
                f"Plugin revision file is not declared by the verified tree: {key}",
                code="invalid_plugin_revision_path",
                path=self.root / logical_path,
            )
        try:
            if self._descriptor_backed:
                data, executable = _read_relative_file(
                    self._require_root_fd(),
                    logical_path,
                )
            else:
                self._require_open()
                data, executable = _read_relative_file_portable(
                    self.root,
                    logical_path,
                    expected_root_identity=self._root_identity,
                )
        except (OSError, PluginRevisionError) as exc:
            raise PluginRevisionError(
                f"Plugin revision file changed after publication: {key}",
                code="plugin_revision_changed",
                path=self.root / logical_path,
            ) from exc
        if (
            sha256(data).hexdigest() != expected.digest
            or executable != expected.executable
        ):
            raise PluginRevisionError(
                f"Plugin revision file changed after publication: {key}",
                code="plugin_revision_changed",
                path=self.root / logical_path,
            )
        return io.BytesIO(data)

    def entry_kind(
        self,
        relative_path: str | PurePosixPath,
    ) -> Literal["file", "directory"]:
        self._require_open()
        logical_path = _logical_relative_path(relative_path, root=self.root)
        expected = self._entries.get(logical_path.as_posix())
        if expected is None or expected.kind not in {"file", "directory"}:
            raise PluginRevisionError(
                "Plugin revision entry is not declared by the verified tree: "
                f"{logical_path}",
                code="invalid_plugin_revision_path",
                path=self.root / logical_path,
            )
        return cast(Literal["file", "directory"], expected.kind)

    def file_identity(
        self,
        relative_path: str | PurePosixPath,
    ) -> tuple[str, int]:
        """Return immutable body identity without reopening package bytes."""

        self._require_open()
        logical_path = _logical_relative_path(relative_path, root=self.root)
        expected = self._entries.get(logical_path.as_posix())
        if (
            expected is None
            or expected.kind != "file"
            or expected.digest is None
            or expected.size is None
        ):
            raise PluginRevisionError(
                "Plugin revision file is not declared by the verified tree: "
                f"{logical_path}",
                code="invalid_plugin_revision_path",
                path=self.root / logical_path,
            )
        return expected.digest, expected.size

    def acquire(self) -> VerifiedRevisionHandle:
        """Acquire an independently disposable lease over the same revision."""

        self.verify()
        root_fd: int | None = None
        if self._descriptor_backed:
            try:
                root_fd = os.dup(self._require_root_fd())
            except OSError as exc:
                raise PluginRevisionError(
                    f"Plugin revision lease could not be acquired: {self.root}: {exc}",
                    code="plugin_revision_changed",
                    path=self.root,
                ) from exc
        handle = object.__new__(VerifiedRevisionHandle)
        handle.root = self.root
        handle.content_digest = self.content_digest
        handle._entries = MappingProxyType(dict(self._entries))
        handle._root_fd = root_fd
        handle._root_identity = self._root_identity
        handle._descriptor_backed = self._descriptor_backed
        handle._closed = False
        return handle

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        root_fd = self._root_fd
        self._root_fd = None
        if root_fd is not None:
            os.close(root_fd)

    def __enter__(self) -> VerifiedRevisionHandle:
        self._require_root_fd()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def _require_root_fd(self) -> int:
        self._require_open()
        if not self._descriptor_backed or self._root_fd is None:
            raise RuntimeError("Portable Plugin revision has no directory fd")
        return self._root_fd

    def _require_open(self) -> None:
        if self._closed:
            raise PluginRevisionError(
                f"Plugin revision handle is closed: {self.root}",
                code="plugin_revision_handle_closed",
                path=self.root,
            )


class PluginRevisionStore:
    """Publish verified Plugin package snapshots under their complete tree digest."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.revision_root = self.root / "sha256"

    def publish(self, package: ResolvedPluginPackage) -> VerifiedPluginRevision:
        PluginManifestParser().revalidate(package)
        self.revision_root.mkdir(parents=True, exist_ok=True)
        quarantine = Path(
            tempfile.mkdtemp(prefix=".quarantine-", dir=self.revision_root)
        )
        published_by_this_call = False
        published_root: Path | None = None
        try:
            if _supports_descriptor_relative_revision_io():
                source_fd = _open_directory(package.root)
                try:
                    entries = _capture_tree(source_fd, destination=quarantine)
                finally:
                    os.close(source_fd)
            else:
                entries = _capture_tree_portable(
                    package.root,
                    destination=quarantine,
                )
            PluginManifestParser().revalidate(package)
            content_digest = _tree_digest(entries)
            published_root = self.revision_root / content_digest
            # Darwin rejects renaming a directory after its owner-write bit has
            # been removed. Freeze every child before publication, but retain a
            # writable staging root until the atomic rename completes.
            _freeze_tree(quarantine, root_mode=_STAGING_DIRECTORY_MODE)
            try:
                quarantine.rename(published_root)
            except OSError as exc:
                collision = exc.errno in {errno.EEXIST, errno.ENOTEMPTY} or (
                    exc.errno in {errno.EACCES, errno.EPERM}
                    and published_root.exists()
                )
                if not collision:
                    raise
                _remove_tree(quarantine)
            else:
                published_by_this_call = True
                published_root.chmod(_FROZEN_DIRECTORY_MODE)
            handle = VerifiedRevisionHandle(
                root=published_root,
                content_digest=content_digest,
                entries=entries,
            )
            try:
                handle.verify()
                return _project_verified_revision(
                    package,
                    published_root=published_root,
                    content_digest=content_digest,
                    handle=handle,
                )
            except Exception:
                handle.close()
                raise
        except PluginRevisionError as exc:
            if published_by_this_call and published_root is not None:
                _remove_tree(published_root)
            else:
                _remove_tree(quarantine)
            if exc.path.is_absolute():
                raise
            raise PluginRevisionError(
                str(exc),
                code=exc.code,
                path=package.root / exc.path,
            ) from exc
        except Exception as exc:
            if published_by_this_call and published_root is not None:
                _remove_tree(published_root)
            else:
                _remove_tree(quarantine)
            raise PluginRevisionError(
                f"Plugin revision could not be published: {package.root}: {exc}",
                code="plugin_revision_publish_failed",
                path=package.root,
            ) from exc

    def publish_all(
        self,
        packages: tuple[ResolvedPluginPackage, ...],
    ) -> tuple[VerifiedPluginRevision, ...]:
        published: list[VerifiedPluginRevision] = []
        try:
            for package in packages:
                published.append(self.publish(package))
        except Exception:
            for package in published:
                package.revision_handle.close()
            raise
        return tuple(published)

    def reopen(
        self,
        content_digest: str,
        *,
        source: PluginSource,
    ) -> VerifiedPluginRevision:
        """Reopen one exact immutable revision without consulting mutable source.

        Durable Product desired state carries the content digest while the
        binding lock carries the original source descriptor.  Reconstructing
        from both facts keeps replay independent of the mutable checkout and
        preserves the source identity used by selection and Approval evidence.
        """

        if not _is_sha256_digest(content_digest):
            raise ValueError("Plugin revision digest must be lowercase SHA-256")
        if not isinstance(source, PluginSource):
            raise TypeError("Plugin revision source descriptor is required")
        published_root = self.revision_root / content_digest
        try:
            if _supports_descriptor_relative_revision_io():
                root_fd = _open_directory(published_root)
                try:
                    entries = _capture_tree(root_fd)
                finally:
                    os.close(root_fd)
            else:
                entries = _capture_tree_portable(published_root)
        except Exception as exc:
            raise PluginRevisionError(
                f"Plugin revision could not be reopened: {published_root}: {exc}",
                code="plugin_revision_unavailable",
                path=published_root,
            ) from exc
        if _tree_digest(entries) != content_digest:
            raise PluginRevisionError(
                f"Plugin revision content changed after publication: {published_root}",
                code="plugin_revision_changed",
                path=published_root,
            )
        try:
            package = PluginManifestParser().parse(published_root)
            package = replace(package, source=source)
            handle = VerifiedRevisionHandle(
                root=published_root,
                content_digest=content_digest,
                entries=entries,
            )
            try:
                handle.verify()
                return _project_verified_revision(
                    package,
                    published_root=published_root,
                    content_digest=content_digest,
                    handle=handle,
                )
            except Exception:
                handle.close()
                raise
        except PluginRevisionError:
            raise
        except Exception as exc:
            raise PluginRevisionError(
                f"Plugin revision could not be reconstructed: {published_root}: {exc}",
                code="plugin_revision_replay_failed",
                path=published_root,
            ) from exc


def _supports_descriptor_relative_revision_io() -> bool:
    """Return whether the host exposes the complete POSIX-style safe-open set."""

    supports_dir_fd = getattr(os, "supports_dir_fd", ())
    supports_follow_symlinks = getattr(os, "supports_follow_symlinks", ())
    supports_fd = getattr(os, "supports_fd", ())
    return (
        isinstance(getattr(os, "O_DIRECTORY", None), int)
        and isinstance(getattr(os, "O_NOFOLLOW", None), int)
        and os.open in supports_dir_fd
        and os.stat in supports_dir_fd
        and os.stat in supports_follow_symlinks
        and os.listdir in supports_fd
    )


def _is_sha256_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _capture_tree_portable(
    root: Path,
    *,
    destination: Path | None = None,
) -> dict[str, _RevisionEntry]:
    """Capture on hosts without directory-fd traversal, rejecting reparse points."""

    entries: dict[str, _RevisionEntry] = {}
    _capture_directory_portable(
        root,
        relative=PurePosixPath(),
        destination=destination,
        entries=entries,
    )
    return entries


def _capture_directory_portable(
    directory: Path,
    *,
    relative: PurePosixPath,
    destination: Path | None,
    entries: dict[str, _RevisionEntry],
) -> None:
    directory_before = _portable_directory_metadata(directory)
    try:
        names = sorted(os.listdir(directory), key=os.fsencode)
    except OSError as exc:
        raise PluginRevisionError(
            f"Plugin revision directory could not be listed: {relative}: {exc}",
            code="plugin_revision_changed",
            path=Path(relative.as_posix()),
        ) from exc
    for name in names:
        if not relative.parts and name in _IGNORED_ROOT_ENTRIES:
            continue
        logical_path = relative / name
        key = logical_path.as_posix()
        source_path = directory / name
        metadata = _portable_entry_metadata(source_path, logical_path=logical_path)
        destination_path = (
            destination / Path(*logical_path.parts) if destination else None
        )
        if stat.S_ISDIR(metadata.st_mode):
            entries[key] = _RevisionEntry(kind="directory")
            if destination_path is not None:
                destination_path.mkdir()
            _capture_directory_portable(
                source_path,
                relative=logical_path,
                destination=destination,
                entries=entries,
            )
            continue
        file_digest, executable = _digest_file_portable(
            source_path,
            expected=metadata,
            destination=destination_path,
        )
        entries[key] = _RevisionEntry(
            kind="file",
            digest=file_digest,
            size=metadata.st_size,
            executable=executable,
        )
        if destination_path is not None:
            destination_path.chmod(
                _FROZEN_EXECUTABLE_MODE if executable else _FROZEN_FILE_MODE
            )
    directory_after = _portable_directory_metadata(directory)
    if _stable_directory_identity(directory_before) != _stable_directory_identity(
        directory_after
    ):
        raise PluginRevisionError(
            f"Plugin revision directory changed while scanned: {relative}",
            code="plugin_revision_changed",
            path=Path(relative.as_posix()),
        )


def _read_relative_file_portable(
    root: Path,
    relative_path: PurePosixPath,
    *,
    expected_root_identity: tuple[int, int],
) -> tuple[bytes, bool]:
    root_metadata = _portable_directory_metadata(root)
    if _stat_identity(root_metadata) != expected_root_identity:
        raise OSError(
            errno.ESTALE,
            "Plugin revision publication path identity changed",
            root,
        )
    directory_chain: list[tuple[Path, os.stat_result]] = [(root, root_metadata)]
    current = root
    for part in relative_path.parts[:-1]:
        current /= part
        directory_chain.append((current, _portable_directory_metadata(current)))
    file_path = current / relative_path.parts[-1]
    metadata = _portable_entry_metadata(file_path, logical_path=relative_path)
    if not stat.S_ISREG(metadata.st_mode):
        raise PluginRevisionError(
            f"Plugin revision path is not a regular file: {relative_path}",
            code="plugin_revision_changed",
            path=Path(relative_path.as_posix()),
        )
    result = _read_file_portable(file_path, expected=metadata)
    for path, before in reversed(directory_chain):
        after = _portable_directory_metadata(path)
        if _stable_directory_identity(before) != _stable_directory_identity(after):
            raise OSError(
                errno.ESTALE,
                "Plugin revision directory changed while file was read",
                path,
            )
    return result


def _read_file_portable(
    path: Path,
    *,
    expected: os.stat_result,
) -> tuple[bytes, bool]:
    file_fd, before = _open_regular_file_portable(path, expected=expected)
    try:
        chunks: list[bytes] = []
        while chunk := os.read(file_fd, 1024 * 1024):
            chunks.append(chunk)
        _assert_file_stable(file_fd, before, name=str(path))
        _assert_portable_path_stable(path, expected=expected)
        return b"".join(chunks), bool(before.st_mode & 0o111)
    finally:
        os.close(file_fd)


def _digest_file_portable(
    path: Path,
    *,
    expected: os.stat_result,
    destination: Path | None,
) -> tuple[str, bool]:
    file_fd, before = _open_regular_file_portable(path, expected=expected)
    destination_fd: int | None = None
    try:
        if destination is not None:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
            destination_fd = os.open(destination, flags, 0o600)
        digest = sha256()
        while chunk := os.read(file_fd, 1024 * 1024):
            digest.update(chunk)
            if destination_fd is not None:
                _write_all(destination_fd, chunk)
        _assert_file_stable(file_fd, before, name=str(path))
        _assert_portable_path_stable(path, expected=expected)
        return digest.hexdigest(), bool(before.st_mode & 0o111)
    finally:
        os.close(file_fd)
        if destination_fd is not None:
            os.close(destination_fd)


def _open_regular_file_portable(
    path: Path,
    *,
    expected: os.stat_result,
) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOINHERIT", 0)
    file_fd = os.open(path, flags)
    try:
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or _stat_identity(before) != _stat_identity(
            expected
        ):
            raise OSError(
                errno.ESTALE,
                "Plugin revision file identity changed",
                path,
            )
        return file_fd, before
    except Exception:
        os.close(file_fd)
        raise


def _assert_portable_path_stable(path: Path, *, expected: os.stat_result) -> None:
    after = _portable_entry_metadata(path, logical_path=PurePosixPath(path.name))
    if _stable_file_identity(expected) != _stable_file_identity(after):
        raise OSError(errno.ESTALE, "Plugin revision file path changed", path)


def _portable_directory_metadata(path: Path) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise PluginRevisionError(
            f"Plugin revision directory could not be inspected: {path}: {exc}",
            code="plugin_revision_changed",
            path=path,
        ) from exc
    if _is_reparse_point(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise PluginRevisionError(
            f"Plugin revision contains an unsafe directory: {path}",
            code="unsafe_plugin_revision_entry",
            path=path,
        )
    return metadata


def _portable_entry_metadata(
    path: Path,
    *,
    logical_path: PurePosixPath,
) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise PluginRevisionError(
            f"Plugin revision entry could not be inspected: {logical_path}: {exc}",
            code="plugin_revision_changed",
            path=Path(logical_path.as_posix()),
        ) from exc
    if _is_reparse_point(metadata) or not (
        stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
    ):
        raise PluginRevisionError(
            f"Plugin revision contains an unsafe entry: {logical_path}",
            code="unsafe_plugin_revision_entry",
            path=Path(logical_path.as_posix()),
        )
    return metadata


def _is_reparse_point(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & _WINDOWS_REPARSE_POINT_ATTRIBUTE
    )


def _capture_tree(
    root_fd: int,
    *,
    destination: Path | None = None,
) -> dict[str, _RevisionEntry]:
    entries: dict[str, _RevisionEntry] = {}
    _capture_directory(
        root_fd,
        relative=PurePosixPath(),
        destination=destination,
        entries=entries,
    )
    return entries


def _capture_directory(
    directory_fd: int,
    *,
    relative: PurePosixPath,
    destination: Path | None,
    entries: dict[str, _RevisionEntry],
) -> None:
    try:
        directory_before = os.fstat(directory_fd)
        names = sorted(os.listdir(directory_fd), key=os.fsencode)
    except OSError as exc:
        raise PluginRevisionError(
            f"Plugin revision directory could not be listed: {relative}: {exc}",
            code="plugin_revision_changed",
            path=Path(relative.as_posix()),
        ) from exc
    for name in names:
        if not relative.parts and name in _IGNORED_ROOT_ENTRIES:
            continue
        logical_path = relative / name
        key = logical_path.as_posix()
        try:
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise PluginRevisionError(
                f"Plugin revision entry could not be inspected: {key}: {exc}",
                code="plugin_revision_changed",
                path=Path(key),
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not (
            stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
        ):
            raise PluginRevisionError(
                f"Plugin revision contains an unsafe entry: {key}",
                code="unsafe_plugin_revision_entry",
                path=Path(key),
            )
        destination_path = (
            destination / Path(*logical_path.parts) if destination else None
        )
        if stat.S_ISDIR(metadata.st_mode):
            entries[key] = _RevisionEntry(kind="directory")
            if destination_path is not None:
                destination_path.mkdir()
            child_fd = _open_directory(name, dir_fd=directory_fd)
            try:
                _capture_directory(
                    child_fd,
                    relative=logical_path,
                    destination=destination,
                    entries=entries,
                )
            finally:
                os.close(child_fd)
            continue
        file_digest, executable = _digest_file(
            directory_fd,
            name,
            expected=metadata,
            destination=destination_path,
        )
        entries[key] = _RevisionEntry(
            kind="file",
            digest=file_digest,
            size=metadata.st_size,
            executable=executable,
        )
        if destination_path is not None:
            destination_path.chmod(
                _FROZEN_EXECUTABLE_MODE if executable else _FROZEN_FILE_MODE
            )
    try:
        directory_after = os.fstat(directory_fd)
    except OSError as exc:
        raise PluginRevisionError(
            f"Plugin revision directory could not be rechecked: {relative}: {exc}",
            code="plugin_revision_changed",
            path=Path(relative.as_posix()),
        ) from exc
    if _stable_directory_identity(directory_before) != _stable_directory_identity(
        directory_after
    ):
        raise PluginRevisionError(
            f"Plugin revision directory changed while scanned: {relative}",
            code="plugin_revision_changed",
            path=Path(relative.as_posix()),
        )


def _read_relative_file(
    root_fd: int,
    relative_path: PurePosixPath,
) -> tuple[bytes, bool]:
    current_fd = os.dup(root_fd)
    try:
        for part in relative_path.parts[:-1]:
            child_fd = _open_directory(part, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = child_fd
        name = relative_path.parts[-1]
        metadata = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            raise PluginRevisionError(
                f"Plugin revision path is not a regular file: {relative_path}",
                code="plugin_revision_changed",
                path=Path(relative_path.as_posix()),
            )
        return _read_file(current_fd, name, expected=metadata)
    finally:
        os.close(current_fd)


def _read_file(
    directory_fd: int,
    name: str,
    *,
    expected: os.stat_result,
) -> tuple[bytes, bool]:
    file_fd, before = _open_regular_file(directory_fd, name, expected=expected)
    try:
        chunks: list[bytes] = []
        while chunk := os.read(file_fd, 1024 * 1024):
            chunks.append(chunk)
        _assert_file_stable(file_fd, before, name=name)
        return b"".join(chunks), bool(before.st_mode & 0o111)
    finally:
        os.close(file_fd)


def _digest_file(
    directory_fd: int,
    name: str,
    *,
    expected: os.stat_result,
    destination: Path | None,
) -> tuple[str, bool]:
    file_fd, before = _open_regular_file(directory_fd, name, expected=expected)
    destination_fd: int | None = None
    try:
        if destination is not None:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= _required_open_flag("O_NOFOLLOW") | getattr(os, "O_CLOEXEC", 0)
            destination_fd = os.open(destination, flags, 0o600)
        digest = sha256()
        while chunk := os.read(file_fd, 1024 * 1024):
            digest.update(chunk)
            if destination_fd is not None:
                _write_all(destination_fd, chunk)
        _assert_file_stable(file_fd, before, name=name)
        return digest.hexdigest(), bool(before.st_mode & 0o111)
    finally:
        os.close(file_fd)
        if destination_fd is not None:
            os.close(destination_fd)


def _open_regular_file(
    directory_fd: int,
    name: str,
    *,
    expected: os.stat_result,
) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY | _required_open_flag("O_NOFOLLOW")
    flags |= getattr(os, "O_CLOEXEC", 0)
    file_fd = os.open(name, flags, dir_fd=directory_fd)
    try:
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or _stat_identity(before) != _stat_identity(
            expected
        ):
            raise OSError(errno.ESTALE, "Plugin revision file identity changed", name)
        return file_fd, before
    except Exception:
        os.close(file_fd)
        raise


def _assert_file_stable(
    file_fd: int,
    before: os.stat_result,
    *,
    name: str,
) -> None:
    after = os.fstat(file_fd)
    if _stable_file_identity(before) != _stable_file_identity(after):
        raise OSError(errno.ESTALE, "Plugin revision file changed while read", name)


def _write_all(file_fd: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(file_fd, remaining)
        if written <= 0:
            raise OSError(errno.EIO, "Plugin revision snapshot write made no progress")
        remaining = remaining[written:]


def _open_directory(path: str | Path, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | _required_open_flag("O_DIRECTORY")
    flags |= _required_open_flag("O_NOFOLLOW") | getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(path, flags, dir_fd=dir_fd)
    except (NotImplementedError, TypeError) as exc:
        raise PluginRevisionError(
            f"Platform cannot open a no-follow Plugin revision directory: {path}: {exc}",
            code="plugin_revision_platform_unsupported",
            path=Path(path),
        ) from exc


def _required_open_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int):
        raise PluginRevisionError(
            f"Platform does not provide required {name} support.",
            code="plugin_revision_platform_unsupported",
            path=Path(),
        )
    return value


def _tree_digest(entries: dict[str, _RevisionEntry]) -> str:
    digest = sha256(_TREE_DIGEST_FORMAT)
    for path, entry in sorted(entries.items()):
        encoded_path = os.fsencode(path)
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(b"d" if entry.kind == "directory" else b"f")
        digest.update(b"x" if entry.executable else b"-")
        if entry.digest is not None:
            digest.update(bytes.fromhex(entry.digest))
    return digest.hexdigest()


def _project_verified_revision(
    package: ResolvedPluginPackage,
    *,
    published_root: Path,
    content_digest: str,
    handle: VerifiedRevisionHandle,
) -> VerifiedPluginRevision:
    package_root = published_root / package.package_root_relative
    manifest_path = (
        published_root / package.manifest_path.relative_to(package.root)
        if package.manifest_path is not None
        else None
    )
    manifest = replace(
        package.manifest,
        root=published_root,
        package_root=package_root,
    )
    return VerifiedPluginRevision(
        root=published_root,
        package_root=package_root,
        manifest=manifest,
        source=package.source,
        manifest_path=manifest_path,
        manifest_digest=package.manifest_digest,
        package_root_relative=package.package_root_relative,
        root_identity=_path_identity(published_root),
        package_root_identity=_path_identity(package_root),
        contribution_index=package.contribution_index,
        content_digest=content_digest,
        revision_handle=handle,
    )


def _logical_relative_path(
    value: str | PurePosixPath,
    *,
    root: Path,
) -> PurePosixPath:
    try:
        return canonical_plugin_relative_path(value)
    except ValueError as exc:
        raise PluginRevisionError(
            f"Plugin revision path must be a contained relative path: {value}",
            code="invalid_plugin_revision_path",
            path=root,
        ) from exc


def _stat_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _stable_file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _stable_directory_identity(
    value: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _path_identity(path: Path) -> tuple[int, int] | None:
    try:
        metadata = path.stat()
    except OSError:
        return None
    return metadata.st_dev, metadata.st_ino


def _freeze_tree(root: Path, *, root_mode: int = _FROZEN_DIRECTORY_MODE) -> None:
    for current_root, directories, files in os.walk(root, topdown=False):
        current = Path(current_root)
        for filename in files:
            path = current / filename
            executable = bool(path.stat().st_mode & 0o111)
            path.chmod(_FROZEN_EXECUTABLE_MODE if executable else _FROZEN_FILE_MODE)
        for directory in directories:
            (current / directory).chmod(_FROZEN_DIRECTORY_MODE)
    root.chmod(root_mode)


def _remove_tree(root: Path) -> None:
    if not root.exists():
        return
    for current_root, directories, files in os.walk(root):
        current = Path(current_root)
        current.chmod(0o700)
        for filename in files:
            (current / filename).chmod(0o600)
        for directory in directories:
            (current / directory).chmod(0o700)
    shutil.rmtree(root)


__all__ = [
    "PluginRevisionError",
    "PluginRevisionStore",
    "VerifiedRevisionHandle",
]
