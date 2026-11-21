"""Exact offline preview and independently journaled Arch backup expiry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast as cast

from loushang.coding.harness.plugin_management import (
    private_data_backup_expiry as _programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_backup import (
    execute_posix_expiry as execute_posix_expiry,
)
from loushang.harness.plugin_management.private_data_backup import (
    inspect_private_expiry_archive as inspect_private_expiry_archive,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .private_data_backup import _archive_codec as _archive_codec
from .private_data_backup import _backup_parent as _backup_parent
from .private_data_backup import _digest as _digest
from .private_data_backup import _private_io as _private_io
from .private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from .private_data_backup_expiry_records import (
    _tombstone_name as _tombstone_name,
)
from .private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataTargetSnapshotV1,
)
from .private_data_deletion_preview import (
    _capture_target_snapshot as _capture_target_snapshot,
)
from .private_data_restore import (
    CodingArchPrivateDataRestoreOwner as CodingArchPrivateDataRestoreOwner,
)
from .private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal as CodingArchPrivateDataRestoreConfirmationJournal,
)
from .private_data_restore_journal import (
    CodingArchPrivateDataRestoreJournal as CodingArchPrivateDataRestoreJournal,
)

if TYPE_CHECKING:
    from .private_data_backup_expiry_journal import (
        CodingArchPrivateDataBackupExpiryConfirmationV1,
        CodingArchPrivateDataBackupExpiryReceiptV1,
    )


_PRIVATE_DATA_PROGRAM_VALUES = {
    "value_01": "Coding Arch backup expiry ID is invalid",
    "value_02": "Coding Arch backup expiry acceptance is invalid",
    "value_03": "Coding Arch backup expiry restore changed",
    "value_04": "Coding Arch backup expiry archive changed",
    "value_05": "Coding Arch backup expiry Desired State changed",
    "value_06": "Coding Arch backup expiry confirmation changed",
    "value_07": "Coding Arch backup expiry restore history changed",
    "value_08": "Coding Arch backup expiry restored data changed",
    "value_09": "Coding Arch backup expiry confirmation is stale",
    "value_10": "Coding Arch backup expiry requires removal",
    "value_11": "Coding Arch backup expiry Installation changed",
}


_PRIVATE_DATA_ATTESTATION_VALUES = {
    "message_01": "Coding Arch backup expiry plan is required",
    "message_02": "Coding Arch backup expiry plan changed",
}


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupExpiryOwner:
    layout: CodingPluginLifecycleStateLayout
    product: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingArchPrivateDataDeletionPreview(self.layout, self.product)

    def preview(
        self,
        key: PluginInstallationKeyV1,
        backup_id: str,
        confirmation_id: str,
    ) -> CodingArchPrivateDataBackupExpiryPlanV1:
        """Read the exact restore and archive evidence under offline quiescence."""

        return _programs.preview(self, key, backup_id, confirmation_id)

    def confirm(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        """Record independent operator acceptance of one current exact plan."""

        return _programs.confirm(
            self, plan, actor_id=actor_id, policy_revision=policy_revision
        )

    def expire(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
    ) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        """Delete one reviewed archive through durable, offline checkpoints."""

        return _programs.expire(self, plan, confirmation)

    def _require_pre_effect_plan(
        self, plan: CodingArchPrivateDataBackupExpiryPlanV1
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        """Recheck every preview authority while the offline fence is held."""

        return _programs.require_pre_effect_plan(self, plan)

    def _require_recovery_authority(
        self, plan: CodingArchPrivateDataBackupExpiryPlanV1
    ) -> None:
        return _programs.require_recovery_authority(self, plan)


__all__ = [
    "CodingArchPrivateDataBackupExpiryOwner",
    "CodingArchPrivateDataBackupExpiryPlanV1",
]
