"""Explicit offline restore of one retained Coding Arch Installation backup.

The restore owner requires Product removal and a completed deletion receipt.
It never replaces existing private data; a complete existing tree is an exact
replay. Backup expiry and public restore commands remain separate decisions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
)
from loushang.coding.plugin_manager.lifecycle import (
    prepare_coding_plugin_private_tree as _prepare_private_tree,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.private_data_backup import (
    PosixPrivateDataRestore,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .private_data_backup import (
    CodingArchPrivateDataBackupReceiptV1,
    _private_io,
    _verify_files,
)
from .private_data_backup import (
    _archive_codec as _archive_codec,
)
from .private_data_backup import (
    _backup_parent as _backup_parent,
)
from .private_data_backup import (
    _digest as _digest,
)
from .private_data_backup import (
    _write_or_verify_file as _write_or_verify_file,
)
from .private_data_deletion_journal import (
    CodingArchPrivateDataDeletionJournal as CodingArchPrivateDataDeletionJournal,
)
from .private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataTargetSnapshotV1,
)
from .private_data_deletion_preview import (
    _capture_target_snapshot as _capture_target_snapshot,
)
from .private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal as CodingArchPrivateDataRestoreConfirmationJournal,
)
from .private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationV1,
)
from .private_data_restore_journal import (
    CodingArchPrivateDataRestoreEventV1,
)
from .private_data_restore_journal import (
    CodingArchPrivateDataRestoreJournal as CodingArchPrivateDataRestoreJournal,
)
from .private_data_restore_journal import (
    restore_id_for as restore_id_for,
)
from .private_data_restore_records import (
    CodingArchPrivateDataRestorePlanV1,
    CodingArchPrivateDataRestoreResultV1,
)

_RESTORE_STAGE_PREFIX = ".arch-restore-"
_RESTORE_STAGE_SUFFIX = ".staging"


def _archive_restore(
    layout: CodingPluginLifecycleStateLayout,
) -> PosixPrivateDataRestore[
    CodingArchPrivateDataTargetSnapshotV1,
    CodingArchPrivateDataBackupReceiptV1,
]:
    return PosixPrivateDataRestore(
        private_base=layout.private_data_base,
        io=_private_io,
        codec=_archive_codec,
        backup_parent=partial(_backup_parent, layout),
        capture_target=partial(
            _capture_target_snapshot, private_base=layout.private_data_base
        ),
        stage_prefix=_RESTORE_STAGE_PREFIX,
        stage_suffix=_RESTORE_STAGE_SUFFIX,
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
            return journal.record(
                CodingArchPrivateDataRestoreConfirmationV1.create(
                    revision=journal.revision_for(completion.restore_id),
                    installation_key=key,
                    backup_id=backup_id,
                    deletion_receipt_id=completion.deletion_receipt_id,
                    restore_id=completion.restore_id,
                    restore_completion_digest=completion.record_digest,
                    restored_target_id=target_id,
                )
            )

    def verify_confirmation(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Reopen one confirmation against current Product and restored bytes."""

        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            completion, target_id = self._current_completed_restore(key, backup_id)
            return CodingArchPrivateDataRestoreConfirmationJournal(
                self.product.state_root
            ).require_current(
                confirmation_id,
                key,
                backup_id,
                completion,
                target_id,
                message="Coding Arch restore confirmation is stale",
            )

    def _current_completed_restore(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> tuple[CodingArchPrivateDataRestoreEventV1, str]:
        return _current_completed_restore(
            self.layout,
            self.product.state_root,
            key,
            backup_id,
            desired_snapshot=self.product.desired_state.snapshot,
        )

    def preview(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataRestorePlanV1:
        """Read exact Product, archive, and target facts without publishing data."""

        target = coding_arch_installation_private_data_root(self.layout, key)
        if not _digest(backup_id):
            raise ValueError("Coding Arch restore backup ID is invalid")
        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            return _preview_restore(
                self.layout,
                self.product.state_root,
                target,
                key,
                backup_id,
                desired_snapshot=self.product.desired_state.snapshot,
            )

    def restore(
        self,
        key: PluginInstallationKeyV1,
        backup_id: str,
        *,
        expected_plan: CodingArchPrivateDataRestorePlanV1 | None = None,
    ) -> CodingArchPrivateDataRestoreResultV1:
        """Publish verified backup bytes only into an absent Installation root."""

        target = coding_arch_installation_private_data_root(self.layout, key)
        if not _digest(backup_id):
            raise ValueError("Coding Arch restore backup ID is invalid")
        if expected_plan is not None and (
            not isinstance(expected_plan, CodingArchPrivateDataRestorePlanV1)
            or expected_plan.installation_key != key
            or expected_plan.backup_id != backup_id
        ):
            raise ValueError("Coding Arch restore plan is foreign")
        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            deletion = _admit_restore(
                self.product.state_root,
                key,
                self.product.desired_state.snapshot(),
                expected_plan=expected_plan,
            )
            return _archive_restore(self.layout).restore(
                target,
                backup_id,
                key,
                deletion_events=deletion.events,
                expected_archive=(
                    None
                    if expected_plan is None
                    else (
                        expected_plan.source_target_id,
                        expected_plan.deletion_receipt_id,
                    )
                ),
                expected_target_state=(
                    None if expected_plan is None else expected_plan.target_state
                ),
                prepare=_prepare_private_tree,
                verify_files=lambda fd, source: _verify_files(fd, source),
                write_file_factory=lambda: _write_or_verify_file,
                journal_factory=lambda: CodingArchPrivateDataRestoreJournal(
                    self.product.state_root
                ),
                identity_for=restore_id_for,
                result_factory=CodingArchPrivateDataRestoreResultV1,
            )


def _admit_restore(
    state_root: Path,
    key: PluginInstallationKeyV1,
    desired: PluginDesiredStateSnapshotV1,
    *,
    expected_plan: CodingArchPrivateDataRestorePlanV1 | None = None,
    removal_error: str = "Coding Arch restore requires a removed Installation",
) -> CodingArchPrivateDataDeletionJournal:
    if desired.installation(key).selection.desired_state != "absent":
        raise ValueError(removal_error)
    if (
        expected_plan is not None
        and desired.inventory_revision != expected_plan.desired_inventory_revision
    ):
        raise ValueError("Coding Arch restore Desired revision changed")
    deletion = CodingArchPrivateDataDeletionJournal(state_root)
    if deletion.current_start() is not None:
        raise ValueError("Coding Arch deletion is unfinished")
    return deletion


def _current_completed_restore(
    layout: CodingPluginLifecycleStateLayout,
    state_root: Path,
    key: PluginInstallationKeyV1,
    backup_id: str,
    *,
    desired_snapshot: Callable[[], PluginDesiredStateSnapshotV1],
) -> tuple[CodingArchPrivateDataRestoreEventV1, str]:
    if not _digest(backup_id):
        raise ValueError("Coding Arch restore backup ID is invalid")
    deletion = _admit_restore(
        state_root,
        key,
        desired_snapshot(),
        removal_error="Coding Arch restore confirmation requires removal",
    )

    def find_completion(
        deletion_receipt_id: str,
    ) -> CodingArchPrivateDataRestoreEventV1:
        restore_id = restore_id_for(key, backup_id, deletion_receipt_id)
        return CodingArchPrivateDataRestoreJournal(state_root).completed_for(restore_id)

    return _archive_restore(layout).completed(
        backup_id,
        key,
        deletion_events=deletion.events,
        find_completion=find_completion,
        resolve_target=partial(coding_arch_installation_private_data_root, layout, key),
    )


def _preview_restore(
    layout: CodingPluginLifecycleStateLayout,
    state_root: Path,
    root: Path,
    key: PluginInstallationKeyV1,
    backup_id: str,
    *,
    desired_snapshot: Callable[[], PluginDesiredStateSnapshotV1],
) -> CodingArchPrivateDataRestorePlanV1:
    desired = desired_snapshot()
    deletion = _admit_restore(state_root, key, desired)
    source_target_id, deletion_receipt_id, target_state = _archive_restore(layout).preview(
        root, backup_id, key, deletion_events=deletion.events
    )
    return CodingArchPrivateDataRestorePlanV1(
        installation_key=key,
        backup_id=backup_id,
        deletion_receipt_id=deletion_receipt_id,
        source_target_id=source_target_id,
        desired_inventory_revision=desired.inventory_revision,
        target_state=target_state,
    )


__all__ = [
    "CodingArchPrivateDataRestoreOwner",
    "CodingArchPrivateDataRestorePlanV1",
    "CodingArchPrivateDataRestoreResultV1",
]
