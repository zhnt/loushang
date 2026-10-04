"""Exact POSIX Coding Arch Installation private-data deletion owner.

Only a separately confirmed, removed Installation may enter this owner. The
Product runtime lease fence remains held through physical deletion and the
durable receipt; Package removal and root GC never call this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationJournal,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
    PrivateDataDeletionDisposition,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    _rename_directory_noreplace,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
    CodingArchPrivateDataDeletionJournal,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
    _capture_target_snapshot,
    _identity,
)

_OWNER_ID = "coding.arch.private-data:posix-v1"
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataDeletionOwner:
    layout: CodingPluginLifecycleStateLayout
    product: PosixLocalWheelProductSessionOwner
    confirmations: PluginPrivateDataConfirmationJournal
    journal: CodingArchPrivateDataDeletionJournal

    def __post_init__(self) -> None:
        CodingArchPrivateDataDeletionPreview(self.layout, self.product)
        if (
            not isinstance(self.confirmations, PluginPrivateDataConfirmationJournal)
            or not isinstance(self.journal, CodingArchPrivateDataDeletionJournal)
            or self.confirmations.path
            != self.product.state_root / "private-data-confirmations.jsonl"
            or self.journal.path
            != self.product.state_root / "private-data-deletions.jsonl"
        ):
            raise ValueError("Coding Arch private-data owners are not bound")

    def plan_for(self, key: PluginInstallationKeyV1) -> PluginPrivateDataDeletionPlanV1:
        root = coding_arch_installation_private_data_root(self.layout, key)
        with self._preview._offline():
            pending = self.journal.current_start()
            if pending is not None:
                if pending.plan.installation_key != key:
                    raise ValueError("Another private-data deletion is unfinished")
                return pending.plan
            target = _capture_target_snapshot(
                root, private_base=self.layout.private_data_base
            )
            return PluginPrivateDataDeletionPlanV1(
                installation_key=key, owner_id=_OWNER_ID, target_id=target.target_id
            )

    def receipt_for(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1 | None:
        coding_arch_installation_private_data_root(self.layout, plan.installation_key)
        with self._preview._offline():
            return self.journal.receipt_for(plan, confirmation)

    def delete_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1:
        if (
            not isinstance(plan, PluginPrivateDataDeletionPlanV1)
            or not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1)
            or plan.owner_id != _OWNER_ID
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError("Coding Arch private-data deletion command is invalid")
        root = coding_arch_installation_private_data_root(
            self.layout, plan.installation_key
        )
        with self._preview._offline():
            if not self.confirmations.is_confirmed(plan, confirmation):
                raise ValueError("Coding Arch private-data confirmation is missing")
            if (
                self.product.desired_state.snapshot()
                .installation(plan.installation_key)
                .selection.desired_state
                != "absent"
            ):
                raise ValueError("Coding Arch Installation must be removed first")
            replay = self.journal.receipt_for(plan, confirmation)
            if replay is not None:
                return replay
            started = self.journal.current_start()
            if started is None:
                target = _capture_target_snapshot(
                    root, private_base=self.layout.private_data_base
                )
                if plan.target_id != target.target_id:
                    raise ValueError("Coding Arch private-data deletion plan is stale")
                started = self.journal.record_start(plan, confirmation, target)
            elif started.plan != plan or started.confirmation != confirmation:
                raise ValueError("Another private-data deletion is unfinished")
            disposition, terminal_start = _delete_started(
                root, started, self.layout.private_data_base, self.journal
            )
            receipt = PluginPrivateDataDeletionReceiptV1(
                installation_key=plan.installation_key,
                owner_id=plan.owner_id,
                target_id=plan.target_id,
                plan_fingerprint=plan.fingerprint,
                confirmation_id=confirmation.confirmation_id,
                receipt_id=_receipt_id(plan, confirmation),
                disposition=disposition,
            )
            self.journal.record_completion(terminal_start, receipt)
            return receipt

    @property
    def _preview(self) -> CodingArchPrivateDataDeletionPreview:
        return CodingArchPrivateDataDeletionPreview(self.layout, self.product)


def _delete_started(
    root: Path,
    started: CodingArchPrivateDataDeletionEventV1,
    private_base: Path,
    journal: CodingArchPrivateDataDeletionJournal,
) -> tuple[PrivateDataDeletionDisposition, CodingArchPrivateDataDeletionEventV1]:
    target = started.target
    current = _capture_target_snapshot(root, private_base=private_base)
    if target.root_identity is None:
        if current.root_identity is not None:
            raise ValueError("Absent Coding Arch private-data target changed")
        return "already_absent", started

    tombstone_name = _tombstone_name(started)
    parent = root.parent
    parent_fd = os.open(parent, _DIRECTORY_FLAGS)
    try:
        parent_identity = _identity(os.fstat(parent_fd))
        if parent_identity != _identity(parent.lstat()):
            raise ValueError("Coding Arch private-data parent changed")
        tombstone = parent / tombstone_name
        try:
            tombstone_metadata = os.stat(
                tombstone_name, dir_fd=parent_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            tombstone_metadata = None
        if tombstone_metadata is None:
            if current.root_identity is None:
                if started.phase != "renamed":
                    raise ValueError("Coding Arch private-data deletion is ambiguous")
                return "deleted", started
            if started.phase != "started":
                raise ValueError("Coding Arch private-data tombstone disappeared")
            if current != target:
                raise ValueError(
                    "Coding Arch private-data target changed before rename"
                )
            source_metadata = os.stat(
                root.name, dir_fd=parent_fd, follow_symlinks=False
            )
            if _identity(source_metadata) != target.root_identity:
                raise ValueError("Coding Arch private-data target identity changed")
            _rename_directory_noreplace(parent_fd, root.name, parent_fd, tombstone_name)
            os.fsync(parent_fd)
        elif current.root_identity is not None:
            raise ValueError("Coding Arch private-data root and tombstone coexist")
        tombstone_fd = os.open(tombstone_name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        try:
            metadata = os.fstat(tombstone_fd)
            if (metadata.st_dev, metadata.st_ino) != target.root_identity[:2]:
                raise ValueError("Coding Arch private-data tombstone identity changed")
            renamed = journal.record_renamed(started)
            remaining = _capture_target_snapshot(tombstone, private_base=private_base)
            _require_remaining_subset(remaining, target)
            _remove_members(tombstone_fd, remaining.members, target)
            if os.listdir(tombstone_fd):
                raise ValueError("Coding Arch private-data tombstone is not empty")
            os.fsync(tombstone_fd)
        finally:
            os.close(tombstone_fd)
        if (
            os.stat(tombstone_name, dir_fd=parent_fd, follow_symlinks=False).st_ino
            != target.root_identity[1]
        ):
            raise ValueError("Coding Arch private-data tombstone changed")
        os.rmdir(tombstone_name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        if _exists_at(parent_fd, root.name):
            raise ValueError("Coding Arch private-data root was recreated")
        return "deleted", renamed
    finally:
        os.close(parent_fd)


def _require_remaining_subset(
    remaining: CodingArchPrivateDataTargetSnapshotV1,
    original: CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    if (
        remaining.root_identity is None
        or original.root_identity is None
        or remaining.root_identity[:3] != original.root_identity[:3]
    ):
        raise ValueError("Coding Arch private-data tombstone changed")
    expected = {member.relative_path: member for member in original.members}
    for member in remaining.members:
        prior = expected.get(member.relative_path)
        if (
            prior is None
            or member.kind != prior.kind
            or (
                member.identity != prior.identity
                if member.kind == "file"
                else member.identity[:3] != prior.identity[:3]
            )
            or member.content_sha256 != prior.content_sha256
        ):
            raise ValueError("Coding Arch private-data tombstone member changed")


def _remove_members(
    tombstone_fd: int,
    members: tuple[CodingArchPrivateDataMemberV1, ...],
    original: CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    expected = {member.relative_path: member for member in original.members}
    for member in sorted(
        members,
        key=lambda item: (item.relative_path.count("/"), item.relative_path),
        reverse=True,
    ):
        parts = member.relative_path.split("/")
        parent_fd = os.dup(tombstone_fd)
        try:
            path = ""
            for part in parts[:-1]:
                path = part if not path else path + "/" + part
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=parent_fd)
                try:
                    prior = expected[path]
                    metadata = os.fstat(next_fd)
                    if (
                        prior.kind != "directory"
                        or _identity(metadata)[:3] != prior.identity[:3]
                    ):
                        raise ValueError("Coding Arch private-data directory changed")
                except BaseException:
                    os.close(next_fd)
                    raise
                os.close(parent_fd)
                parent_fd = next_fd
            metadata = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            if member.kind == "file":
                if _identity(metadata) != member.identity:
                    raise ValueError("Coding Arch private-data file changed")
                os.unlink(parts[-1], dir_fd=parent_fd)
            else:
                if _identity(metadata)[:3] != member.identity[:3]:
                    raise ValueError("Coding Arch private-data directory changed")
                os.rmdir(parts[-1], dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)


def _exists_at(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _tombstone_name(started: CodingArchPrivateDataDeletionEventV1) -> str:
    digest = sha256(
        b"loushang.coding-arch-private-data-tombstone/v1\0"
        + started.plan.fingerprint.encode("ascii")
        + b"\0"
        + started.confirmation.confirmation_id.encode("utf-8")
    ).hexdigest()
    return ".deleting-" + digest


def _receipt_id(
    plan: PluginPrivateDataDeletionPlanV1,
    confirmation: PluginPrivateDataDeletionConfirmationV1,
) -> str:
    return sha256(
        b"loushang.coding-arch-private-data-receipt/v1\0"
        + plan.fingerprint.encode("ascii")
        + b"\0"
        + confirmation.confirmation_id.encode("utf-8")
    ).hexdigest()


__all__ = ["CodingArchPrivateDataDeletionOwner"]
