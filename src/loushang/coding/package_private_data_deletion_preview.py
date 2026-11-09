"""Read-only, fenced preview of Coding Arch Installation private data.

This preview grants no deletion authority. The eventual domain owner must
recapture the target under the same Product fence before a confirmed mutation.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Literal

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_records import (
    PrivateDataMemberV1,
    PrivateDataTargetSnapshotV1,
)
from loushang.harness.plugin_management._private_data_records import (
    _valid_digest as _valid_digest,
)
from loushang.harness.plugin_management._private_data_records import (
    _valid_identity as _valid_identity,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._private_tree_posix import (
    capture_private_tree,
    metadata_identity,
)

from ._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)

_OWNER_ID = "coding.arch.private-data:posix-v1"
_MAX_ENTRIES = 4096
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 64 * 1024 * 1024
_identity = metadata_identity


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataMemberV1(PrivateDataMemberV1):
    label: ClassVar[str] = "Coding Arch"
    relative_path: str
    kind: Literal["directory", "file"]
    identity: tuple[int, int, int, int, int]
    content_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataTargetSnapshotV1(
    PrivateDataTargetSnapshotV1[CodingArchPrivateDataMemberV1]
):
    label: ClassVar[str] = "Coding Arch"
    max_entries: ClassVar[int] = _MAX_ENTRIES
    fingerprint_domain: ClassVar[bytes] = (
        b"loushang.coding-arch-private-data-preview/v1\0"
    )
    root_path_digest: str
    root_identity: tuple[int, int, int, int, int] | None
    members: tuple[CodingArchPrivateDataMemberV1, ...]

    @classmethod
    def member_from_dict(cls, value: object) -> CodingArchPrivateDataMemberV1:
        return CodingArchPrivateDataMemberV1.from_dict(value)


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataDeletionPreview:
    """Capture an exact target without creating files or authorizing deletion."""

    layout: CodingPluginLifecycleStateLayout
    product: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        if (
            not isinstance(self.layout, CodingPluginLifecycleStateLayout)
            or not isinstance(self.product, PosixLocalWheelProductSessionOwner)
            or self.product.policy.product_id != "coding"
            or self.layout
            != resolve_coding_plugin_lifecycle_state_layout(self.product.workspace)
            or self.product.policy.project_scope_id != self.layout.scope_id
            or self.product.epoch_runtime.registry.store_id
            != resolve_coding_package_epoch_layout(self.layout).store_id
        ):
            raise ValueError("Coding Arch private-data Product owner is not bound")

    def plan_for(self, key: PluginInstallationKeyV1) -> PluginPrivateDataDeletionPlanV1:
        target = self.snapshot_for(key)
        return PluginPrivateDataDeletionPlanV1(
            installation_key=key, owner_id=_OWNER_ID, target_id=target.target_id
        )

    def snapshot_for(
        self, key: PluginInstallationKeyV1
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        root = coding_arch_installation_private_data_root(self.layout, key)
        with self._offline():
            return _capture_target_snapshot(
                root, private_base=self.layout.private_data_base
            )

    @contextmanager
    def _offline(self) -> Iterator[None]:
        registry = self.product.epoch_runtime.registry
        with registry.exclusive_runtime_quiescence(
            store_id=registry.store_id
        ) as quiescence:
            if quiescence.active_runtime_lease_ids:
                raise ValueError("Coding Arch private-data Product runtime is active")
            self.product.assert_root_gc_authority_current()
            with self.product.gc_gate.guard():
                yield
            self.product.assert_root_gc_authority_current()


def _capture_target_snapshot(
    root: Path, *, private_base: Path
) -> CodingArchPrivateDataTargetSnapshotV1:
    identity, members = capture_private_tree(
        root,
        private_base=private_base,
        label="Coding Arch",
        max_entries=_MAX_ENTRIES,
        max_file_bytes=_MAX_FILE_BYTES,
        max_total_bytes=_MAX_TOTAL_BYTES,
    )
    return CodingArchPrivateDataTargetSnapshotV1(
        sha256(os.fsencode(str(root))).hexdigest(),
        identity,
        tuple(
            CodingArchPrivateDataMemberV1(
                item.relative_path, item.kind, item.identity, item.content_sha256
            )
            for item in members
        ),
    )


__all__ = [
    "CodingArchPrivateDataDeletionPreview",
    "CodingArchPrivateDataMemberV1",
    "CodingArchPrivateDataTargetSnapshotV1",
]
