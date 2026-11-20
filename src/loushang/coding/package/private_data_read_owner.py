"""Narrow, non-repairing Product owner for offline Arch private-data reads."""

from __future__ import annotations

import os as os
import stat as stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from loushang.coding.harness.plugin_management import private_data_read as _programs
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout as resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.plugin_management.assembly import (
    bind_plugin_desired_state as bind_plugin_desired_state,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.workspace.paths import assert_workspace_directory_identity

from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .private_data_backup import (
    CodingArchPrivateDataBackupReceiptV1,
)
from .private_data_backup import (
    _backup_parent as _backup_parent,
)
from .private_data_backup import (
    _digest as _digest,
)
from .private_data_backup_expiry_records import CodingArchPrivateDataBackupExpiryPlanV1
from .private_data_deletion_journal import (
    CodingArchPrivateDataDeletionJournal as CodingArchPrivateDataDeletionJournal,
)
from .private_data_deletion_preview import _OWNER_ID as _OWNER_ID
from .private_data_deletion_preview import (
    _capture_target_snapshot as _capture_target_snapshot,
)
from .private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationV1,
)
from .private_data_restore_journal import CodingArchPrivateDataRestoreEventV1
from .private_data_restore_records import CodingArchPrivateDataRestorePlanV1

_READ_POLICY = JournalLoadPolicy(partial_tail="raise", create_lock=False)


_PRIVATE_DATA_CUSTODY_VALUES = {
    "message_01": "Coding Arch read Product state changed",
    "message_02": "Coding Arch private-data Product runtime is active",
}


_PRIVATE_DATA_FLOW_VALUES = {
    "message_01": "Coding Arch read Product scope changed",
    "message_02": "Coding Arch read Product state is unsafe",
}


_PRIVATE_DATA_QUERY_VALUES = {
    "message_01": "Coding Arch backup ID is invalid",
    "message_03": "Coding Arch restore confirmation is stale",
    "invalid_restore_backup": "Coding Arch restore backup ID is invalid",
    "invalid_expiry_backup": "Coding Arch backup expiry ID is invalid",
}


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataReadOwner:
    """Hold only the existing epoch, Desired ledger, and quiescence locks."""

    layout: CodingPluginLifecycleStateLayout
    workspace: Path
    workspace_identity: tuple[int, int]
    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    state_root: Path
    state_identity: tuple[int, int]
    gc_gate: PluginPackageGcReservationJournal
    desired_state: PluginDesiredStateLedger

    @classmethod
    def open(
        cls,
        *,
        layout: CodingPluginLifecycleStateLayout,
        workspace: Path,
        workspace_identity: tuple[int, int],
    ) -> CodingArchPrivateDataReadOwner:
        return _programs.open_read_scope(
            cls,
            layout=layout,
            workspace=workspace,
            workspace_identity=workspace_identity,
        )

    def close(self) -> None:
        self.epoch_runtime.close()

    def verify_backup(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataBackupReceiptV1:
        return _programs.verify_backup(self, key, backup_id)

    def deletion_preview(
        self, key: PluginInstallationKeyV1
    ) -> PluginPrivateDataDeletionPlanV1:
        return _programs.deletion_preview(self, key)

    def restore_preview(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataRestorePlanV1:
        return _programs.restore_preview(self, key, backup_id)

    def verify_restore_confirmation(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        return _programs.verify_restore_confirmation(
            self, key, backup_id, confirmation_id
        )

    def expiry_preview(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataBackupExpiryPlanV1:
        return _programs.expiry_preview(self, key, backup_id, confirmation_id)

    def _current_completed_restore(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> tuple[CodingArchPrivateDataRestoreEventV1, str]:
        return _programs.current_completed_restore(self, key, backup_id)

    def assert_current(self) -> None:
        return _programs.assert_current(self)

    @contextmanager
    def offline(self) -> Iterator[None]:
        """Keep runtime and GC references fixed without creating lock files."""

        with _programs.offline(self) as borrowed:
            yield borrowed


def _assert_workspace(workspace: Path, identity: tuple[int, int]) -> None:
    assert_workspace_directory_identity(
        workspace,
        identity,
        changed=lambda: ValueError("Coding Arch read workspace changed"),
    )


__all__ = ["CodingArchPrivateDataReadOwner"]
