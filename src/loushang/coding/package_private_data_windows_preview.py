"""Read-only Windows Product preview of one Coding Arch private-data root.

This owner admits the current Arch shape: an Installation `sessions` directory,
hashed Session directories, and direct cache files. Other shapes need their own
Product admission before backup or deletion can consume them. Named data streams
on files and directories are refused; other Windows data dimensions and native
verification still need admission before this observation can authorize deletion.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_directory_stream_names,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
)
from .package_private_data_deletion_preview import (
    _MAX_ENTRIES,
    _MAX_FILE_BYTES,
    _MAX_TOTAL_BYTES,
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
    _identity,
)

_SESSION_NAME = re.compile(r"[0-9a-f]{64}\Z")
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_SIMPLE_FILE_ATTRIBUTES = 0x00000020 | 0x00000080 | 0x00002000
_SIMPLE_DIRECTORY_ATTRIBUTES = _FILE_ATTRIBUTE_DIRECTORY | 0x00000020 | 0x00002000


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataReadPreview:
    """Observe one exact Installation without creating or deleting its data."""

    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        if not isinstance(
            self.layout, CodingPluginLifecycleStateLayout
        ) or not isinstance(self.product, WindowsLocalWheelProductSessionOwner):
            raise ValueError(
                "Windows Coding Arch private-data Product owner is not bound"
            )
        epoch = resolve_coding_package_epoch_layout(self.layout)
        if (
            self.product.policy.product_id != "coding"
            or self.product.policy.project_scope_id != self.layout.scope_id
            or self.product.epoch_runtime.registry.store_id != epoch.store_id
            or self.product.epoch_runtime.control_root != epoch.control_root
            or self.product.epoch_runtime.selected_store_root().parent
            != epoch.epochs_root
        ):
            raise ValueError(
                "Windows Coding Arch private-data Product owner is not bound"
            )

    def snapshot_for(
        self, key: PluginInstallationKeyV1
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        root = coding_arch_installation_private_data_root(self.layout, key)
        state_root = (
            resolve_coding_package_epoch_layout(self.layout).control_root
            / "product-state"
        )
        with self._offline():
            expected = inspect_coding_windows_arch_installation_root(
                self.layout, key, state_root=state_root
            )
            if expected is None:
                return CodingArchPrivateDataTargetSnapshotV1(
                    root_path_digest=sha256(os.fsencode(str(root))).hexdigest(),
                    root_identity=None,
                    members=(),
                )
            snapshot = _capture_windows_target_snapshot(root, expected_root=expected)
            if (
                inspect_coding_windows_arch_installation_root(
                    self.layout, key, state_root=state_root
                )
                != expected
            ):
                raise ValueError("Windows Coding Arch private-data root changed")
            return snapshot

    @contextmanager
    def _offline(self) -> Iterator[None]:
        registry = self.product.epoch_runtime.registry
        with registry.exclusive_runtime_quiescence(
            store_id=registry.store_id
        ) as quiescence:
            if quiescence.active_runtime_lease_ids:
                raise ValueError(
                    "Windows Coding Arch private-data Product runtime is active"
                )
            self.product.assert_private_data_read_authority_current()
            with self.product.gc_gate.read_guard():
                yield
            self.product.assert_private_data_read_authority_current()


def _capture_windows_target_snapshot(
    root: Path, *, expected_root: tuple[int, int]
) -> CodingArchPrivateDataTargetSnapshotV1:
    with (
        WindowsPrivateDirectoryAcl() as exact_acl,
        WindowsPrivateDirectoryAcl(inherit_children=True) as session_acl,
    ):
        root_fd = open_windows_directory(root, share_delete=False, read_control=True)
        try:
            exact_acl.validate(root_fd)
            _require_no_named_directory_streams(root_fd)
            root_metadata = os.fstat(root_fd)
            _require_simple_windows_metadata(root_metadata, directory=True)
            if (root_metadata.st_dev, root_metadata.st_ino) != expected_root:
                raise ValueError("Windows Coding Arch private-data root changed")
            members: list[CodingArchPrivateDataMemberV1] = []
            total_bytes = 0
            root_names = windows_listdir_at(root_fd)
            if any(name != "sessions" for name in root_names):
                raise ValueError(
                    "Windows Coding Arch private-data member is unsupported"
                )
            if root_names:
                sessions_fd, sessions_metadata = _open_directory_child(
                    root_fd, "sessions", exact_acl
                )
                try:
                    _append_member(
                        members,
                        CodingArchPrivateDataMemberV1(
                            "sessions", "directory", _identity(sessions_metadata)
                        ),
                    )
                    for session_name in sorted(windows_listdir_at(sessions_fd)):
                        if _SESSION_NAME.fullmatch(session_name) is None:
                            raise ValueError(
                                "Windows Coding Arch private-data Session is invalid"
                            )
                        session_fd, session_metadata = _open_directory_child(
                            sessions_fd, session_name, session_acl
                        )
                        try:
                            session_path = "sessions/" + session_name
                            _append_member(
                                members,
                                CodingArchPrivateDataMemberV1(
                                    session_path,
                                    "directory",
                                    _identity(session_metadata),
                                ),
                            )
                            for file_name in sorted(windows_listdir_at(session_fd)):
                                member, byte_count = _read_cache_file(
                                    session_fd,
                                    file_name,
                                    session_path,
                                    session_acl,
                                )
                                total_bytes += byte_count
                                if total_bytes > _MAX_TOTAL_BYTES:
                                    raise ValueError(
                                        "Windows Coding Arch private-data preview is too large"
                                    )
                                _append_member(members, member)
                            _require_directory_unchanged(
                                sessions_fd, session_name, session_fd, session_metadata
                            )
                        finally:
                            os.close(session_fd)
                    _require_directory_unchanged(
                        root_fd, "sessions", sessions_fd, sessions_metadata
                    )
                finally:
                    os.close(sessions_fd)
            _require_no_named_directory_streams(root_fd)
            current_root = os.fstat(root_fd)
            current_path = root.lstat()
            _require_same_windows_metadata(current_root, root_metadata, directory=True)
            _require_same_windows_metadata(current_path, root_metadata, directory=True)
            if _identity(current_root) != _identity(root_metadata) or _identity(
                current_path
            ) != _identity(root_metadata):
                raise ValueError("Windows Coding Arch private-data root changed")
            return CodingArchPrivateDataTargetSnapshotV1(
                root_path_digest=sha256(os.fsencode(str(root))).hexdigest(),
                root_identity=_identity(root_metadata),
                members=tuple(sorted(members, key=lambda item: item.relative_path)),
            )
        finally:
            os.close(root_fd)


def _open_directory_child(
    parent_fd: int, name: str, acl: WindowsPrivateDirectoryAcl
) -> tuple[int, os.stat_result]:
    metadata = windows_stat_at(parent_fd, name)
    descriptor = open_windows_directory(
        name, dir_fd=parent_fd, share_delete=False, read_control=True
    )
    try:
        acl.validate(descriptor)
        _require_no_named_directory_streams(descriptor)
        _require_same_windows_metadata(os.fstat(descriptor), metadata, directory=True)
        if _identity(os.fstat(descriptor)) != _identity(metadata):
            raise ValueError("Windows Coding Arch private-data directory changed")
        return descriptor, metadata
    except BaseException:
        os.close(descriptor)
        raise


def _read_cache_file(
    parent_fd: int,
    name: str,
    parent_path: str,
    acl: WindowsPrivateDirectoryAcl,
) -> tuple[CodingArchPrivateDataMemberV1, int]:
    metadata = windows_stat_at(parent_fd, name)
    descriptor = open_windows_regular_file_at(
        parent_fd, name, create_new=False, write=False, read_control=True
    )
    try:
        acl.validate(descriptor, inherited_file=True)
        _require_same_windows_metadata(os.fstat(descriptor), metadata, directory=False)
        if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
            raise ValueError("Windows Coding Arch private-data file has a named stream")
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > _MAX_FILE_BYTES
            or _identity(os.fstat(descriptor)) != _identity(metadata)
        ):
            raise ValueError("Windows Coding Arch private-data file is unsafe")
        digest = sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            if size > _MAX_FILE_BYTES:
                raise ValueError("Windows Coding Arch private-data file is too large")
            digest.update(chunk)
        current_file = os.fstat(descriptor)
        current_path = windows_stat_at(parent_fd, name)
        _require_same_windows_metadata(current_file, metadata, directory=False)
        _require_same_windows_metadata(current_path, metadata, directory=False)
        if (
            windows_regular_file_stream_names(descriptor) != ("::$DATA",)
            or size != metadata.st_size
            or _identity(current_file) != _identity(metadata)
            or _identity(current_path) != _identity(metadata)
        ):
            raise ValueError("Windows Coding Arch private-data file changed")
        return (
            CodingArchPrivateDataMemberV1(
                parent_path + "/" + name,
                "file",
                _identity(metadata),
                digest.hexdigest(),
            ),
            size,
        )
    finally:
        os.close(descriptor)


def _require_directory_unchanged(
    parent_fd: int, name: str, descriptor: int, expected: os.stat_result
) -> None:
    _require_no_named_directory_streams(descriptor)
    current_directory = os.fstat(descriptor)
    current_path = windows_stat_at(parent_fd, name)
    _require_same_windows_metadata(current_directory, expected, directory=True)
    _require_same_windows_metadata(current_path, expected, directory=True)
    if _identity(current_directory) != _identity(expected) or _identity(
        current_path
    ) != _identity(expected):
        raise ValueError("Windows Coding Arch private-data directory changed")


def _require_no_named_directory_streams(descriptor: int) -> None:
    if any(
        name.casefold().endswith(":$data") and name.casefold() != "::$data"
        for name in windows_directory_stream_names(descriptor)
    ):
        raise ValueError(
            "Windows Coding Arch private-data directory has a named stream"
        )


def _require_simple_windows_metadata(
    metadata: os.stat_result, *, directory: bool
) -> None:
    _require_simple_windows_attributes(
        getattr(metadata, "st_file_attributes", None), directory=directory
    )


def _require_simple_windows_attributes(attributes: object, *, directory: bool) -> None:
    allowed = _SIMPLE_DIRECTORY_ATTRIBUTES if directory else _SIMPLE_FILE_ATTRIBUTES
    if (
        type(attributes) is not int
        or attributes == 0
        or attributes & ~allowed
        or bool(attributes & _FILE_ATTRIBUTE_DIRECTORY) != directory
    ):
        raise ValueError("Windows Coding Arch private-data attributes are unsupported")


def _require_same_windows_metadata(
    current: os.stat_result, expected: os.stat_result, *, directory: bool
) -> None:
    _require_simple_windows_metadata(expected, directory=directory)
    _require_simple_windows_metadata(current, directory=directory)
    if getattr(current, "st_file_attributes") != getattr(
        expected, "st_file_attributes"
    ):
        raise ValueError("Windows Coding Arch private-data attributes changed")


def _append_member(
    members: list[CodingArchPrivateDataMemberV1], member: CodingArchPrivateDataMemberV1
) -> None:
    if len(members) >= _MAX_ENTRIES:
        raise ValueError("Windows Coding Arch private-data preview is too large")
    members.append(member)


__all__ = ["CodingWindowsArchPrivateDataReadPreview"]
