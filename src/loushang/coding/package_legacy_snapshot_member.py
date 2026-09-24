"""Bind Coding migration reads to one authenticated first-B snapshot."""

from __future__ import annotations

from typing import Literal

from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_snapshot import (
    PackagePosixEpochSnapshotEvidenceStore,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout

CodingLegacyEvidenceDomain = Literal["binding_history", "desired_state"]


class CodingLegacySnapshotError(ValueError):
    """The current Product fence cannot authorize a migration evidence read."""


def read_coding_first_b_snapshot_member(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    domain: CodingLegacyEvidenceDomain,
    member_name: str,
    maximum_bytes: int,
) -> bytes | None:
    """Read an exact Coding member without reopening mutable pre-B roots."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    if not isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        raise TypeError("Fenced Product epoch owner is required")
    if domain not in ("binding_history", "desired_state"):
        raise ValueError("Coding legacy evidence domain is unsupported")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime.assert_current()
    fence = epoch_runtime.cutover_result.fence
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
        or fence is None
        or fence.store_id != epoch.store_id
        or fence.epoch != 1
        or fence.request.prior_epoch != 0
    ):
        raise CodingLegacySnapshotError(
            "Coding legacy Package first fence is unsupported"
        )
    snapshots = PackagePosixEpochSnapshotEvidenceStore(
        epoch.snapshot_root, store_id=epoch.store_id
    )
    receipt_id = fence.request.snapshot_receipt_id
    evidence = snapshots.snapshot(receipt_id)
    if (
        evidence is None
        or evidence.snapshot.receipt_id != receipt_id
        or evidence.snapshot.legacy_root_identity != fence.request.legacy_root_identity
    ):
        raise CodingLegacySnapshotError("Coding legacy Package snapshot is unavailable")
    raw = snapshots.read_regular_member(
        receipt_id,
        domain=domain,
        member_name=member_name,
        maximum_bytes=maximum_bytes,
    )
    epoch_runtime.assert_current()
    return raw


__all__ = [
    "CodingLegacyEvidenceDomain",
    "CodingLegacySnapshotError",
    "read_coding_first_b_snapshot_member",
]
