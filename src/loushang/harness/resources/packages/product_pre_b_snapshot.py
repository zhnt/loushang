"""Product-facing owner for a complete POSIX pre-B Package snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_snapshot import (
    PackagePosixEpochSnapshotOwner,
    PackagePosixSnapshotSharedMemberV1,
)


@dataclass(frozen=True, slots=True)
class PackageProductPreBSnapshotSharedMemberV1:
    source_root: Path
    member_name: str
    domains: tuple[str, ...]


class PackageProductPreBSnapshotOwner:
    """Keep native snapshot publication behind the Product Package boundary."""

    def __init__(
        self,
        snapshot_root: Path,
        *,
        store_id: str,
        domain_roots: Mapping[str, Path],
        domain_members: Mapping[str, tuple[str, ...] | None],
        legacy_root_pointer_name: str,
        shared_members: tuple[PackageProductPreBSnapshotSharedMemberV1, ...] = (),
    ) -> None:
        self._owner = PackagePosixEpochSnapshotOwner(
            snapshot_root,
            store_id=store_id,
            domain_roots=domain_roots,
            domain_members=domain_members,
            legacy_root_pointer_name=legacy_root_pointer_name,
            shared_members=tuple(
                PackagePosixSnapshotSharedMemberV1(
                    source_root=item.source_root,
                    member_name=item.member_name,
                    domains=item.domains,
                )
                for item in shared_members
            ),
        )

    def capture(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
        quiescence_receipt_id: str,
    ) -> PackageEpochCutoverSnapshotReceiptV1:
        return self._owner.capture(
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            quiescence_receipt_id=quiescence_receipt_id,
        )

    def snapshot(
        self, snapshot_receipt_id: str
    ) -> PackageOfflineRestoreSnapshotEvidenceV1 | None:
        return self._owner.snapshot(snapshot_receipt_id)


__all__ = [
    "PackageProductPreBSnapshotOwner",
    "PackageProductPreBSnapshotSharedMemberV1",
]
