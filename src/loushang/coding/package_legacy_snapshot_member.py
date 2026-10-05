"""Bind Coding migration reads to one authenticated first-B snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from loushang.harness.resources.packages.plugin_lifecycle.adoption import (
    PackageLegacyStateEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_snapshot import (
    PackagePosixEpochSnapshotEvidenceStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_snapshot import (
    PackageWindowsEpochSnapshotEvidenceStore,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout

CodingLegacyEvidenceDomain = Literal[
    "binding_history",
    "desired_state",
    "instance_state",
    "lock_history",
    "source_configuration",
]
CodingLegacyInventoryDomain = (
    CodingLegacyEvidenceDomain | Literal["enablement_state", "store_bytes"]
)
CodingFencedEpochRuntime: TypeAlias = (
    PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
)
_SnapshotStore: TypeAlias = (
    PackagePosixEpochSnapshotEvidenceStore | PackageWindowsEpochSnapshotEvidenceStore
)


class CodingLegacySnapshotError(ValueError):
    """The current Product fence cannot authorize a migration evidence read."""


@dataclass(frozen=True, slots=True)
class CodingFirstBLegacyStateObserver:
    """Observe the complete immutable old state for Harness adoption checks."""

    lifecycle: CodingPluginLifecycleStateLayout
    epoch_runtime: CodingFencedEpochRuntime

    def observe(
        self, *, store_id: str, legacy_root_identity: str
    ) -> PackageLegacyStateEvidenceV1:
        _snapshots, _receipt_id, evidence = _current_first_b_snapshot(
            self.lifecycle, self.epoch_runtime
        )
        fence = self.epoch_runtime.cutover_result.fence
        if (
            fence is None
            or store_id != fence.store_id
            or legacy_root_identity != fence.request.legacy_root_identity
            or evidence.snapshot.store_id != store_id
        ):
            raise CodingLegacySnapshotError(
                "Coding legacy Package observation authority changed"
            )
        self.epoch_runtime.assert_current()
        return PackageLegacyStateEvidenceV1.create(
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            state_digest=evidence.snapshot_tree_digest,
            entry_count=evidence.snapshot.entry_count,
            byte_count=evidence.snapshot.byte_count,
        )


def read_coding_first_b_snapshot_member(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
    *,
    domain: CodingLegacyEvidenceDomain,
    member_name: str,
    maximum_bytes: int,
) -> bytes | None:
    """Read an exact Coding member without reopening mutable pre-B roots."""

    if domain not in (
        "binding_history",
        "desired_state",
        "instance_state",
        "lock_history",
        "source_configuration",
    ):
        raise ValueError("Coding legacy evidence domain is unsupported")
    snapshots, receipt_id, _evidence = _current_first_b_snapshot(
        lifecycle, epoch_runtime
    )
    raw = snapshots.read_regular_member(
        receipt_id,
        domain=domain,
        member_name=member_name,
        maximum_bytes=maximum_bytes,
    )
    epoch_runtime.assert_current()
    return raw


def list_coding_first_b_snapshot_domain_members(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
    *,
    domain: CodingLegacyInventoryDomain,
) -> tuple[str, ...]:
    """Enumerate one authenticated pre-B domain under the same first fence."""

    if domain not in (
        "binding_history",
        "desired_state",
        "enablement_state",
        "instance_state",
        "lock_history",
        "source_configuration",
        "store_bytes",
    ):
        raise ValueError("Coding legacy evidence domain is unsupported")
    snapshots, receipt_id, _evidence = _current_first_b_snapshot(
        lifecycle, epoch_runtime
    )
    members = snapshots.list_domain_members(receipt_id, domain=domain)
    if members is None:
        raise CodingLegacySnapshotError("Coding legacy Package snapshot disappeared")
    epoch_runtime.assert_current()
    return members


def _current_first_b_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
) -> tuple[
    _SnapshotStore,
    str,
    PackageOfflineRestoreSnapshotEvidenceV1,
]:
    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    if not isinstance(
        epoch_runtime,
        (PackageProductPosixFencedRuntimeOwner, PackageProductWindowsFencedRuntimeOwner),
    ):
        raise TypeError("Fenced Product epoch owner is required")
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
    snapshot_owner = (
        PackageWindowsEpochSnapshotEvidenceStore
        if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
        else PackagePosixEpochSnapshotEvidenceStore
    )
    snapshots = snapshot_owner(epoch.snapshot_root, store_id=epoch.store_id)
    receipt_id = fence.request.snapshot_receipt_id
    evidence = snapshots.snapshot(receipt_id)
    if (
        evidence is None
        or evidence.snapshot.receipt_id != receipt_id
        or evidence.snapshot.legacy_root_identity != fence.request.legacy_root_identity
    ):
        raise CodingLegacySnapshotError("Coding legacy Package snapshot is unavailable")
    return snapshots, receipt_id, evidence


__all__ = [
    "CodingFencedEpochRuntime",
    "CodingLegacyEvidenceDomain",
    "CodingLegacyInventoryDomain",
    "CodingLegacySnapshotError",
    "CodingFirstBLegacyStateObserver",
    "list_coding_first_b_snapshot_domain_members",
    "read_coding_first_b_snapshot_member",
]
