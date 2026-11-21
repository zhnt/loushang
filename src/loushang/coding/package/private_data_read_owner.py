"""Narrow, non-repairing Product owner for offline Arch private-data reads."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from loushang.coding.harness.plugin_management.private_data_backup_expiry import (
    preview_expiry,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout as resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.plugin_management._private_data_custody import (
    assert_private_read_current,
    private_data_read_fence,
    private_read_state_identity,
)
from loushang.harness.plugin_management.assembly import (
    bind_plugin_desired_state,
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
    resolve_coding_package_epoch_layout,
)
from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .private_data_backup import (
    CodingArchPrivateDataBackupReceiptV1,
    _verify_retained_archive,
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
from .private_data_restore import _current_completed_restore, _preview_restore
from .private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal,
    CodingArchPrivateDataRestoreConfirmationV1,
)
from .private_data_restore_journal import CodingArchPrivateDataRestoreEventV1
from .private_data_restore_records import CodingArchPrivateDataRestorePlanV1

_READ_POLICY = JournalLoadPolicy(partial_tail="raise", create_lock=False)


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
        _assert_workspace(workspace, workspace_identity)
        if layout != resolve_coding_plugin_lifecycle_state_layout(workspace):
            raise ValueError("Coding Arch read Product scope changed")
        epoch_layout = resolve_coding_package_epoch_layout(layout)
        epoch = PackageProductPosixFencedRuntimeOwner.open(
            **epoch_layout.fenced_runtime_open_kwargs(), read_only=True
        )
        try:
            _assert_workspace(workspace, workspace_identity)
            state_root = epoch.control_root / "product-state"
            state_identity = private_read_state_identity(
                state_root, message="Coding Arch read Product state is unsafe"
            )
            binding = bind_plugin_desired_state(
                state_root / "gc-reservations.jsonl",
                state_root / "desired-state.jsonl",
                load_policy=_READ_POLICY,
            )
            epoch.assert_current()
            _assert_workspace(workspace, workspace_identity)
            owner = cls(
                layout=layout,
                workspace=workspace,
                workspace_identity=workspace_identity,
                epoch_runtime=epoch,
                state_root=state_root,
                state_identity=state_identity,
                gc_gate=binding.gc_reservations,
                desired_state=binding.desired,
            )
            owner.assert_current()
            return owner
        except BaseException:
            epoch.close()
            raise

    def close(self) -> None:
        self.epoch_runtime.close()

    def verify_backup(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataBackupReceiptV1:
        coding_arch_installation_private_data_root(self.layout, key)
        if not _digest(backup_id):
            raise ValueError("Coding Arch backup ID is invalid")
        with self.offline():
            return _verify_retained_archive(
                self.layout.private_data_base,
                _backup_parent(self.layout, key),
                key,
                backup_id,
            )

    def deletion_preview(
        self, key: PluginInstallationKeyV1
    ) -> PluginPrivateDataDeletionPlanV1:
        root = coding_arch_installation_private_data_root(self.layout, key)
        with self.offline():
            return CodingArchPrivateDataDeletionJournal(self.state_root).preview_plan(
                key,
                owner_id=_OWNER_ID,
                capture_target=lambda: _capture_target_snapshot(
                    root, private_base=self.layout.private_data_base
                ),
            )

    def restore_preview(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataRestorePlanV1:
        root = coding_arch_installation_private_data_root(self.layout, key)
        if not _digest(backup_id):
            raise ValueError("Coding Arch restore backup ID is invalid")
        with self.offline():
            return _preview_restore(
                self.layout,
                self.state_root,
                root,
                key,
                backup_id,
                desired_snapshot=lambda: self.desired_state.capture_read_only()[0],
            )

    def verify_restore_confirmation(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        with self.offline():
            completion, target_id = self._current_completed_restore(key, backup_id)
            return CodingArchPrivateDataRestoreConfirmationJournal(
                self.state_root
            ).require_current(
                confirmation_id,
                key,
                backup_id,
                completion,
                target_id,
                message="Coding Arch restore confirmation is stale",
            )

    def expiry_preview(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataBackupExpiryPlanV1:
        if not _digest(backup_id):
            raise ValueError("Coding Arch backup expiry ID is invalid")
        with self.offline():
            return preview_expiry(
                self.layout,
                self.state_root,
                key,
                backup_id,
                confirmation_id,
                completed_restore=lambda: self._current_completed_restore(
                    key, backup_id
                ),
                desired_snapshot=lambda: self.desired_state.capture_read_only()[0],
            )

    def _current_completed_restore(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> tuple[CodingArchPrivateDataRestoreEventV1, str]:
        return _current_completed_restore(
            self.layout,
            self.state_root,
            key,
            backup_id,
            desired_snapshot=lambda: self.desired_state.capture_read_only()[0],
        )

    def assert_current(self) -> None:
        assert_private_read_current(
            self.epoch_runtime,
            self.workspace,
            self.workspace_identity,
            self.state_root,
            self.state_identity,
            label="Coding Arch",
        )

    @contextmanager
    def offline(self) -> Iterator[None]:
        """Keep runtime and GC references fixed without creating lock files."""

        with private_data_read_fence(
            self.epoch_runtime,
            self.workspace,
            self.workspace_identity,
            self.state_root,
            self.state_identity,
            self.gc_gate,
            self.desired_state,
            label="Coding Arch",
        ):
            yield


def _assert_workspace(workspace: Path, identity: tuple[int, int]) -> None:
    assert_workspace_directory_identity(
        workspace,
        identity,
        changed=lambda: ValueError("Coding Arch read workspace changed"),
    )


__all__ = ["CodingArchPrivateDataReadOwner"]
