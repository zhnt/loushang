"""POSIX rooted snapshot I/O for publication, verification and pre-fence registration."""

from __future__ import annotations

import ctypes
import errno
import json
import os
import stat
import sys
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast

from loushang.harness.journal._io_loops import write_all as _complete_write
from loushang.harness.resources.packages._file_consumption import closing_descriptor
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.snapshot_records import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
    PackageOfflineRestoreError,
    PackageOfflineRestoreSnapshotEvidenceV1,
)

if os.name == "posix":
    import fcntl as _fcntl
else:  # pragma: no cover - imported by Windows collection only
    _fcntl = None  # type: ignore[assignment]

PACKAGE_POSIX_OFFLINE_RESTORE_TREE_MANIFEST_VERSION = 1

PACKAGE_POSIX_OFFLINE_RESTORE_STATE_MANIFEST_VERSION = 1

DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_ENTRIES = 100_000

DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_BYTES = 16 * 1024 * 1024 * 1024

DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_DEPTH = 128

_PAYLOAD_NAME = "payload"

_STATE_MANIFEST_NAME = "state-manifest.json"

_MAX_STATE_MANIFEST_BYTES = 1024 * 1024

_NativeIdentity = tuple[int, int]

_EntryKind = Literal["directory", "file"]


@dataclass(frozen=True, slots=True)
class _TreeEntry:
    logical_path: str
    kind: _EntryKind
    mode: int
    content_digest: str | None = None
    byte_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        if self.kind == "directory":
            return {
                "kind": self.kind,
                "logicalPath": self.logical_path,
                "mode": self.mode,
            }
        return {
            "byteCount": self.byte_count,
            "contentDigest": self.content_digest,
            "kind": self.kind,
            "logicalPath": self.logical_path,
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class _TreeInspection:
    entries: tuple[_TreeEntry, ...]
    identities: dict[tuple[str, ...], _NativeIdentity]
    tree_digest: str
    entry_count: int
    byte_count: int


@dataclass(slots=True)
class _ValidatedSnapshot:
    bundle_fd: int
    payload_fd: int
    inspection: _TreeInspection

    def close(self) -> None:
        with suppress(OSError):
            os.close(self.payload_fd)
        with suppress(OSError):
            os.close(self.bundle_fd)


class _PinnedRoot:
    def __init__(
        self,
        *,
        path: Path,
        components: tuple[str, ...],
        descriptors: list[int],
        identities: tuple[_NativeIdentity, ...],
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
        expected_identities: tuple[_NativeIdentity, ...] | None = None,
    ) -> _PinnedRoot:
        descriptors: list[int] = []
        components = path.parts[1:]
        try:
            current = _open_directory("/")
            descriptors.append(current)
            for component in components:
                current = _open_directory_at(current, component)
                descriptors.append(current)
            identities = tuple(_native_identity(os.fstat(fd)) for fd in descriptors)
            if expected_identities is not None and identities != expected_identities:
                raise OSError("Configured authority identity changed")
            _require_private_directory(descriptors[-1])
            result = cls(
                path=path,
                components=components,
                descriptors=descriptors,
                identities=identities,
            )
            result.assert_visible()
            return result
        except Exception:
            for descriptor in reversed(descriptors):
                with suppress(OSError):
                    os.close(descriptor)
            raise

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise RuntimeError("Pinned POSIX authority is closed")
        return self._descriptors[-1]

    @property
    def root_identity(self) -> _NativeIdentity:
        return self.identities[-1]

    def assert_visible(self) -> None:
        if self._closed:
            raise OSError("Pinned POSIX authority is closed")
        for descriptor, expected in zip(
            self._descriptors,
            self.identities,
            strict=True,
        ):
            if _native_identity(os.fstat(descriptor)) != expected:
                raise OSError("Pinned POSIX ancestor identity changed")
        _require_private_directory(self.descriptor)
        visible = _open_directory("/")
        try:
            if _native_identity(os.fstat(visible)) != self.identities[0]:
                raise OSError("POSIX filesystem root identity changed")
            for component, expected in zip(
                self.components,
                self.identities[1:],
                strict=True,
            ):
                child = _open_directory_at(visible, component)
                os.close(visible)
                visible = child
                if _native_identity(os.fstat(visible)) != expected:
                    raise OSError("POSIX authority ancestor identity changed")
        finally:
            os.close(visible)

    def close(self) -> None:
        if self._closed:
            return
        for descriptor in reversed(self._descriptors):
            with suppress(OSError):
                os.close(descriptor)
        self._descriptors.clear()
        self._closed = True


def _validated_snapshot_bundle(
    source_root: _PinnedRoot,
    snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
    *,
    maximum_depth: int,
) -> _ValidatedSnapshot:
    bundle_fd: int | None = None
    payload_fd: int | None = None
    try:
        bundle_fd = _open_directory_at(
            source_root.descriptor,
            snapshot.snapshot.snapshot_id,
        )
        if set(os.listdir(bundle_fd)) != {_PAYLOAD_NAME, _STATE_MANIFEST_NAME}:
            raise OSError("Snapshot bundle membership changed")
        payload_fd = _open_directory_at(bundle_fd, _PAYLOAD_NAME)
        inspection = _inspect_tree(
            payload_fd,
            maximum_entries=snapshot.snapshot.entry_count,
            maximum_bytes=snapshot.snapshot.byte_count,
            maximum_depth=maximum_depth,
        )
        if (
            inspection.tree_digest != snapshot.snapshot_tree_digest
            or inspection.entry_count != snapshot.snapshot.entry_count
            or inspection.byte_count != snapshot.snapshot.byte_count
        ):
            raise OSError("Snapshot payload identity changed")
        manifest_bytes, _identity = _read_regular_file(
            bundle_fd,
            _STATE_MANIFEST_NAME,
            maximum_bytes=_MAX_STATE_MANIFEST_BYTES,
        )
        if sha256(manifest_bytes).hexdigest() != snapshot.state_manifest_digest:
            raise OSError("Snapshot state manifest digest changed")
        expected_manifest = _expected_state_manifest(snapshot)
        if (
            manifest_bytes != canonical_json_bytes(expected_manifest)
            or _strict_json_object(manifest_bytes, name="snapshot state manifest")
            != expected_manifest
        ):
            raise OSError("Snapshot state manifest changed")
        return _ValidatedSnapshot(
            bundle_fd=bundle_fd,
            payload_fd=payload_fd,
            inspection=inspection,
        )
    except Exception as exc:
        if payload_fd is not None:
            os.close(payload_fd)
        if bundle_fd is not None:
            os.close(bundle_fd)
        raise PackageOfflineRestoreError(
            "Authenticated Package snapshot bundle is invalid",
            code="package_offline_restore_snapshot_invalid",
            evidence_ref=snapshot.evidence_id,
        ) from exc


def _revalidate_source(
    source: _ValidatedSnapshot,
    snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
    *,
    maximum_depth: int,
) -> None:
    try:
        if set(os.listdir(source.bundle_fd)) != {_PAYLOAD_NAME, _STATE_MANIFEST_NAME}:
            raise OSError("Snapshot bundle membership changed")
        observed = _inspect_tree(
            source.payload_fd,
            maximum_entries=snapshot.snapshot.entry_count,
            maximum_bytes=snapshot.snapshot.byte_count,
            maximum_depth=maximum_depth,
        )
        if observed.entries != source.inspection.entries:
            raise OSError("Snapshot tree changed during restore")
        manifest, _identity = _read_regular_file(
            source.bundle_fd,
            _STATE_MANIFEST_NAME,
            maximum_bytes=_MAX_STATE_MANIFEST_BYTES,
        )
        if sha256(manifest).hexdigest() != snapshot.state_manifest_digest:
            raise OSError("Snapshot state manifest changed during restore")
    except PackageOfflineRestoreError:
        raise
    except Exception as exc:
        raise PackageOfflineRestoreError(
            "Authenticated Package snapshot changed during restore",
            code="package_offline_restore_snapshot_invalid",
            evidence_ref=snapshot.evidence_id,
        ) from exc


def _inspect_tree(
    root_fd: int,
    *,
    maximum_entries: int,
    maximum_bytes: int,
    maximum_depth: int,
    top_level_names: frozenset[str] | None = None,
) -> _TreeInspection:
    entries: list[_TreeEntry] = []
    identities: dict[tuple[str, ...], _NativeIdentity] = {}
    total_bytes = 0

    def visit(directory_fd: int, prefix: tuple[str, ...]) -> None:
        nonlocal total_bytes
        names = sorted(os.listdir(directory_fd))
        if not prefix and top_level_names is not None:
            if not top_level_names.issubset(names):
                raise OSError("Snapshot selected source member is missing")
            names = sorted(top_level_names)
        for name in names:
            _validate_entry_name(name)
            metadata = os.stat(
                name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            parts = prefix + (name,)
            if len(parts) > maximum_depth:
                raise OSError("Snapshot tree depth exceeds configured budget")
            logical_path = "/".join(parts)
            if len(entries) >= maximum_entries:
                raise OSError("Snapshot entry count exceeds receipt")
            if stat.S_ISDIR(metadata.st_mode):
                with closing_descriptor(
                    _open_directory_at(directory_fd, name)
                ) as child:
                    identity = _native_identity(os.fstat(child))
                    if identity != _native_identity(metadata):
                        raise OSError("Snapshot directory identity changed")
                    entries.append(
                        _TreeEntry(
                            logical_path=logical_path,
                            kind="directory",
                            mode=stat.S_IMODE(metadata.st_mode),
                        )
                    )
                    identities[parts] = identity
                    visit(child, parts)
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                with closing_descriptor(
                    _open_regular_file(directory_fd, name, write=False)
                ) as descriptor:
                    opened_before = os.fstat(descriptor)
                    if (
                        _native_identity(opened_before) != _native_identity(metadata)
                        or opened_before.st_nlink != 1
                    ):
                        raise OSError("Snapshot file identity changed")
                    digest = sha256()
                    file_bytes = 0
                    while chunk := os.read(descriptor, 64 * 1024):
                        file_bytes += len(chunk)
                        total_bytes += len(chunk)
                        if total_bytes > maximum_bytes:
                            raise OSError("Snapshot byte count exceeds receipt")
                        digest.update(chunk)
                    opened_after = os.fstat(descriptor)
                    if _stable_file_metadata(opened_before) != _stable_file_metadata(
                        opened_after
                    ):
                        raise OSError("Snapshot file changed while reading")
                    entries.append(
                        _TreeEntry(
                            logical_path=logical_path,
                            kind="file",
                            mode=stat.S_IMODE(metadata.st_mode),
                            content_digest=digest.hexdigest(),
                            byte_count=file_bytes,
                        )
                    )
                    identities[parts] = _native_identity(opened_after)
            else:
                raise OSError("Snapshot contains an aliased or special member")

    visit(root_fd, ())
    ordered_entries = tuple(sorted(entries, key=lambda entry: entry.logical_path))
    manifest = {
        "entries": [entry.to_dict() for entry in ordered_entries],
        "manifestVersion": PACKAGE_POSIX_OFFLINE_RESTORE_TREE_MANIFEST_VERSION,
    }
    return _TreeInspection(
        entries=ordered_entries,
        identities=identities,
        tree_digest=sha256(canonical_json_bytes(manifest)).hexdigest(),
        entry_count=len(entries),
        byte_count=total_bytes,
    )


def _copy_tree(
    source_fd: int,
    target_fd: int,
    inspection: _TreeInspection,
) -> None:
    for entry in inspection.entries:
        parts = tuple(entry.logical_path.split("/"))
        with closing_descriptor(
            _open_relative_directory(target_fd, parts[:-1])
        ) as target_parent:
            if entry.kind == "directory":
                os.mkdir(parts[-1], mode=0o700, dir_fd=target_parent)
                continue
            with closing_descriptor(
                _open_relative_directory(source_fd, parts[:-1])
            ) as source_parent:
                source_file = _open_regular_file(
                    source_parent,
                    parts[-1],
                    write=False,
                )
            try:
                with closing_descriptor(
                    _open_regular_file(
                        target_parent,
                        parts[-1],
                        create_new=True,
                        write=True,
                    )
                ) as target_file:
                    source_before = os.fstat(source_file)
                    if (
                        _native_identity(source_before) != inspection.identities[parts]
                        or source_before.st_nlink != 1
                    ):
                        raise OSError("Snapshot file identity changed before copy")
                    digest = sha256()
                    byte_count = 0
                    while chunk := os.read(source_file, 64 * 1024):
                        _write_all(target_file, chunk)
                        digest.update(chunk)
                        byte_count += len(chunk)
                        if (
                            entry.byte_count is not None
                            and byte_count > entry.byte_count
                        ):
                            raise OSError("Snapshot file grew during copy")
                    source_after = os.fstat(source_file)
                    if _stable_file_metadata(source_before) != _stable_file_metadata(
                        source_after
                    ):
                        raise OSError("Snapshot file changed during copy")
                    if (
                        byte_count != entry.byte_count
                        or digest.hexdigest() != entry.content_digest
                    ):
                        raise OSError("Snapshot file content changed during copy")
                    os.fchmod(target_file, entry.mode)
                    os.fsync(target_file)
            finally:
                os.close(source_file)
    for entry in reversed(inspection.entries):
        if entry.kind != "directory":
            continue
        with closing_descriptor(
            _open_relative_directory(
                target_fd,
                tuple(entry.logical_path.split("/")),
            )
        ) as descriptor:
            os.fchmod(descriptor, entry.mode)


def _fsync_tree(root_fd: int, entries: tuple[_TreeEntry, ...]) -> None:
    directories = [
        tuple(entry.logical_path.split("/"))
        for entry in entries
        if entry.kind == "directory"
    ]
    for parts in sorted(
        directories, key=lambda value: (len(value), value), reverse=True
    ):
        with closing_descriptor(_open_relative_directory(root_fd, parts)) as descriptor:
            os.fsync(descriptor)


def _remove_owned_namespace(
    root_fd: int,
    name: str,
    *,
    expected_identity: _NativeIdentity,
) -> None:
    with closing_descriptor(_open_directory_at(root_fd, name)) as namespace:
        if _native_identity(os.fstat(namespace)) != expected_identity:
            raise OSError("Owned staging namespace identity changed")
        _remove_directory_contents(namespace)
        if os.listdir(namespace):
            raise OSError("Owned staging namespace is not empty")
    _assert_entry_identity(
        root_fd,
        name,
        expected_identity,
        expected_kind="directory",
    )
    os.rmdir(name, dir_fd=root_fd)


def _remove_directory_contents(directory_fd: int) -> None:
    for name in sorted(os.listdir(directory_fd)):
        _validate_entry_name(name)
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        identity = _native_identity(metadata)
        if stat.S_ISDIR(metadata.st_mode):
            with closing_descriptor(_open_directory_at(directory_fd, name)) as child:
                if _native_identity(os.fstat(child)) != identity:
                    raise OSError("Owned staging directory identity changed")
                _remove_directory_contents(child)
            _assert_entry_identity(
                directory_fd,
                name,
                identity,
                expected_kind="directory",
            )
            os.rmdir(name, dir_fd=directory_fd)
        elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
            _assert_entry_identity(
                directory_fd,
                name,
                identity,
                expected_kind="file",
            )
            os.unlink(name, dir_fd=directory_fd)
        else:
            raise OSError("Owned staging namespace contains an unsafe entry")


def _expected_state_manifest(
    snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
) -> dict[str, object]:
    receipt = snapshot.snapshot
    return {
        "byteCount": receipt.byte_count,
        "coveredDomains": list(PACKAGE_PRE_B_SNAPSHOT_DOMAINS),
        "entryCount": receipt.entry_count,
        "legacyRootIdentity": receipt.legacy_root_identity,
        "manifestVersion": PACKAGE_POSIX_OFFLINE_RESTORE_STATE_MANIFEST_VERSION,
        "snapshotId": receipt.snapshot_id,
        "snapshotReceiptId": receipt.receipt_id,
        "snapshotRevision": receipt.snapshot_revision,
        "storeId": receipt.store_id,
        "treeDigest": snapshot.snapshot_tree_digest,
    }


def _read_regular_file(
    directory_fd: int,
    name: str,
    *,
    maximum_bytes: int,
) -> tuple[bytes, _NativeIdentity]:
    with closing_descriptor(
        _open_regular_file(directory_fd, name, write=False)
    ) as descriptor:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError("Expected one regular file")
        contents = bytearray()
        while chunk := os.read(descriptor, 64 * 1024):
            contents.extend(chunk)
            if len(contents) > maximum_bytes:
                raise OSError("Bounded metadata file is too large")
        after = os.fstat(descriptor)
        if _stable_file_metadata(before) != _stable_file_metadata(after):
            raise OSError("Metadata file changed while reading")
        return bytes(contents), _native_identity(after)


def _write_new_file(directory_fd: int, name: str, contents: bytes) -> None:
    with closing_descriptor(
        _open_regular_file(
            directory_fd,
            name,
            create_new=True,
            write=True,
        )
    ) as descriptor:
        _write_all(descriptor, contents)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)


def _write_all(descriptor: int, contents: bytes) -> None:
    _complete_write(
        lambda view: os.write(descriptor, view),
        contents,
        message="Restore write made no progress",
    )


def _strict_json_object(payload: bytes, *, name: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{name} contains a duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{name} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return cast(dict[str, object], value)


def _validated_root_path(value: str | Path, *, name: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise TypeError(f"Package {name} root must be a filesystem path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        raise PackageOfflineRestoreError(
            f"Package {name} root must be absolute and normalized",
            code="package_offline_restore_materialization_invalid",
        )
    return path


def _validated_limit(value: int, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Package {name} must be a non-negative integer")
    return value


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _pinned_roots_overlap(left: _PinnedRoot, right: _PinnedRoot) -> bool:
    return (
        left.root_identity in right.identities or right.root_identity in left.identities
    )


def _validate_entry_name(name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise OSError("Snapshot entry name is invalid")
    name.encode("utf-8")


def _open_directory(path: str | Path) -> int:
    return os.open(path, _directory_open_flags())


def _open_directory_at(parent_fd: int, name: str) -> int:
    descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise OSError("Expected a rooted directory")
    return descriptor


def _open_regular_file(
    directory_fd: int,
    name: str,
    *,
    create_new: bool = False,
    write: bool,
) -> int:
    flags = (os.O_WRONLY if write else os.O_RDONLY) | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    if create_new:
        flags |= os.O_CREAT | os.O_EXCL
    return os.open(name, flags, 0o600, dir_fd=directory_fd)


def _open_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            child = _open_directory_at(current, part)
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def _entry_exists(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _native_identity(metadata: os.stat_result) -> _NativeIdentity:
    return metadata.st_dev, metadata.st_ino


def _directory_identity(descriptor: int) -> str:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise OSError("Restored Package root is not a directory")
    return sha256(
        canonical_json_bytes(
            {
                "device": metadata.st_dev,
                "fileType": "directory",
                "identityVersion": 1,
                "inode": metadata.st_ino,
            }
        )
    ).hexdigest()


def _stable_file_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _assert_entry_identity(
    directory_fd: int,
    name: str,
    expected: _NativeIdentity,
    *,
    expected_kind: _EntryKind,
) -> None:
    metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if _native_identity(metadata) != expected:
        raise OSError("Owned restore entry identity changed")
    if expected_kind == "directory" and not stat.S_ISDIR(metadata.st_mode):
        raise OSError("Owned restore directory type changed")
    if expected_kind == "file" and (
        not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
    ):
        raise OSError("Owned restore file type changed")


def _require_private_directory(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise OSError("Package authority root is not private")


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _supports_posix_rooted_io() -> bool:
    return bool(
        _fcntl is not None
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
        and os.listdir in os.supports_fd
        and _noreplace_rename_function() is not None
    )


_RenameAt = Any


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
    return function, flag


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


__all__: tuple[str, ...] = ()
