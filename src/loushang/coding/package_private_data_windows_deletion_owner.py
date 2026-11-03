"""Product-bound Windows deletion of one confirmed Coding Arch private root.

The owner holds the Product's offline gate across every filesystem effect and
durable phase. It accepts only the currently observed Arch cache shape.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
    PrivateDataDeletionDisposition,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_deletion_entry_at,
    open_windows_directory,
    windows_delete_open_entry,
    windows_flush_directory,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_rename_open_directory_at,
    windows_stat_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
    _identity,
)
from .package_private_data_windows_confirmation import (
    CodingWindowsArchPrivateDataConfirmationOwner,
)
from .package_private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionJournal,
    CodingWindowsArchPrivateDataDeletionTransaction,
    _capture_current_target,
    _tombstone_name,
    windows_arch_deletion_receipt_id,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
    _require_no_named_directory_streams,
    _require_simple_windows_metadata,
)

_OWNER_ID = "coding.arch.private-data:windows-v1"
_READ_CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataDeletionOwner:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        CodingWindowsArchPrivateDataDeletionJournal(self.layout, self.product)

    def plan_for(self, key: PluginInstallationKeyV1) -> PluginPrivateDataDeletionPlanV1:
        return CodingWindowsArchPrivateDataConfirmationOwner(
            self.layout, self.product
        ).plan_for(key)

    def receipt_for(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1 | None:
        self._require_command(plan, confirmation)
        coding_arch_installation_private_data_root(self.layout, plan.installation_key)
        with self._journal.transaction() as transaction:
            return transaction.receipt_for(plan, confirmation)

    def delete_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1:
        self._require_command(plan, confirmation)
        root = coding_arch_installation_private_data_root(
            self.layout, plan.installation_key
        )
        confirmations = CodingWindowsArchPrivateDataConfirmationOwner(
            self.layout, self.product
        )
        with self._journal.transaction() as transaction:
            replay = transaction.receipt_for(plan, confirmation)
            if replay is not None:
                return replay
            pending = transaction.current_start()
            if pending is None:
                target = _capture_current_target(confirmations, plan.installation_key)
                if target.target_id != plan.target_id:
                    raise ValueError("Windows Coding Arch deletion plan is stale")
                started = transaction.record_start(plan, confirmation, target)
            elif pending.plan == plan and pending.confirmation == confirmation:
                events = transaction.events()
                started = events[-2] if pending.phase == "renamed" else pending
                if started.phase != "started" or started.target != pending.target:
                    raise ValueError("Windows Coding Arch deletion event changed")
            else:
                raise ValueError("Another Windows Coding Arch deletion is unfinished")
            disposition = _delete_started(root, started, transaction, confirmations)
            receipt = PluginPrivateDataDeletionReceiptV1(
                installation_key=plan.installation_key,
                owner_id=plan.owner_id,
                target_id=plan.target_id,
                plan_fingerprint=plan.fingerprint,
                confirmation_id=confirmation.confirmation_id,
                receipt_id=windows_arch_deletion_receipt_id(plan, confirmation),
                disposition=disposition,
            )
            transaction.record_completion(started, receipt)
            return receipt

    @property
    def _journal(self) -> CodingWindowsArchPrivateDataDeletionJournal:
        return CodingWindowsArchPrivateDataDeletionJournal(self.layout, self.product)

    @staticmethod
    def _require_command(
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> None:
        if (
            not isinstance(plan, PluginPrivateDataDeletionPlanV1)
            or not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1)
            or plan.owner_id != _OWNER_ID
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError("Windows Coding Arch deletion command is invalid")


def _delete_started(
    root: Path,
    started: CodingArchPrivateDataDeletionEventV1,
    transaction: CodingWindowsArchPrivateDataDeletionTransaction,
    confirmations: CodingWindowsArchPrivateDataConfirmationOwner,
) -> PrivateDataDeletionDisposition:
    target = started.target
    if target.root_identity is None:
        if (
            _capture_current_target(
                confirmations, started.plan.installation_key, allow_pending=True
            )
            != target
        ):
            raise ValueError("Windows Coding Arch absent target changed")
        return "already_absent"

    parent_identity = inspect_windows_product_private_directory_identity(root.parent)
    tombstone_name = _tombstone_name(started)
    with WindowsPrivateDirectoryAcl() as exact_acl:
        parent_fd = open_windows_directory(
            root.parent, share_delete=False, read_control=True
        )
        try:
            _require_directory(parent_fd, parent_identity, exact_acl)
            names = set(windows_listdir_at(parent_fd))
            root_present = root.name in names
            tombstone_present = tombstone_name in names
            if root_present and tombstone_present:
                raise ValueError("Windows Coding Arch root and tombstone coexist")
            if not root_present and not tombstone_present:
                pending = transaction.current_start()
                if pending is None or pending.phase != "renamed":
                    raise ValueError("Windows Coding Arch deletion is ambiguous")
                return "deleted"
            if root_present:
                if transaction.current_start() != started:
                    raise ValueError("Windows Coding Arch deletion root reappeared")
                if (
                    _capture_current_target(
                        confirmations,
                        started.plan.installation_key,
                        allow_pending=True,
                    )
                    != target
                ):
                    raise ValueError("Windows Coding Arch target changed before rename")
                source_fd = open_windows_deletion_entry_at(
                    parent_fd, root.name, directory=True
                )
                try:
                    exact_acl.validate(source_fd)
                    _require_simple_windows_metadata(
                        os.fstat(source_fd), directory=True
                    )
                    _require_no_named_directory_streams(source_fd)
                    if _identity(os.fstat(source_fd))[:3] != target.root_identity[:3]:
                        raise ValueError("Windows Coding Arch root identity changed")
                    windows_rename_open_directory_at(
                        parent_fd,
                        source_fd,
                        tombstone_name,
                        expected_identity=target.root_identity,
                    )
                finally:
                    os.close(source_fd)
                windows_flush_directory(parent_fd)
            renamed = transaction.record_renamed(started)
            if renamed.phase != "renamed":
                raise ValueError("Windows Coding Arch rename event changed")
            tombstone = root.parent / tombstone_name
            remaining = _capture_windows_target_snapshot(
                tombstone, expected_root=target.root_identity[:2]
            )
            _require_remaining_subset(remaining, target)
            _remove_members(tombstone, remaining.members, target)
            if root.name in windows_listdir_at(parent_fd):
                raise ValueError("Windows Coding Arch root was recreated")
            tombstone_fd = open_windows_deletion_entry_at(
                parent_fd, tombstone_name, directory=True
            )
            try:
                _require_directory(tombstone_fd, target.root_identity[:2], exact_acl)
                if windows_listdir_at(tombstone_fd):
                    raise ValueError("Windows Coding Arch tombstone is not empty")
                windows_delete_open_entry(
                    tombstone_fd,
                    expected_identity=target.root_identity,
                    directory=True,
                )
            finally:
                os.close(tombstone_fd)
            windows_flush_directory(parent_fd)
            if root.name in windows_listdir_at(parent_fd) or (
                tombstone_name in windows_listdir_at(parent_fd)
            ):
                raise ValueError("Windows Coding Arch deletion did not settle")
            _require_directory(parent_fd, parent_identity, exact_acl)
            return "deleted"
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
        raise ValueError("Windows Coding Arch tombstone changed")
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
            raise ValueError("Windows Coding Arch tombstone member changed")


def _remove_members(
    tombstone: Path,
    members: tuple[CodingArchPrivateDataMemberV1, ...],
    original: CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    expected = {member.relative_path: member for member in original.members}
    with (
        WindowsPrivateDirectoryAcl() as exact_acl,
        WindowsPrivateDirectoryAcl(inherit_children=True) as inherited_acl,
    ):
        tombstone_fd = open_windows_directory(
            tombstone, share_delete=False, read_control=True
        )
        try:
            if original.root_identity is None:
                raise ValueError("Windows Coding Arch tombstone has no root")
            _require_directory(tombstone_fd, original.root_identity[:2], exact_acl)
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
                        prior = expected[path]
                        next_fd = open_windows_directory(
                            part,
                            dir_fd=parent_fd,
                            share_delete=False,
                            read_control=True,
                        )
                        try:
                            _require_directory(
                                next_fd,
                                prior.identity[:2],
                                exact_acl if path == "sessions" else inherited_acl,
                            )
                        except BaseException:
                            os.close(next_fd)
                            raise
                        os.close(parent_fd)
                        parent_fd = next_fd
                    entry_fd = open_windows_deletion_entry_at(
                        parent_fd, parts[-1], directory=member.kind == "directory"
                    )
                    try:
                        if member.kind == "directory":
                            _require_directory(
                                entry_fd,
                                member.identity[:2],
                                exact_acl
                                if member.relative_path == "sessions"
                                else inherited_acl,
                            )
                            if windows_listdir_at(entry_fd):
                                raise ValueError(
                                    "Windows Coding Arch directory is not empty"
                                )
                        else:
                            _require_file(
                                entry_fd, parent_fd, parts[-1], member, inherited_acl
                            )
                        windows_delete_open_entry(
                            entry_fd,
                            expected_identity=member.identity,
                            directory=member.kind == "directory",
                        )
                    finally:
                        os.close(entry_fd)
                    windows_flush_directory(parent_fd)
                finally:
                    os.close(parent_fd)
            if windows_listdir_at(tombstone_fd):
                raise ValueError("Windows Coding Arch tombstone is not empty")
            windows_flush_directory(tombstone_fd)
        finally:
            os.close(tombstone_fd)


def _require_directory(
    descriptor: int,
    expected_identity: tuple[int, int],
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    acl.validate(descriptor)
    metadata = os.fstat(descriptor)
    _require_simple_windows_metadata(metadata, directory=True)
    _require_no_named_directory_streams(descriptor)
    if (metadata.st_dev, metadata.st_ino) != expected_identity:
        raise ValueError("Windows Coding Arch directory identity changed")


def _require_file(
    descriptor: int,
    parent_fd: int,
    name: str,
    member: CodingArchPrivateDataMemberV1,
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    acl.validate(descriptor, inherited_file=True)
    before = os.fstat(descriptor)
    _require_simple_windows_metadata(before, directory=False)
    if (
        windows_regular_file_stream_names(descriptor) != ("::$DATA",)
        or _identity(before) != member.identity
    ):
        raise ValueError("Windows Coding Arch file identity changed")
    digest = sha256()
    size = 0
    while chunk := os.read(descriptor, _READ_CHUNK):
        size += len(chunk)
        if size > member.identity[3]:
            raise ValueError("Windows Coding Arch file bytes changed")
        digest.update(chunk)
    after = os.fstat(descriptor)
    visible = windows_stat_at(parent_fd, name)
    _require_simple_windows_metadata(after, directory=False)
    _require_simple_windows_metadata(visible, directory=False)
    if (
        size != member.identity[3]
        or digest.hexdigest() != member.content_sha256
        or _identity(after) != member.identity
        or _identity(visible) != member.identity
        or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
    ):
        raise ValueError("Windows Coding Arch file bytes changed")
    acl.validate(descriptor, inherited_file=True)


__all__ = ["CodingWindowsArchPrivateDataDeletionOwner"]
