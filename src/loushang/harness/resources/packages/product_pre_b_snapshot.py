"""Product-facing owner for a complete POSIX pre-B Package snapshot."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistry,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_coordination import (
    PackagePosixEpochCutoverCoordination,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
    PackagePosixEpochCutoverOwner,
    PackagePosixEpochCutoverRequestV1,
    PackagePosixEpochCutoverResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_snapshot import (
    PackagePosixEpochSnapshotEvidenceStore,
    PackagePosixEpochSnapshotOwner,
    PackagePosixSnapshotSharedMemberV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_pre_fence_registration import (
    PackagePosixPreFenceRegistrationOwner,
)


@dataclass(frozen=True, slots=True)
class PackageProductPreBSnapshotSharedMemberV1:
    source_root: Path
    member_name: str
    domains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PackageProductPosixCutoverAttemptV1:
    request: PackagePosixEpochCutoverRequestV1
    result: PackagePosixEpochCutoverResultV1


def read_posix_product_pre_b_snapshot(
    *,
    snapshot_root: Path,
    store_id: str,
    snapshot_receipt_id: str,
) -> PackageOfflineRestoreSnapshotEvidenceV1 | None:
    """Verify one fenced Product backup through its native snapshot owner."""

    return PackagePosixEpochSnapshotEvidenceStore(
        snapshot_root, store_id=store_id
    ).snapshot(snapshot_receipt_id)


def reopen_posix_product_cutover(
    *,
    authority_root: Path,
    control_root: Path,
    store_id: str,
    epochs_root_name: str,
) -> PackagePosixEpochCutoverResultV1:
    """Reopen the fenced Product root using durable evidence, without old Source."""

    if any(
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        for path in (authority_root, control_root)
    ):
        raise ValueError("Package Product epoch roots must be absolute")
    if control_root != control_root.resolve(strict=True):
        raise ValueError("Package Product control root is not canonical")
    metadata = control_root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_uid != os.geteuid()
    ):
        raise ValueError("Package Product control root is not private")
    journal_path = control_root / "epoch.jsonl"
    journal = PackageEpochFenceJournal(journal_path)
    if journal.path != journal_path:
        raise ValueError("Package Product fence journal is not canonical")
    result = PackagePosixEpochCutoverOwner.reopen_fenced(
        authority_root,
        store_id=store_id,
        epoch_journal=journal,
        epochs_root_name=epochs_root_name,
    )
    observed = control_root.lstat()
    if (
        control_root != control_root.resolve(strict=True)
        or journal.path != journal_path
        or (observed.st_dev, observed.st_ino) != (metadata.st_dev, metadata.st_ino)
    ):
        raise ValueError("Package Product control root changed during reopen")
    return result


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
        self._store_id = store_id
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

    def cutover_from_legacy(
        self,
        *,
        authority_root: Path,
        control_root: Path,
        legacy_root_name: str,
        epochs_root_name: str,
        namespace_id: str,
        minimum_runtime_version: str,
        minimum_runtime_protocol_epoch: int,
    ) -> PackageProductPosixCutoverAttemptV1:
        """Fence a quiescent legacy Store against this exact snapshot owner."""

        if os.name != "posix" or any(
            not hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
        ):
            raise RuntimeError("POSIX Package Product cutover is required")
        if any(
            not isinstance(path, Path)
            or not path.is_absolute()
            or ".." in path.parts
            for path in (authority_root, control_root)
        ):
            raise ValueError("Package Product cutover roots must be absolute")
        fences = PackageEpochFenceJournal(control_root / "epoch.jsonl")
        pre_fence = PackagePosixPreFenceRegistrationOwner(
            authority_root, store_id=self._store_id, fences=fences
        )
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(control_root, flags)
        file_io = None
        try:
            file_io = RootedFileIO(control_root, descriptor)
            leases = PackageEpochRuntimeLeaseRegistry(
                path=control_root / "runtime-leases.jsonl",
                coordination_lock=control_root / "coordination",
                file_io=file_io,
                fences=fences,
                store_id=self._store_id,
            )
            owner = PackagePosixEpochCutoverOwner(
                authority_root,
                store_id=self._store_id,
                epoch_journal=fences,
                legacy_root_name=legacy_root_name,
                epochs_root_name=epochs_root_name,
                coordination=PackagePosixEpochCutoverCoordination(
                    leases=leases,
                    pre_fence=pre_fence,
                ),
                snapshots=self,
            )
            current = fences.current(self._store_id)
            request = PackagePosixEpochCutoverRequestV1.create(
                store_id=self._store_id,
                prior_fence=None,
                expected_legacy_root_identity=(
                    owner.current_root_identity()
                    if current is None
                    else current.request.legacy_root_identity
                ),
                namespace_id=namespace_id,
                minimum_runtime_version=minimum_runtime_version,
                minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
            )
            return PackageProductPosixCutoverAttemptV1(
                request=request,
                result=owner.cutover(request),
            )
        finally:
            try:
                if file_io is not None:
                    file_io.cleanup()
            finally:
                os.close(descriptor)


__all__ = [
    "PackagePosixEpochCutoverResultV1",
    "PackageProductPreBSnapshotOwner",
    "PackageProductPreBSnapshotSharedMemberV1",
    "PackageProductPosixCutoverAttemptV1",
    "read_posix_product_pre_b_snapshot",
    "reopen_posix_product_cutover",
]
