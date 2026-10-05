"""Offline Windows candidate that restores one deleted Coding Arch private root.

The owner needs an exact preview plan. It leaves every incomplete stage in
place for review or exact retry and never replaces an existing root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_deletion_entry_at,
    open_windows_directory,
    windows_flush_directory,
    windows_listdir_at,
    windows_rename_open_directory_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    _prepare_windows_arch_restore_generation_intent,
    _publish_windows_arch_restored_root_receipt,
    coding_arch_installation_private_data_root,
)
from .package_private_data_backup_records import backup_parent
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
    _identity,
)
from .package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationV1,
)
from .package_private_data_restore_journal import CodingArchPrivateDataRestoreEventV1
from .package_private_data_restore_records import (
    CodingArchPrivateDataRestorePlanV1,
    CodingArchPrivateDataRestoreResultV1,
)
from .package_private_data_windows_backup import (
    _copy_members,
    _directory_identity,
    _logical_members,
    _open_or_create_directory,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
    _require_no_named_directory_streams,
    _require_simple_windows_metadata,
)
from .package_private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreJournal,
    CodingWindowsArchPrivateDataRestoreTransaction,
    CodingWindowsArchRestorePublicationV1,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataRestoreOwner:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)

    def restore(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataRestoreResultV1:
        """Copy a verified archive and atomically publish an absent root."""

        if not isinstance(plan, CodingArchPrivateDataRestorePlanV1):
            raise ValueError("Windows Coding Arch restore plan is invalid")
        coding_arch_installation_private_data_root(self.layout, plan.installation_key)
        with CodingWindowsArchPrivateDataRestoreJournal(
            self.layout, self.product
        ).transaction() as transaction:
            source = transaction._require_plan_current(plan)
            current = transaction.begin(plan)
            if current.phase == "completed":
                started = next(
                    (
                        event
                        for event in reversed(transaction.events())
                        if event.phase == "started"
                        and event.restore_id == current.restore_id
                    ),
                    None,
                )
                if started is None:
                    raise ValueError("Windows Coding Arch restore start is missing")
                publication = transaction.publication_for(started, plan)
                if publication is None:
                    raise ValueError("Windows Coding Arch restore publication is missing")
                _require_published_root(self.layout, plan, source, publication)
                transaction.complete(started, plan, source)
                disposition = "already_present"
            else:
                _restore_started(self.layout, self.product, transaction, current, plan, source)
                transaction.complete(current, plan, source)
                disposition = "restored"
            return CodingArchPrivateDataRestoreResultV1(
                backup_id=plan.backup_id,
                disposition=disposition,
                restore_id=current.restore_id,
            )

    def confirm(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Explicitly attest to current restored bytes after completion."""

        with CodingWindowsArchPrivateDataRestoreJournal(
            self.layout, self.product
        ).transaction() as transaction:
            return transaction.confirm_restore(plan)

    def verify_confirmation(
        self, plan: CodingArchPrivateDataRestorePlanV1, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        with CodingWindowsArchPrivateDataRestoreJournal(
            self.layout, self.product
        ).transaction() as transaction:
            return transaction.verify_confirmation(plan, confirmation_id)


def _restore_started(
    layout: CodingPluginLifecycleStateLayout,
    product: WindowsLocalWheelProductSessionOwner,
    transaction: CodingWindowsArchPrivateDataRestoreTransaction,
    started: CodingArchPrivateDataRestoreEventV1,
    plan: CodingArchPrivateDataRestorePlanV1,
    source: CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    root = coding_arch_installation_private_data_root(layout, plan.installation_key)
    parent_identity = inspect_windows_product_private_directory_identity(root.parent)
    stage_name = ".arch-restore-" + started.restore_id.split(":", 1)[1] + ".staging"
    with WindowsPrivateDirectoryAcl() as exact_acl:
        parent_fd = open_windows_directory(
            root.parent, share_delete=False, read_control=True
        )
        try:
            exact_acl.validate(parent_fd)
            if _directory_identity(parent_fd) != parent_identity:
                raise ValueError("Windows Coding Arch restore parent changed")
            names = set(windows_listdir_at(parent_fd))
            if any(
                name.startswith(".arch-restore-") and name != stage_name
                for name in names
            ):
                raise ValueError("Another Windows Coding Arch restore stage exists")
            publication = transaction.publication_for(
                started, plan, recover_stage=True
            )
            if root.name in names:
                if publication is None or stage_name in names:
                    raise ValueError("Windows Coding Arch restore root is unclaimed")
                _require_published_root(layout, plan, source, publication)
            else:
                if publication is None:
                    if stage_name not in names:
                        stage_fd = _open_or_create_directory(
                            parent_fd, stage_name, exact_acl
                        )
                    else:
                        stage_fd = open_windows_directory(
                            stage_name,
                            dir_fd=parent_fd,
                            share_delete=False,
                            read_control=True,
                        )
                    try:
                        exact_acl.validate(stage_fd)
                        _copy_verified_archive(layout, plan, source, stage_fd)
                        stage_identity = _identity(os.fstat(stage_fd))
                        staged = _capture_windows_target_snapshot(
                            root.parent / stage_name,
                            expected_root=stage_identity[:2],
                        )
                        if (
                            staged.root_identity != stage_identity
                            or _logical_members(staged) != _logical_members(source)
                        ):
                            raise ValueError("Windows Coding Arch restore stage changed")
                        windows_flush_directory(stage_fd)
                    finally:
                        os.close(stage_fd)
                    generation = _prepare_windows_arch_restore_generation_intent(
                        layout,
                        plan.installation_key,
                        state_root=product.state_root,
                        deletion_receipt_id=plan.deletion_receipt_id,
                    )
                    publication = transaction.prepare_publication(
                        started, plan, source, generation, stage_identity
                    )
                elif stage_name not in names:
                    raise ValueError("Windows Coding Arch restore stage disappeared")
                if publication.parent_identity != parent_identity:
                    raise ValueError("Windows Coding Arch restore parent changed")
                _publish_stage(parent_fd, root, source, publication, exact_acl)
                _require_published_root(layout, plan, source, publication)
            _publish_windows_arch_restored_root_receipt(
                layout,
                plan.installation_key,
                state_root=product.state_root,
                generation_number=publication.generation_number,
                deletion_receipt_id=plan.deletion_receipt_id,
                expected_identity=publication.stage_identity[:2],
            )
            if (
                _directory_identity(parent_fd) != parent_identity
                or stage_name in windows_listdir_at(parent_fd)
            ):
                raise ValueError("Windows Coding Arch restore parent changed")
        finally:
            os.close(parent_fd)


def _copy_verified_archive(
    layout: CodingPluginLifecycleStateLayout,
    plan: CodingArchPrivateDataRestorePlanV1,
    source: CodingArchPrivateDataTargetSnapshotV1,
    stage_fd: int,
) -> None:
    parent_path = backup_parent(layout, plan.installation_key)
    parent_identity = inspect_windows_product_private_directory_identity(parent_path)
    with (
        WindowsPrivateDirectoryAcl() as exact_acl,
        WindowsPrivateDirectoryAcl(inherit_children=True) as session_acl,
    ):
        parent_fd = open_windows_directory(
            parent_path, share_delete=False, read_control=True
        )
        try:
            exact_acl.validate(parent_fd)
            archive_fd = open_windows_directory(
                plan.backup_id,
                dir_fd=parent_fd,
                share_delete=False,
                read_control=True,
            )
            try:
                exact_acl.validate(archive_fd)
                files_fd = open_windows_directory(
                    "files",
                    dir_fd=archive_fd,
                    share_delete=False,
                    read_control=True,
                )
                try:
                    exact_acl.validate(files_fd)
                    files_path = parent_path / plan.backup_id / "files"
                    archived = _capture_windows_target_snapshot(
                        files_path, expected_root=_directory_identity(files_fd)
                    )
                    if _logical_members(archived) != _logical_members(source):
                        raise ValueError("Windows Coding Arch restore archive changed")
                    _copy_members(files_path, archived, stage_fd, exact_acl, session_acl)
                    if (
                        _capture_windows_target_snapshot(
                            files_path, expected_root=_directory_identity(files_fd)
                        )
                        != archived
                    ):
                        raise ValueError("Windows Coding Arch restore archive changed")
                finally:
                    os.close(files_fd)
            finally:
                os.close(archive_fd)
            if _directory_identity(parent_fd) != parent_identity:
                raise ValueError("Windows Coding Arch restore backup parent changed")
        finally:
            os.close(parent_fd)


def _publish_stage(
    parent_fd: int,
    root: Path,
    source: CodingArchPrivateDataTargetSnapshotV1,
    publication: CodingWindowsArchRestorePublicationV1,
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    stage = root.parent / publication.stage_name
    staged = _capture_windows_target_snapshot(
        stage, expected_root=publication.stage_identity[:2]
    )
    if (
        staged.root_identity != publication.stage_identity
        or _logical_members(staged) != _logical_members(source)
    ):
        raise ValueError("Windows Coding Arch restore stage changed")
    descriptor = open_windows_deletion_entry_at(
        parent_fd, publication.stage_name, directory=True
    )
    try:
        acl.validate(descriptor)
        _require_simple_windows_metadata(os.fstat(descriptor), directory=True)
        _require_no_named_directory_streams(descriptor)
        if _identity(os.fstat(descriptor)) != publication.stage_identity:
            raise ValueError("Windows Coding Arch restore stage identity changed")
        windows_rename_open_directory_at(
            parent_fd,
            descriptor,
            root.name,
            expected_identity=publication.stage_identity,
        )
    finally:
        os.close(descriptor)
    windows_flush_directory(parent_fd)


def _require_published_root(
    layout: CodingPluginLifecycleStateLayout,
    plan: CodingArchPrivateDataRestorePlanV1,
    source: CodingArchPrivateDataTargetSnapshotV1,
    publication: CodingWindowsArchRestorePublicationV1,
) -> None:
    root = coding_arch_installation_private_data_root(layout, plan.installation_key)
    if (
        publication.plan_fingerprint != plan.fingerprint
        or inspect_windows_product_private_directory_identity(root.parent)
        != publication.parent_identity
    ):
        raise ValueError("Windows Coding Arch restore publication changed")
    with WindowsPrivateDirectoryAcl() as acl:
        parent_fd = open_windows_directory(
            root.parent, share_delete=False, read_control=True
        )
        try:
            acl.validate(parent_fd)
            names = set(windows_listdir_at(parent_fd))
            if root.name not in names or any(
                name.startswith(".arch-restore-") for name in names
            ):
                raise ValueError("Windows Coding Arch restore publication has stage debt")
        finally:
            os.close(parent_fd)
    restored = _capture_windows_target_snapshot(
        root, expected_root=publication.stage_identity[:2]
    )
    if (
        restored.root_identity != publication.stage_identity
        or _logical_members(restored) != _logical_members(source)
    ):
        raise ValueError("Windows Coding Arch restored root changed")


__all__ = ["CodingWindowsArchPrivateDataRestoreOwner"]
