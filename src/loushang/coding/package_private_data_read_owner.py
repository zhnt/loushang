"""Narrow, non-repairing Product owner for offline Arch private-data reads."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.journal import JournalLoadPolicy
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
    _open_private_dir,
    _open_private_path,
    _read_manifest,
    _verify_archive,
)
from .package_private_data_backup_expiry import (
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionJournal,
)
from .package_private_data_deletion_preview import (
    _OWNER_ID,
    _capture_target_snapshot,
    _identity,
)
from .package_private_data_restore import (
    CodingArchPrivateDataRestorePlanV1,
    _matching_latest_deletion,
    _require_no_foreign_restore_stage,
    _require_restored_tree,
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
            authority_root=epoch_layout.authority_root,
            control_root=epoch_layout.control_root,
            store_id=epoch_layout.store_id,
            epochs_root_name=epoch_layout.epochs_root_name,
            read_only=True,
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
            gate = PluginPackageGcReservationJournal(
                state_root / "gc-reservations.jsonl", load_policy=_READ_POLICY
            )
            desired = PluginDesiredStateLedger(
                state_root / "desired-state.jsonl",
                gc_gate=gate,
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
                gc_gate=gate,
                desired_state=desired,
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
            parent_fd = _open_private_path(
                self.layout.private_data_base, _backup_parent(self.layout, key)
            )
            try:
                receipt, source = _read_manifest(parent_fd, backup_id)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Coding Arch backup Installation changed")
                _verify_archive(parent_fd, backup_id, key, source, receipt)
                return receipt
            finally:
                os.close(parent_fd)

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
            desired, _ = self.desired_state.capture_read_only()
            if desired.installation(key).selection.desired_state != "absent":
                raise ValueError("Coding Arch restore requires a removed Installation")
            deletion = CodingArchPrivateDataDeletionJournal(self.state_root)
            if deletion.current_start() is not None:
                raise ValueError("Coding Arch deletion is unfinished")
            parent_fd = _open_private_path(
                self.layout.private_data_base, _backup_parent(self.layout, key)
            )
            try:
                receipt, source = _read_manifest(parent_fd, backup_id)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Coding Arch restore Installation changed")
                deletion_receipt = _matching_latest_deletion(deletion, key, receipt)
                if deletion_receipt is None:
                    raise ValueError("Coding Arch restore lacks completed deletion")
                _verify_archive(parent_fd, backup_id, key, source, receipt)
            finally:
                os.close(parent_fd)
            current = _capture_target_snapshot(
                source_root, private_base=self.layout.private_data_base
            )
            target_state: Literal["absent", "same_bytes"]
            if current.root_identity is None:
                target_state = "absent"
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

    def verify_restore_confirmation(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        with self.offline():
            completion, target_id = self._current_completed_restore(key, backup_id)
            records = CodingArchPrivateDataRestoreConfirmationJournal(
                self.state_root
            ).records()
            matched = next(
                (item for item in reversed(records) if item.confirmation_id == confirmation_id),
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

    def expiry_preview(
        self, key: PluginInstallationKeyV1, backup_id: str, confirmation_id: str
    ) -> CodingArchPrivateDataBackupExpiryPlanV1:
        if not _digest(backup_id):
            raise ValueError("Coding Arch backup expiry ID is invalid")
        with self.offline():
            completion, target_id = self._current_completed_restore(key, backup_id)
            confirmations = CodingArchPrivateDataRestoreConfirmationJournal(
                self.state_root
            ).records()
            confirmation = next(
                (
                    item
                    for item in reversed(confirmations)
                    if item.confirmation_id == confirmation_id
                ),
                None,
            )
            if (
                confirmation is None
                or confirmation.installation_key != key
                or confirmation.backup_id != backup_id
                or confirmation.restore_id != completion.restore_id
                or confirmation.deletion_receipt_id != completion.deletion_receipt_id
                or confirmation.restore_completion_digest != completion.record_digest
                or confirmation.restored_target_id != target_id
            ):
                raise ValueError("Coding Arch backup expiry confirmation is stale")
            desired, _ = self.desired_state.capture_read_only()
            if desired.installation(key).selection.desired_state != "absent":
                raise ValueError("Coding Arch backup expiry requires removal")
            parent_fd = _open_private_path(
                self.layout.private_data_base, _backup_parent(self.layout, key)
            )
            try:
                receipt, source = _read_manifest(parent_fd, backup_id)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Coding Arch backup expiry Installation changed")
                _verify_archive(parent_fd, backup_id, key, source, receipt)
                archive_fd = _open_private_dir(parent_fd, backup_id)
                try:
                    identity = _identity(os.fstat(archive_fd))
                    if identity != _identity(
                        os.stat(backup_id, dir_fd=parent_fd, follow_symlinks=False)
                    ):
                        raise ValueError("Coding Arch backup expiry archive changed")
                finally:
                    os.close(archive_fd)
            finally:
                os.close(parent_fd)
            archive_snapshot = _capture_target_snapshot(
                _backup_parent(self.layout, key) / backup_id,
                private_base=self.layout.private_data_base,
            )
            if (
                archive_snapshot.root_identity != identity
                or archive_snapshot.root_identity is None
            ):
                raise ValueError("Coding Arch backup expiry archive changed")
            return CodingArchPrivateDataBackupExpiryPlanV1(
                installation_key=key,
                backup_id=backup_id,
                backup_receipt_id=receipt.receipt_id,
                source_target_id=source.target_id,
                confirmation_id=confirmation.confirmation_id,
                restore_completion_digest=completion.record_digest,
                restored_target_id=target_id,
                desired_inventory_revision=desired.inventory_revision,
                archive_root_identity=identity,
                archive_target_id=archive_snapshot.target_id,
            )

    def _current_completed_restore(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> tuple[CodingArchPrivateDataRestoreEventV1, str]:
        if not _digest(backup_id):
            raise ValueError("Coding Arch restore backup ID is invalid")
        desired, _ = self.desired_state.capture_read_only()
        if desired.installation(key).selection.desired_state != "absent":
            raise ValueError("Coding Arch restore confirmation requires removal")
        deletion = CodingArchPrivateDataDeletionJournal(self.state_root)
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
        events = CodingArchPrivateDataRestoreJournal(self.state_root).events()
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
