"""Read-only status of the real pre-B workspace snapshot owner."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding._plugin_lifecycle import CodingPluginLifecycleStateLayout
from loushang.coding.package.epoch_layout import resolve_coding_package_epoch_layout
from loushang.coding.package.pre_b_snapshot import reopen_coding_package_cutover
from loushang.harness.package_product._legacy_runtime import (
    LegacyCutoverBackupReason as CodingCutoverBackupReason,
)
from loushang.harness.package_product._legacy_runtime import (
    LegacyCutoverBackupStatus as CodingCutoverBackupStatus,
)
from loushang.harness.package_product._legacy_runtime import (
    _LegacyCutoverBackupFacts,
    inspect_legacy_cutover_backup,
)


@dataclass(frozen=True, slots=True)
class CodingPackageCutoverBackupStatusV1(_LegacyCutoverBackupFacts):
    _backup_label = "Coding"

    store_id: str
    namespace_id: str
    snapshot_receipt_id: str
    status: CodingCutoverBackupStatus
    reason: CodingCutoverBackupReason
    evidence_id: str | None
    entry_count: int | None
    byte_count: int | None
    status_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "backupKind": "pre_b_workspace_snapshot",
            "byteCount": self.byte_count,
            "entryCount": self.entry_count,
            "evidenceId": self.evidence_id,
            "expiryStatus": "unknown",
            "namespaceId": self.namespace_id,
            "reason": self.reason,
            "snapshotReceiptId": self.snapshot_receipt_id,
            "status": self.status,
            "statusVersion": self.status_version,
            "storeId": self.store_id,
        }


def inspect_coding_package_cutover_backup(
    lifecycle: CodingPluginLifecycleStateLayout,
) -> CodingPackageCutoverBackupStatusV1:
    """Correlate the current B fence with a verified backup-owner snapshot."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Package lifecycle layout is required")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    cutover = reopen_coding_package_cutover(lifecycle, read_only=True)
    return inspect_legacy_cutover_backup(
        cutover,
        snapshot_root=epoch.snapshot_root,
        store_id=epoch.store_id,
        status_factory=CodingPackageCutoverBackupStatusV1,
        product_label="Coding",
    )


__all__ = [
    "CodingPackageCutoverBackupStatusV1",
    "inspect_coding_package_cutover_backup",
]
