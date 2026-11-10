"""Narrow, non-repairing Product owner for offline Arch private-data reads."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.plugin_management.assembly import bind_plugin_desired_state
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._file_consumption import closing_descriptor
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_backup import (
    CodingArchPrivateDataBackupReceiptV1,
    _backup_parent,
    _digest,
    _open_private_path,
    _read_manifest,
    _verify_archive,
)
from .package_private_data_backup_expiry import (
    CodingArchPrivateDataBackupExpiryPlanV1,
    _expiry_preview,
)
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionJournal,
)
from .package_private_data_deletion_preview import (
    _OWNER_ID,
    _capture_target_snapshot,
)
from .package_private_data_restore import (
    CodingArchPrivateDataRestorePlanV1,
    _current_completed_restore,
    _restore_preview,
)
from .package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal,
    CodingArchPrivateDataRestoreConfirmationV1,
    _require_restore_confirmation,
)
from .package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreEventV1,
)

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
            metadata = state_root.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) & 0o077
                or metadata.st_uid != os.geteuid()
            ):
                raise ValueError("Coding Arch read Product state is unsafe")
            desired_binding = bind_plugin_desired_state(
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
                state_identity=(metadata.st_dev, metadata.st_ino),
                gc_gate=desired_binding.gc_reservations,
                desired_state=desired_binding.desired,
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
            with closing_descriptor(
                _open_private_path(
                    self.layout.private_data_base, _backup_parent(self.layout, key)
                )
            ) as parent_fd:
                receipt, source = _read_manifest(parent_fd, backup_id)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Coding Arch backup Installation changed")
                _verify_archive(parent_fd, backup_id, key, source, receipt)
                return receipt

    def deletion_preview(
        self, key: PluginInstallationKeyV1
    ) -> PluginPrivateDataDeletionPlanV1:
        root = coding_arch_installation_private_data_root(self.layout, key)
        with self.offline():
            pending = CodingArchPrivateDataDeletionJournal(
                self.state_root
            ).current_start()
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

    def restore_preview(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataRestorePlanV1:
        source_root = coding_arch_installation_private_data_root(self.layout, key)
        if not _digest(backup_id):
            raise ValueError("Coding Arch restore backup ID is invalid")
        with self.offline():
            return _restore_preview(
                self.layout,
                self.state_root,
                source_root,
                key,
                backup_id,
                desired_snapshot=lambda: self.desired_state.capture_read_only()[0],
            )

    def verify_restore_confirmation(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        with self.offline():
            completion, target_id = self._current_completed_restore(key, backup_id)
            records = CodingArchPrivateDataRestoreConfirmationJournal(
                self.state_root
            ).records()
            matched = _require_restore_confirmation(
                records,
                confirmation_id,
                key,
                backup_id,
                completion,
                target_id,
                message="Coding Arch restore confirmation is stale",
            )
            return matched

    def expiry_preview(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataBackupExpiryPlanV1:
        if not _digest(backup_id):
            raise ValueError("Coding Arch backup expiry ID is invalid")
        with self.offline():
            return _expiry_preview(
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
        _assert_workspace(self.workspace, self.workspace_identity)
        self.epoch_runtime.assert_current()
        metadata = self.state_root.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_uid != os.geteuid()
            or (metadata.st_dev, metadata.st_ino) != self.state_identity
        ):
            raise ValueError("Coding Arch read Product state changed")

    @contextmanager
    def offline(self) -> Iterator[None]:
        """Keep runtime and GC references fixed without creating lock files."""

        self.assert_current()
        registry = self.epoch_runtime.registry
        with registry.exclusive_runtime_quiescence(
            store_id=registry.store_id, read_only=True
        ) as quiescence:
            if quiescence.active_runtime_lease_ids:
                raise ValueError("Coding Arch private-data Product runtime is active")
            self.assert_current()
            with self.gc_gate.read_guard():
                self.assert_current()
                self.desired_state.capture_read_only()
                try:
                    yield
                finally:
                    self.assert_current()


def _assert_workspace(workspace: Path, identity: tuple[int, int]) -> None:
    try:
        metadata = workspace.lstat()
        resolved = workspace.resolve(strict=True)
    except OSError as error:
        raise ValueError("Coding Arch read workspace changed") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or resolved != workspace
        or (metadata.st_dev, metadata.st_ino) != identity
    ):
        raise ValueError("Coding Arch read workspace changed")


__all__ = ["CodingArchPrivateDataReadOwner"]
