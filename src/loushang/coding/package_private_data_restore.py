"""Explicit offline restore of one retained Coding Arch Installation backup.

The restore owner requires Product removal and a completed deletion receipt.
It never replaces existing private data; a complete existing tree is an exact
replay. Backup expiry and public restore commands remain separate decisions.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    _rename_directory_noreplace,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout, _prepare_private_tree
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_backup import (
    CodingArchPrivateDataBackupReceiptV1,
    _backup_parent,
    _digest,
    _exists_at,
    _mkdir_at,
    _open_chain,
    _open_private_dir,
    _open_private_path,
    _read_bounded,
    _read_manifest,
    _verify_archive,
    _verify_files,
    _write_or_verify_file,
)
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionJournal,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataTargetSnapshotV1,
    _capture_target_snapshot,
    _identity,
)
from .package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal,
    CodingArchPrivateDataRestoreConfirmationV1,
)
from .package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreEventV1,
    CodingArchPrivateDataRestoreJournal,
    restore_id_for,
)
from .package_private_data_restore_records import (
    CodingArchPrivateDataRestorePlanV1,
    CodingArchPrivateDataRestoreResultV1,
)


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataRestoreOwner:
    layout: CodingPluginLifecycleStateLayout
    product: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingArchPrivateDataDeletionPreview(self.layout, self.product)

    def confirm(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Durably confirm exact restored bytes after completion, by request."""

        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            completion, target_id = self._current_completed_restore(key, backup_id)
            journal = CodingArchPrivateDataRestoreConfirmationJournal(
                self.product.state_root
            )
            records = journal.records()
            previous = next(
                (
                    item
                    for item in reversed(records)
                    if item.restore_id == completion.restore_id
                ),
                None,
            )
            confirmation = CodingArchPrivateDataRestoreConfirmationV1.create(
                revision=len(records) + 1 if previous is None else previous.revision,
                installation_key=key,
                backup_id=backup_id,
                deletion_receipt_id=completion.deletion_receipt_id,
                restore_id=completion.restore_id,
                restore_completion_digest=completion.record_digest,
                restored_target_id=target_id,
            )
            return journal.record(confirmation)

    def verify_confirmation(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Reopen one confirmation against current Product and restored bytes."""

        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            completion, target_id = self._current_completed_restore(key, backup_id)
            records = CodingArchPrivateDataRestoreConfirmationJournal(
                self.product.state_root
            ).records()
            matched = next(
                (
                    item
                    for item in reversed(records)
                    if item.confirmation_id == confirmation_id
                ),
                None,
            )
            if (
                matched is None
                or matched.installation_key != key
                or matched.backup_id != backup_id
                or matched.restore_id != completion.restore_id
                or matched.deletion_receipt_id != completion.deletion_receipt_id
                or matched.restore_completion_digest != completion.record_digest
                or matched.restored_target_id != target_id
            ):
                raise ValueError("Coding Arch restore confirmation is stale")
            return matched

    def _current_completed_restore(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> tuple[CodingArchPrivateDataRestoreEventV1, str]:
        if not _digest(backup_id):
            raise ValueError("Coding Arch restore backup ID is invalid")
        desired = self.product.desired_state.snapshot()
        if desired.installation(key).selection.desired_state != "absent":
            raise ValueError("Coding Arch restore confirmation requires removal")
        deletion = CodingArchPrivateDataDeletionJournal(self.product.state_root)
        if deletion.current_start() is not None:
            raise ValueError("Coding Arch deletion is unfinished")
        parent_fd = _open_private_path(
            self.layout.private_data_base, _backup_parent(self.layout, key)
        )
        try:
            receipt, source = _read_manifest(parent_fd, backup_id)
            if receipt.installation_key != key or receipt.backup_id != backup_id:
                raise ValueError("Coding Arch restore backup Installation changed")
            deletion_receipt = _matching_latest_deletion(deletion, key, receipt)
            if deletion_receipt is None:
                raise ValueError("Coding Arch restore confirmation lacks deletion")
            _verify_archive(parent_fd, backup_id, key, source, receipt)
        finally:
            os.close(parent_fd)
        completion_id = restore_id_for(key, backup_id, deletion_receipt.receipt_id)
        events = CodingArchPrivateDataRestoreJournal(self.product.state_root).events()
        completion = next(
            (
                item
                for item in reversed(events)
                if item.restore_id == completion_id and item.phase == "completed"
            ),
            None,
        )
        if completion is None or (events and events[-1].phase == "started"):
            raise ValueError("Coding Arch restore is not completed")
        source_root = coding_arch_installation_private_data_root(self.layout, key)
        _require_restored_tree(self.layout, source_root, source)
        target = _capture_target_snapshot(
            source_root, private_base=self.layout.private_data_base
        )
        if target.root_identity is None:
            raise ValueError("Coding Arch restored target is absent")
        return completion, target.target_id

    def preview(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataRestorePlanV1:
        """Read exact Product, archive, and target facts without publishing data."""

        source_root = coding_arch_installation_private_data_root(self.layout, key)
        if not _digest(backup_id):
            raise ValueError("Coding Arch restore backup ID is invalid")
        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            desired = self.product.desired_state.snapshot()
            if desired.installation(key).selection.desired_state != "absent":
                raise ValueError("Coding Arch restore requires a removed Installation")
            deletion = CodingArchPrivateDataDeletionJournal(self.product.state_root)
            if deletion.current_start() is not None:
                raise ValueError("Coding Arch deletion is unfinished")
            backup_parent_fd = _open_private_path(
                self.layout.private_data_base, _backup_parent(self.layout, key)
            )
            try:
                receipt, source = _read_manifest(backup_parent_fd, backup_id)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Coding Arch restore Installation changed")
                deletion_receipt = _matching_latest_deletion(deletion, key, receipt)
                if deletion_receipt is None:
                    raise ValueError("Coding Arch restore lacks completed deletion")
                _verify_archive(backup_parent_fd, backup_id, key, source, receipt)
            finally:
                os.close(backup_parent_fd)
            current = _capture_target_snapshot(
                source_root, private_base=self.layout.private_data_base
            )
            if current.root_identity is None:
                target_state: Literal["absent", "same_bytes"] = "absent"
            else:
                _require_restored_tree(self.layout, source_root, source)
                target_state = "same_bytes"
            _require_no_foreign_restore_stage(
                self.layout,
                source_root,
                backup_id,
                target_present=target_state == "same_bytes",
            )
            return CodingArchPrivateDataRestorePlanV1(
                installation_key=key,
                backup_id=backup_id,
                deletion_receipt_id=deletion_receipt.receipt_id,
                source_target_id=source.target_id,
                desired_inventory_revision=desired.inventory_revision,
                target_state=target_state,
            )

    def restore(
        self,
        key: PluginInstallationKeyV1,
        backup_id: str,
        *,
        expected_plan: CodingArchPrivateDataRestorePlanV1 | None = None,
    ) -> CodingArchPrivateDataRestoreResultV1:
        """Publish verified backup bytes only into an absent Installation root."""

        source_root = coding_arch_installation_private_data_root(self.layout, key)
        if not _digest(backup_id):
            raise ValueError("Coding Arch restore backup ID is invalid")
        if expected_plan is not None and (
            not isinstance(expected_plan, CodingArchPrivateDataRestorePlanV1)
            or expected_plan.installation_key != key
            or expected_plan.backup_id != backup_id
        ):
            raise ValueError("Coding Arch restore plan is foreign")
        preview = CodingArchPrivateDataDeletionPreview(self.layout, self.product)
        with preview._offline():
            desired = self.product.desired_state.snapshot()
            if desired.installation(key).selection.desired_state != "absent":
                raise ValueError("Coding Arch restore requires a removed Installation")
            if (
                expected_plan is not None
                and desired.inventory_revision
                != expected_plan.desired_inventory_revision
            ):
                raise ValueError("Coding Arch restore Desired revision changed")
            deletion = CodingArchPrivateDataDeletionJournal(self.product.state_root)
            if deletion.current_start() is not None:
                raise ValueError("Coding Arch deletion is unfinished")
            backup_parent_fd = _open_private_path(
                self.layout.private_data_base, _backup_parent(self.layout, key)
            )
            try:
                receipt, source = _read_manifest(backup_parent_fd, backup_id)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Coding Arch restore Installation changed")
                deletion_receipt = _matching_latest_deletion(deletion, key, receipt)
                if deletion_receipt is None:
                    raise ValueError("Coding Arch restore lacks completed deletion")
                if expected_plan is not None and (
                    expected_plan.source_target_id != source.target_id
                    or expected_plan.deletion_receipt_id != deletion_receipt.receipt_id
                ):
                    raise ValueError("Coding Arch restore plan evidence changed")
                archive_identity = _identity(
                    os.stat(backup_id, dir_fd=backup_parent_fd, follow_symlinks=False)
                )
                _verify_archive(backup_parent_fd, backup_id, key, source, receipt)
                archive_fd = _open_private_dir(backup_parent_fd, backup_id)
                try:
                    if _identity(os.fstat(archive_fd)) != archive_identity:
                        raise ValueError("Coding Arch restore archive changed")
                    files_fd = _open_private_dir(archive_fd, "files")
                    try:
                        _verify_files(files_fd, source)
                        existing_target = _preflight_restore_target(
                            self.layout, source_root, source, backup_id
                        )
                        if (
                            expected_plan is not None
                            and expected_plan.target_state == "same_bytes"
                            and not existing_target
                        ):
                            raise ValueError("Coding Arch restore target changed")
                        journal = CodingArchPrivateDataRestoreJournal(
                            self.product.state_root
                        )
                        restore_id = restore_id_for(
                            key, backup_id, deletion_receipt.receipt_id
                        )
                        if existing_target and not any(
                            event.restore_id == restore_id for event in journal.events()
                        ):
                            raise ValueError(
                                "Coding Arch existing data lacks restore start"
                            )
                        started = journal.begin(
                            key=key,
                            backup_id=backup_id,
                            deletion_receipt_id=deletion_receipt.receipt_id,
                        )
                        if started.phase == "completed":
                            _require_restored_tree(self.layout, source_root, source)
                            disposition = "already_present"
                        else:
                            disposition = _restore_verified_files(
                                self.layout, source_root, source, files_fd, backup_id
                            )
                        _verify_files(files_fd, source)
                    finally:
                        os.close(files_fd)
                    if _identity(os.fstat(archive_fd)) != _identity(
                        os.stat(
                            backup_id,
                            dir_fd=backup_parent_fd,
                            follow_symlinks=False,
                        )
                    ):
                        raise ValueError("Coding Arch restore archive changed")
                    completed = (
                        started
                        if started.phase == "completed"
                        else journal.complete(started)
                    )
                    return CodingArchPrivateDataRestoreResultV1(
                        backup_id, disposition, completed.restore_id
                    )
                finally:
                    os.close(archive_fd)
            finally:
                os.close(backup_parent_fd)


def _matching_latest_deletion(
    journal: CodingArchPrivateDataDeletionJournal,
    key: PluginInstallationKeyV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
) -> PluginPrivateDataDeletionReceiptV1 | None:
    for event in reversed(journal.events()):
        if event.plan.installation_key != key:
            continue
        if (
            event.phase == "completed"
            and event.target.target_id == receipt.source_target_id
            and event.receipt is not None
            and event.receipt.disposition == "deleted"
        ):
            return event.receipt
        return None
    return None


def _restore_verified_files(
    layout: CodingPluginLifecycleStateLayout,
    source_root: Path,
    source: CodingArchPrivateDataTargetSnapshotV1,
    files_fd: int,
    backup_id: str,
) -> str:
    target = source_root
    _prepare_private_tree(
        target.parent, private_base=layout.private_data_base, label="data"
    )
    parent_fd = _open_private_path(layout.private_data_base, target.parent)
    try:
        stage_name = ".arch-restore-" + backup_id + ".staging"
        if any(
            name.startswith(".arch-restore-")
            and name.endswith(".staging")
            and name != stage_name
            for name in os.listdir(parent_fd)
        ):
            raise ValueError("Coding Arch restore has foreign staging debt")
        if _exists_at(parent_fd, target.name):
            if _exists_at(parent_fd, stage_name):
                raise ValueError("Coding Arch restore has unsettled staging debt")
            existing_fd = _open_private_dir(parent_fd, target.name)
            try:
                _verify_files(existing_fd, source)
            finally:
                os.close(existing_fd)
            return "already_present"
        _mkdir_at(parent_fd, stage_name)
        stage_fd = _open_private_dir(parent_fd, stage_name)
        try:
            for item in source.members:
                parts = item.relative_path.split("/")
                destination_parent = _open_chain(stage_fd, parts[:-1], create=True)
                try:
                    if item.kind == "directory":
                        _mkdir_at(destination_parent, parts[-1])
                    else:
                        archive_parent = _open_chain(files_fd, parts[:-1], create=False)
                        try:
                            file_fd = os.open(
                                parts[-1],
                                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=archive_parent,
                            )
                            try:
                                content = _read_bounded(
                                    file_fd,
                                    item.identity[3],
                                    exact_size=item.identity[3],
                                )
                            finally:
                                os.close(file_fd)
                        finally:
                            os.close(archive_parent)
                        if sha256(content).hexdigest() != item.content_sha256:
                            raise ValueError("Coding Arch restore content changed")
                        _write_or_verify_file(destination_parent, parts[-1], content)
                    os.fsync(destination_parent)
                finally:
                    os.close(destination_parent)
            _verify_files(stage_fd, source)
            os.fsync(stage_fd)
            visible_stage = os.stat(stage_name, dir_fd=parent_fd, follow_symlinks=False)
            opened_stage = os.fstat(stage_fd)
            visible_parent = target.parent.lstat()
            opened_parent = os.fstat(parent_fd)
            if (
                not stat.S_ISDIR(visible_stage.st_mode)
                or (visible_stage.st_dev, visible_stage.st_ino)
                != (opened_stage.st_dev, opened_stage.st_ino)
                or (visible_parent.st_dev, visible_parent.st_ino)
                != (opened_parent.st_dev, opened_parent.st_ino)
            ):
                raise ValueError("Coding Arch restore stage or parent changed")
            _rename_directory_noreplace(parent_fd, stage_name, parent_fd, target.name)
            published = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
            if (published.st_dev, published.st_ino) != (
                os.fstat(stage_fd).st_dev,
                os.fstat(stage_fd).st_ino,
            ):
                raise ValueError("Coding Arch restored root changed")
            os.fsync(parent_fd)
        finally:
            os.close(stage_fd)
        restored_fd = _open_private_dir(parent_fd, target.name)
        try:
            _verify_files(restored_fd, source)
        finally:
            os.close(restored_fd)
        return "restored"
    finally:
        os.close(parent_fd)


def _preflight_restore_target(
    layout: CodingPluginLifecycleStateLayout,
    target: Path,
    source: CodingArchPrivateDataTargetSnapshotV1,
    backup_id: str,
) -> bool:
    _prepare_private_tree(
        target.parent, private_base=layout.private_data_base, label="data"
    )
    parent_fd = _open_private_path(layout.private_data_base, target.parent)
    try:
        stage_name = ".arch-restore-" + backup_id + ".staging"
        if any(
            name.startswith(".arch-restore-")
            and name.endswith(".staging")
            and name != stage_name
            for name in os.listdir(parent_fd)
        ):
            raise ValueError("Coding Arch restore has foreign staging debt")
        if _exists_at(parent_fd, target.name):
            if _exists_at(parent_fd, stage_name):
                raise ValueError("Coding Arch restore has unsettled staging debt")
            _require_restored_tree(layout, target, source)
            return True
        return False
    finally:
        os.close(parent_fd)


def _require_no_foreign_restore_stage(
    layout: CodingPluginLifecycleStateLayout,
    target: Path,
    backup_id: str,
    *,
    target_present: bool,
) -> None:
    try:
        parent_fd = _open_private_path(layout.private_data_base, target.parent)
    except FileNotFoundError:
        return
    try:
        stage_name = ".arch-restore-" + backup_id + ".staging"
        for name in os.listdir(parent_fd):
            if not (name.startswith(".arch-restore-") and name.endswith(".staging")):
                continue
            if name != stage_name:
                raise ValueError("Coding Arch restore has foreign staging debt")
            if target_present:
                raise ValueError("Coding Arch restore has unsettled staging debt")
    finally:
        os.close(parent_fd)


def _require_restored_tree(
    layout: CodingPluginLifecycleStateLayout,
    target: Path,
    source: CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    target_fd = _open_private_path(layout.private_data_base, target)
    try:
        _verify_files(target_fd, source)
    finally:
        os.close(target_fd)


__all__ = [
    "CodingArchPrivateDataRestoreOwner",
    "CodingArchPrivateDataRestorePlanV1",
    "CodingArchPrivateDataRestoreResultV1",
]
