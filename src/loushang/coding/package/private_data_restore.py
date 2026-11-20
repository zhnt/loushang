"""Explicit offline restore of one retained Coding Arch Installation backup.

The restore owner requires Product removal and a completed deletion receipt.
It never replaces existing private data; a complete existing tree is an exact
replay. Backup expiry and public restore commands remain separate decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal as Literal

from loushang.coding.harness.plugin_management import private_data_restore as _programs
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
)
from loushang.coding.plugin_manager.lifecycle import (
    prepare_coding_plugin_private_tree as _prepare_private_tree,  # noqa: F401
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_backup import (
    read_deleted_restore_source as read_deleted_restore_source,
)
from loushang.harness.plugin_management.private_data_backup import (
    restore_private_archive as restore_private_archive,
)
from loushang.harness.plugin_management.private_data_deletion import (
    latest_deleted_target_receipt as latest_deleted_target_receipt,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._file_consumption import closing_descriptor

from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
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
    _open_private_path,
    _private_io,
    _verify_files,
)
from .private_data_backup import (
    _read_manifest as _read_manifest,
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


_PRIVATE_DATA_PROGRAM_VALUES = {
    "value_01": "Coding Arch restore confirmation is stale",
    "value_02": "Coding Arch restore backup ID is invalid",
    "value_03": "Coding Arch restore plan is foreign",
    "value_04": "Coding Arch restore requires a removed Installation",
    "value_05": "Coding Arch restore Desired revision changed",
    "value_06": "Coding Arch deletion is unfinished",
    "value_07": "Coding Arch restore Installation changed",
    "value_08": "Coding Arch restore lacks completed deletion",
    "value_09": "Coding Arch restore plan evidence changed",
    "value_10": "Coding Arch restore confirmation requires removal",
    "value_11": "Coding Arch restore backup Installation changed",
    "value_12": "Coding Arch restore confirmation lacks deletion",
    "value_13": "Coding Arch restored target is absent",
}


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

        return _programs.confirm(self, key, backup_id)

    def verify_confirmation(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Reopen one confirmation against current Product and restored bytes."""

        return _programs.verify_confirmation(self, key, backup_id, confirmation_id)

    def _current_completed_restore(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> tuple[CodingArchPrivateDataRestoreEventV1, str]:
        return _programs.current_completed_restore(
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

        return _programs.preview(self, key, backup_id)

    def restore(
        self,
        key: PluginInstallationKeyV1,
        backup_id: str,
        *,
        expected_plan: CodingArchPrivateDataRestorePlanV1 | None = None,
    ) -> CodingArchPrivateDataRestoreResultV1:
        """Publish verified backup bytes only into an absent Installation root."""

        return _programs.restore(self, key, backup_id, expected_plan=expected_plan)


def _require_no_foreign_restore_stage(
    layout: CodingPluginLifecycleStateLayout,
    target: Path,
    backup_id: str,
    *,
    target_present: bool,
) -> None:
    _private_io.require_no_foreign_restore_stage(
        layout.private_data_base,
        target,
        stage_name=_RESTORE_STAGE_PREFIX + backup_id + _RESTORE_STAGE_SUFFIX,
        stage_prefix=_RESTORE_STAGE_PREFIX,
        stage_suffix=_RESTORE_STAGE_SUFFIX,
        target_present=target_present,
    )


def _require_restored_tree(
    layout: CodingPluginLifecycleStateLayout,
    target: Path,
    source: CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    with closing_descriptor(
        _open_private_path(layout.private_data_base, target)
    ) as target_fd:
        _verify_files(target_fd, source)


__all__ = [
    "CodingArchPrivateDataRestoreOwner",
    "CodingArchPrivateDataRestorePlanV1",
    "CodingArchPrivateDataRestoreResultV1",
]
