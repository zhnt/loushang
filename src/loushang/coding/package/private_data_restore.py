"""Explicit offline restore of one retained Coding Arch Installation backup.

The restore owner requires Product removal and a completed deletion receipt.
It never replaces existing private data; a complete existing tree is an exact
replay. Backup expiry and public restore commands remain separate decisions.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
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


_CodingArchiveRestore = PosixPrivateDataRestore[
    CodingArchPrivateDataTargetSnapshotV1,
    CodingArchPrivateDataBackupReceiptV1,
    CodingArchPrivateDataRestoreEventV1,
]


def _archive_restore(
    layout: CodingPluginLifecycleStateLayout,
    state_root: Path,
    desired_snapshot: Callable[[], PluginDesiredStateSnapshotV1],
) -> _CodingArchiveRestore:
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
        desired_snapshot=desired_snapshot,
        deletion_journal=lambda: CodingArchPrivateDataDeletionJournal(state_root),
        restore_journal=lambda: CodingArchPrivateDataRestoreJournal(state_root),
        identity_for=restore_id_for,
        resolve_target=partial(coding_arch_installation_private_data_root, layout),
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
            return self._archive().confirm(
                key,
                backup_id,
                confirmation_journal=self._confirmation_journal,
                create_confirmation=CodingArchPrivateDataRestoreConfirmationV1.create,
            )

    def verify_confirmation(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Reopen one confirmation against current Product and restored bytes."""

        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            return self._archive().verify_confirmation(
                key, backup_id, confirmation_id, confirmation_journal=self._confirmation_journal
            )

    def _archive(self) -> _CodingArchiveRestore:
        return _archive_restore(self.layout, self.product.state_root, self.product.desired_state.snapshot)

    def _confirmation_journal(self) -> CodingArchPrivateDataRestoreConfirmationJournal:
        return CodingArchPrivateDataRestoreConfirmationJournal(self.product.state_root)

    def preview(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataRestorePlanV1:
        """Read exact Product, archive, and target facts without publishing data."""

        return _preview_restore(
            self.layout,
            key,
            backup_id,
            archive=self._archive,
            offline=lambda: CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline(),
        )

    def restore(
        self,
        key: PluginInstallationKeyV1,
        backup_id: str,
        *,
        expected_plan: CodingArchPrivateDataRestorePlanV1 | None = None,
    ) -> CodingArchPrivateDataRestoreResultV1:
        """Publish verified backup bytes only into an absent Installation root."""
        return self._restore(key, backup_id, expected_plan=expected_plan)

    def _restore(
        self,
        key: PluginInstallationKeyV1,
        backup_id: str,
        *,
        expected_plan: CodingArchPrivateDataRestorePlanV1 | None,
        operator_submission: bool = False,
    ) -> CodingArchPrivateDataRestoreResultV1:
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
            return self._archive().restore(
                target,
                backup_id,
                key,
                expected_plan=expected_plan,
                prepare=_prepare_private_tree,
                result_factory=CodingArchPrivateDataRestoreResultV1,
                operator_submission=operator_submission,
            )


def _preview_restore(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    backup_id: str,
    *,
    archive: Callable[[], _CodingArchiveRestore],
    offline: Callable[[], AbstractContextManager[None]],
) -> CodingArchPrivateDataRestorePlanV1:
    root = coding_arch_installation_private_data_root(layout, key)
    if not _digest(backup_id):
        raise ValueError("Coding Arch restore backup ID is invalid")
    with offline():
        return archive().preview(root, backup_id, key, create_plan=CodingArchPrivateDataRestorePlanV1)


__all__ = [
    "CodingArchPrivateDataRestoreOwner",
    "CodingArchPrivateDataRestorePlanV1",
    "CodingArchPrivateDataRestoreResultV1",
]
