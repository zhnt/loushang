"""Explicit offline restore of one retained Coding Arch Installation backup.

The restore owner requires Product removal and a completed deletion receipt.
It never replaces existing private data; a complete existing tree is an exact
replay. Backup expiry and public restore commands remain separate decisions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.private_data_backup import (
    read_deleted_restore_source,
    restore_private_archive,
)
from loushang.harness.plugin_management.private_data_deletion import (
    latest_deleted_target_receipt,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._file_consumption import closing_descriptor

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout, _prepare_private_tree
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_backup import (
    _archive_codec,
    _backup_parent,
    _digest,
    _open_private_path,
    _private_io,
    _read_manifest,
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
)
from .package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal,
    CodingArchPrivateDataRestoreConfirmationV1,
    _require_restore_confirmation,
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

_RESTORE_STAGE_PREFIX = ".arch-restore-"
_RESTORE_STAGE_SUFFIX = ".staging"


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

        source_root = coding_arch_installation_private_data_root(self.layout, key)
        if not _digest(backup_id):
            raise ValueError("Coding Arch restore backup ID is invalid")
        with CodingArchPrivateDataDeletionPreview(self.layout, self.product)._offline():
            return _restore_preview(
                self.layout,
                self.product.state_root,
                source_root,
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
            with closing_descriptor(
                _open_private_path(
                    self.layout.private_data_base, _backup_parent(self.layout, key)
                )
            ) as backup_parent_fd:
                receipt, source = _read_manifest(backup_parent_fd, backup_id)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Coding Arch restore Installation changed")
                deletion_receipt = latest_deleted_target_receipt(
                    deletion.events(), key, receipt.source_target_id
                )
                if deletion_receipt is None:
                    raise ValueError("Coding Arch restore lacks completed deletion")
                if expected_plan is not None and (
                    expected_plan.source_target_id != source.target_id
                    or expected_plan.deletion_receipt_id != deletion_receipt.receipt_id
                ):
                    raise ValueError("Coding Arch restore plan evidence changed")
                return restore_private_archive(
                    backup_parent_fd,
                    backup_id,
                    key,
                    source,
                    receipt,
                    deletion_receipt,
                    target=source_root,
                    private_base=self.layout.private_data_base,
                    io=_private_io,
                    codec=_archive_codec,
                    expected_target_state=(
                        None if expected_plan is None else expected_plan.target_state
                    ),
                    stage_prefix=_RESTORE_STAGE_PREFIX,
                    stage_suffix=_RESTORE_STAGE_SUFFIX,
                    prepare=lambda path, *, private_base, label: _prepare_private_tree(
                        path, private_base=private_base, label=label
                    ),
                    verify_files=lambda fd, source: _verify_files(fd, source),
                    write_file_factory=lambda: _write_or_verify_file,
                    journal_factory=lambda: CodingArchPrivateDataRestoreJournal(
                        self.product.state_root
                    ),
                    identity_for=lambda key, name, deletion: restore_id_for(
                        key, name, deletion
                    ),
                    result_factory=lambda name, disposition, identity: (
                        CodingArchPrivateDataRestoreResultV1(
                            name, disposition, identity
                        )
                    ),
                )


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
    desired = desired_snapshot()
    if desired.installation(key).selection.desired_state != "absent":
        raise ValueError("Coding Arch restore confirmation requires removal")
    deletion = CodingArchPrivateDataDeletionJournal(state_root)
    if deletion.current_start() is not None:
        raise ValueError("Coding Arch deletion is unfinished")
    source, deletion_receipt = read_deleted_restore_source(
        layout.private_data_base,
        _backup_parent(layout, key),
        backup_id,
        key,
        io=_private_io,
        codec=_archive_codec,
        deletion_events=lambda: deletion.events(),
        installation_error="Coding Arch restore backup Installation changed",
        deletion_error="Coding Arch restore confirmation lacks deletion",
    )
    completion_id = restore_id_for(key, backup_id, deletion_receipt.receipt_id)
    completion = CodingArchPrivateDataRestoreJournal(state_root).completed_for(
        completion_id
    )
    source_root = coding_arch_installation_private_data_root(layout, key)
    _require_restored_tree(layout, source_root, source)
    target = _capture_target_snapshot(
        source_root, private_base=layout.private_data_base
    )
    if target.root_identity is None:
        raise ValueError("Coding Arch restored target is absent")
    return completion, target.target_id


def _restore_preview(
    layout: CodingPluginLifecycleStateLayout,
    state_root: Path,
    source_root: Path,
    key: PluginInstallationKeyV1,
    backup_id: str,
    *,
    desired_snapshot: Callable[[], PluginDesiredStateSnapshotV1],
) -> CodingArchPrivateDataRestorePlanV1:
    desired = desired_snapshot()
    if desired.installation(key).selection.desired_state != "absent":
        raise ValueError("Coding Arch restore requires a removed Installation")
    deletion = CodingArchPrivateDataDeletionJournal(state_root)
    if deletion.current_start() is not None:
        raise ValueError("Coding Arch deletion is unfinished")
    source, deletion_receipt = read_deleted_restore_source(
        layout.private_data_base,
        _backup_parent(layout, key),
        backup_id,
        key,
        io=_private_io,
        codec=_archive_codec,
        deletion_events=lambda: deletion.events(),
        installation_error="Coding Arch restore Installation changed",
        deletion_error="Coding Arch restore lacks completed deletion",
    )
    current = _capture_target_snapshot(
        source_root, private_base=layout.private_data_base
    )
    if current.root_identity is None:
        target_state: Literal["absent", "same_bytes"] = "absent"
    else:
        _require_restored_tree(layout, source_root, source)
        target_state = "same_bytes"
    _require_no_foreign_restore_stage(
        layout,
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
