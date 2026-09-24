"""Read-only status of the real pre-B workspace snapshot owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loushang.coding._plugin_lifecycle import CodingPluginLifecycleStateLayout
from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
from loushang.coding.package_pre_b_snapshot import reopen_coding_package_cutover
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    read_posix_product_pre_b_snapshot,
)

CodingCutoverBackupStatus = Literal["retained", "unknown"]
CodingCutoverBackupReason = Literal[
    "snapshot_verified",
    "snapshot_evidence_missing",
    "snapshot_owner_unavailable",
]


@dataclass(frozen=True, slots=True)
class CodingPackageCutoverBackupStatusV1:
    store_id: str
    namespace_id: str
    snapshot_receipt_id: str
    status: CodingCutoverBackupStatus
    reason: CodingCutoverBackupReason
    evidence_id: str | None
    entry_count: int | None
    byte_count: int | None
    status_version: int = 1

    def __post_init__(self) -> None:
        if type(self.status_version) is not int or self.status_version != 1 or not all(
            (self.store_id, self.namespace_id, self.snapshot_receipt_id)
        ):
            raise ValueError("Coding cutover backup status identity is invalid")
        if self.status == "retained":
            if (
                self.reason != "snapshot_verified"
                or self.evidence_id is None
                or self.entry_count is None
                or self.byte_count is None
            ):
                raise ValueError("Retained cutover backup requires owner evidence")
        elif self.status == "unknown":
            if (
                self.reason not in {
                    "snapshot_evidence_missing", "snapshot_owner_unavailable"
                }
                or self.evidence_id is not None
                or self.entry_count is not None
                or self.byte_count is not None
            ):
                raise ValueError("Unknown cutover backup cannot claim evidence")
        else:
            raise ValueError("Unsupported cutover backup status")

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
    cutover = reopen_coding_package_cutover(lifecycle)
    if cutover.disposition != "fenced" or cutover.fence is None:
        raise RuntimeError("Coding Package Product fence is unavailable")
    fence = cutover.fence
    receipt_id = fence.request.snapshot_receipt_id
    reason: CodingCutoverBackupReason
    try:
        evidence = read_posix_product_pre_b_snapshot(
            snapshot_root=epoch.snapshot_root,
            store_id=epoch.store_id,
            snapshot_receipt_id=receipt_id,
        )
    except FileNotFoundError:
        evidence = None
        reason = "snapshot_owner_unavailable"
    else:
        reason = "snapshot_evidence_missing"
    if evidence is None:
        return CodingPackageCutoverBackupStatusV1(
            store_id=epoch.store_id,
            namespace_id=fence.request.namespace_id,
            snapshot_receipt_id=receipt_id,
            status="unknown",
            reason=reason,
            evidence_id=None,
            entry_count=None,
            byte_count=None,
        )
    snapshot = evidence.snapshot
    if (
        snapshot.store_id != epoch.store_id
        or snapshot.legacy_root_identity != fence.request.legacy_root_identity
        or snapshot.quiescence_receipt_id != fence.request.quiescence_receipt_id
        or cutover.switch_receipt is None
        or cutover.switch_receipt.snapshot_receipt_id != receipt_id
    ):
        raise ValueError("Coding cutover backup does not match the current fence")
    return CodingPackageCutoverBackupStatusV1(
        store_id=epoch.store_id,
        namespace_id=fence.request.namespace_id,
        snapshot_receipt_id=receipt_id,
        status="retained",
        reason="snapshot_verified",
        evidence_id=evidence.evidence_id,
        entry_count=snapshot.entry_count,
        byte_count=snapshot.byte_count,
    )


__all__ = [
    "CodingPackageCutoverBackupStatusV1",
    "inspect_coding_package_cutover_backup",
]
