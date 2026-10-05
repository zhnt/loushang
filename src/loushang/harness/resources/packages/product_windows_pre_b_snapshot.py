"""Windows Product owner for complete pre-B snapshots and first-B cutover."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    PackageWindowsEpochCutoverOwner,
    PackageWindowsEpochCutoverRequestV1,
    PackageWindowsEpochCutoverResultV1,
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_snapshot import (
    PackageWindowsEpochSnapshotEvidenceStore,
    PackageWindowsEpochSnapshotOwner,
    PackageWindowsSnapshotSharedMemberV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_pre_fence_registration import (
    PackageWindowsPreFenceRegistrationOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    supports_windows_rooted_io,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackageProductPreBSnapshotSharedMemberV1,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageWindowsFirstEpochCutoverCoordinationOwner,
)


@dataclass(frozen=True, slots=True)
class PackageProductWindowsCutoverAttemptV1:
    request: PackageWindowsEpochCutoverRequestV1
    result: PackageWindowsEpochCutoverResultV1


def read_windows_product_pre_b_snapshot(
    *,
    snapshot_root: Path,
    store_id: str,
    snapshot_receipt_id: str,
) -> PackageOfflineRestoreSnapshotEvidenceV1 | None:
    """Verify one Windows Product backup without reopening old Source roots."""

    return PackageWindowsEpochSnapshotEvidenceStore(
        snapshot_root, store_id=store_id
    ).snapshot(snapshot_receipt_id)


def reopen_windows_product_cutover(
    *,
    authority_root: Path,
    control_root: Path,
    store_id: str,
    epochs_root_name: str,
    read_only: bool = False,
) -> PackageWindowsEpochCutoverResultV1:
    """Reopen a durable Windows fence without accessing its old Source state."""

    _require_roots(authority_root, control_root)
    with WindowsPrivateDirectoryAcl() as acl:
        control = _PinnedWindowsAuthority.open(control_root, read_control=True)
        try:
            acl.validate(control.descriptor)
            journal_path = control_root / "epoch.jsonl"
            fences = PackageEpochFenceJournal(journal_path, read_only=read_only)
            if fences.path != journal_path:
                raise ValueError("Windows Product fence journal path changed")
            result = PackageWindowsEpochCutoverOwner.reopen_fenced(
                authority_root,
                store_id=store_id,
                epoch_journal=fences,
                epochs_root_name=epochs_root_name,
            )
            acl.validate(control.descriptor)
            control.assert_visible()
            return result
        finally:
            control.close()


class PackageProductWindowsPreBSnapshotOwner:
    """Keep Windows snapshot publication behind the Product Package boundary."""

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
        self._owner = PackageWindowsEpochSnapshotOwner(
            snapshot_root,
            store_id=store_id,
            domain_roots=domain_roots,
            domain_members=domain_members,
            legacy_root_pointer_name=legacy_root_pointer_name,
            shared_members=tuple(
                PackageWindowsSnapshotSharedMemberV1(
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

    def read_regular_member(
        self,
        snapshot_receipt_id: str,
        *,
        domain: str,
        member_name: str,
        maximum_bytes: int = 2 * 1024 * 1024,
    ) -> bytes | None:
        return self._owner.read_regular_member(
            snapshot_receipt_id,
            domain=domain,
            member_name=member_name,
            maximum_bytes=maximum_bytes,
        )

    def list_domain_members(
        self, snapshot_receipt_id: str, *, domain: str
    ) -> tuple[str, ...] | None:
        return self._owner.list_domain_members(snapshot_receipt_id, domain=domain)

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
        snapshot_admission: Callable[[PackageEpochCutoverSnapshotReceiptV1], None]
        | None = None,
    ) -> PackageProductWindowsCutoverAttemptV1:
        """Fence a quiescent old Windows Store after Product snapshot admission."""

        _require_roots(authority_root, control_root)
        with WindowsPrivateDirectoryAcl() as acl:
            control = _PinnedWindowsAuthority.open(control_root, read_control=True)
            try:
                acl.validate(control.descriptor)
                journal_path = control_root / "epoch.jsonl"
                fences = PackageEpochFenceJournal(journal_path)
                if fences.path != journal_path:
                    raise ValueError("Windows Product fence journal path changed")
                if fences.current(self._store_id) is not None:
                    raise ValueError(
                        "Windows first-B Product cutover is already fenced"
                    )
                pre_fence = PackageWindowsPreFenceRegistrationOwner(
                    control_root, store_id=self._store_id, fences=fences
                )
                owner = PackageWindowsEpochCutoverOwner(
                    authority_root,
                    store_id=self._store_id,
                    epoch_journal=fences,
                    coordination=PackageWindowsFirstEpochCutoverCoordinationOwner(
                        pre_fence
                    ),
                    snapshots=self,
                    legacy_root_name=legacy_root_name,
                    epochs_root_name=epochs_root_name,
                    snapshot_admission=snapshot_admission,
                )
                request = PackageWindowsEpochCutoverRequestV1.create(
                    store_id=self._store_id,
                    prior_fence=None,
                    expected_legacy_root_identity=owner.current_root_identity(),
                    namespace_id=namespace_id,
                    minimum_runtime_version=minimum_runtime_version,
                    minimum_runtime_protocol_epoch=minimum_runtime_protocol_epoch,
                )
                result = owner.cutover(request)
                acl.validate(control.descriptor)
                control.assert_visible()
                return PackageProductWindowsCutoverAttemptV1(
                    request=request, result=result
                )
            finally:
                control.close()


def _require_roots(authority_root: Path, control_root: Path) -> None:
    if (
        os.name != "nt"
        or not supports_windows_rooted_io()
        or any(
            not isinstance(path, Path)
            or not path.is_absolute()
            or ".." in path.parts
            or path == Path(path.anchor)
            for path in (authority_root, control_root)
        )
    ):
        raise ValueError("Windows Package Product cutover roots are invalid")


__all__ = [
    "PackageProductWindowsCutoverAttemptV1",
    "PackageProductWindowsPreBSnapshotOwner",
    "read_windows_product_pre_b_snapshot",
    "reopen_windows_product_cutover",
]
