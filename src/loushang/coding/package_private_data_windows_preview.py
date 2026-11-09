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
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._private_tree_windows import (
    PrivateWindowsTreeIO,
)
from loushang.harness.resources.packages._private_tree_windows_observation import (
    PrivateWindowsTreeShape,
    capture_private_windows_tree,
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
)

_ROOT_DIRECTORY = "sessions"
_SESSION_NAME = re.compile(r"[0-9a-f]{64}\Z")
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_SIMPLE_FILE_ATTRIBUTES = 0x00000020 | 0x00000080 | 0x00002000
_SIMPLE_DIRECTORY_ATTRIBUTES = _FILE_ATTRIBUTE_DIRECTORY | 0x00000020 | 0x00002000


_native_io = PrivateWindowsTreeIO(
    label="Windows Coding Arch",
    backup_label="Coding Arch",
    simple_file_attributes=_SIMPLE_FILE_ATTRIBUTES,
    simple_directory_attributes=_SIMPLE_DIRECTORY_ATTRIBUTES,
    max_read_bytes=_MAX_FILE_BYTES,
    read_chunk_size=1024 * 1024,
    inherited_directory_depth=2,
    exact_directory_name=_ROOT_DIRECTORY,
)


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
    return capture_private_windows_tree(
        root,
        expected_root=expected_root,
        io=_native_io,
        shape=PrivateWindowsTreeShape(
            root_directory=_ROOT_DIRECTORY,
            child_names=_SESSION_NAME,
            invalid_child_message="Windows Coding Arch private-data Session is invalid",
            max_entries=_MAX_ENTRIES,
            max_file_bytes=_MAX_FILE_BYTES,
            max_total_bytes=_MAX_TOTAL_BYTES,
        ),
        make_member=CodingArchPrivateDataMemberV1,
        project_snapshot=lambda identity, members: (
            CodingArchPrivateDataTargetSnapshotV1(
                root_path_digest=sha256(os.fsencode(str(root))).hexdigest(),
                root_identity=identity,
                members=members,
            )
        ),
    )


_require_no_named_directory_streams = _native_io.require_no_named_directory_streams


_require_simple_windows_metadata = _native_io.require_simple_metadata


_require_same_windows_metadata = _native_io.require_same_metadata


__all__ = ["CodingWindowsArchPrivateDataReadPreview"]
