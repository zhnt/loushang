"""Complete private-data programs using existing storage/history owners.

Temporary Product binding imports preserve original nominal and fault seams;
they are tracked intermediate dependencies, not final Harness neutrality.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from loushang.coding.package import private_data_restore as _binding
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1

from . import private_data_restore_confirmation


def confirm(
    self: _binding.CodingArchPrivateDataRestoreOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
) -> _binding.CodingArchPrivateDataRestoreConfirmationV1:
    """Durably confirm exact restored bytes after completion, by request."""

    with _binding.CodingArchPrivateDataDeletionPreview(
        self.layout, self.product
    )._offline():
        completion, target_id = self._current_completed_restore(key, backup_id)
        journal = _binding.CodingArchPrivateDataRestoreConfirmationJournal(
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
        confirmation = _binding.CodingArchPrivateDataRestoreConfirmationV1.create(
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
    self: _binding.CodingArchPrivateDataRestoreOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    confirmation_id: str,
) -> _binding.CodingArchPrivateDataRestoreConfirmationV1:
    """Reopen one confirmation against current Product and restored bytes."""

    with _binding.CodingArchPrivateDataDeletionPreview(
        self.layout, self.product
    )._offline():
        completion, target_id = self._current_completed_restore(key, backup_id)
        return private_data_restore_confirmation.require_current_confirmation(
            self.product.state_root,
            confirmation_id,
            key,
            backup_id,
            completion,
            target_id,
            message=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_01"],
        )


def preview(
    self: _binding.CodingArchPrivateDataRestoreOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
) -> _binding.CodingArchPrivateDataRestorePlanV1:
    """Read exact Product, archive, and target facts without publishing data."""

    source_root = _binding.coding_arch_installation_private_data_root(self.layout, key)
    if not _binding._digest(backup_id):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_02"])
    with _binding.CodingArchPrivateDataDeletionPreview(
        self.layout, self.product
    )._offline():
        return preview_restore(
            self.layout,
            self.product.state_root,
            source_root,
            key,
            backup_id,
            desired_snapshot=self.product.desired_state.snapshot,
        )


def restore(
    self: _binding.CodingArchPrivateDataRestoreOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    *,
    expected_plan: _binding.CodingArchPrivateDataRestorePlanV1 | None = None,
) -> _binding.CodingArchPrivateDataRestoreResultV1:
    """Publish verified backup bytes only into an absent Installation root."""

    source_root = _binding.coding_arch_installation_private_data_root(self.layout, key)
    if not _binding._digest(backup_id):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_02"])
    if expected_plan is not None and (
        not isinstance(expected_plan, _binding.CodingArchPrivateDataRestorePlanV1)
        or expected_plan.installation_key != key
        or expected_plan.backup_id != backup_id
    ):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_03"])
    preview = _binding.CodingArchPrivateDataDeletionPreview(self.layout, self.product)
    with preview._offline():
        desired = self.product.desired_state.snapshot()
        if desired.installation(key).selection.desired_state != "absent":
            raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_04"])
        if (
            expected_plan is not None
            and desired.inventory_revision != expected_plan.desired_inventory_revision
        ):
            raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_05"])
        deletion = _binding.CodingArchPrivateDataDeletionJournal(
            self.product.state_root
        )
        if deletion.current_start() is not None:
            raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_06"])
        with _binding.closing_descriptor(
            _binding._open_private_path(
                self.layout.private_data_base, _binding._backup_parent(self.layout, key)
            )
        ) as backup_parent_fd:
            receipt, source = _binding._read_manifest(backup_parent_fd, backup_id)
            if receipt.installation_key != key or receipt.backup_id != backup_id:
                raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_07"])
            deletion_receipt = _binding.latest_deleted_target_receipt(
                deletion.events(), key, receipt.source_target_id
            )
            if deletion_receipt is None:
                raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_08"])
            if expected_plan is not None and (
                expected_plan.source_target_id != source.target_id
                or expected_plan.deletion_receipt_id != deletion_receipt.receipt_id
            ):
                raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_09"])
            return _binding.restore_private_archive(
                backup_parent_fd,
                backup_id,
                key,
                source,
                receipt,
                deletion_receipt,
                target=source_root,
                private_base=self.layout.private_data_base,
                io=_binding._private_io,
                codec=_binding._archive_codec,
                expected_target_state=(
                    None if expected_plan is None else expected_plan.target_state
                ),
                stage_prefix=_binding._RESTORE_STAGE_PREFIX,
                stage_suffix=_binding._RESTORE_STAGE_SUFFIX,
                prepare=lambda path, *, private_base, label: (
                    _binding._prepare_private_tree(
                        path, private_base=private_base, label=label
                    )
                ),
                verify_files=lambda fd, source: _binding._verify_files(fd, source),
                write_file_factory=lambda: _binding._write_or_verify_file,
                journal_factory=lambda: _binding.CodingArchPrivateDataRestoreJournal(
                    self.product.state_root
                ),
                identity_for=lambda key, name, deletion: _binding.restore_id_for(
                    key, name, deletion
                ),
                result_factory=lambda name, disposition, identity: (
                    _binding.CodingArchPrivateDataRestoreResultV1(
                        name, disposition, identity
                    )
                ),
            )


def current_completed_restore(
    layout: _binding.CodingPluginLifecycleStateLayout,
    state_root: _binding.Path,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    *,
    desired_snapshot: Callable[[], PluginDesiredStateSnapshotV1],
) -> tuple[_binding.CodingArchPrivateDataRestoreEventV1, str]:
    if not _binding._digest(backup_id):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_02"])
    desired = desired_snapshot()
    if desired.installation(key).selection.desired_state != "absent":
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_10"])
    deletion = _binding.CodingArchPrivateDataDeletionJournal(state_root)
    if deletion.current_start() is not None:
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_06"])
    source, deletion_receipt = _binding.read_deleted_restore_source(
        layout.private_data_base,
        _binding._backup_parent(layout, key),
        backup_id,
        key,
        io=_binding._private_io,
        codec=_binding._archive_codec,
        deletion_events=lambda: deletion.events(),
        installation_error=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_11"],
        deletion_error=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_12"],
    )
    completion_id = _binding.restore_id_for(key, backup_id, deletion_receipt.receipt_id)
    completion = _binding.CodingArchPrivateDataRestoreJournal(state_root).completed_for(
        completion_id
    )
    source_root = _binding.coding_arch_installation_private_data_root(layout, key)
    _binding._require_restored_tree(layout, source_root, source)
    target = _binding._capture_target_snapshot(
        source_root, private_base=layout.private_data_base
    )
    if target.root_identity is None:
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_13"])
    return completion, target.target_id


def preview_restore(
    layout: _binding.CodingPluginLifecycleStateLayout,
    state_root: _binding.Path,
    source_root: _binding.Path,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    *,
    desired_snapshot: Callable[[], PluginDesiredStateSnapshotV1],
) -> _binding.CodingArchPrivateDataRestorePlanV1:
    desired = desired_snapshot()
    if desired.installation(key).selection.desired_state != "absent":
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_04"])
    deletion = _binding.CodingArchPrivateDataDeletionJournal(state_root)
    if deletion.current_start() is not None:
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_06"])
    source, deletion_receipt = _binding.read_deleted_restore_source(
        layout.private_data_base,
        _binding._backup_parent(layout, key),
        backup_id,
        key,
        io=_binding._private_io,
        codec=_binding._archive_codec,
        deletion_events=lambda: deletion.events(),
        installation_error=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_07"],
        deletion_error=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_08"],
    )
    current = _binding._capture_target_snapshot(
        source_root, private_base=layout.private_data_base
    )
    if current.root_identity is None:
        target_state: Literal["absent", "same_bytes"] = "absent"
    else:
        _binding._require_restored_tree(layout, source_root, source)
        target_state = "same_bytes"
    _binding._require_no_foreign_restore_stage(
        layout,
        source_root,
        backup_id,
        target_present=target_state == "same_bytes",
    )
    return _binding.CodingArchPrivateDataRestorePlanV1(
        installation_key=key,
        backup_id=backup_id,
        deletion_receipt_id=deletion_receipt.receipt_id,
        source_target_id=source.target_id,
        desired_inventory_revision=desired.inventory_revision,
        target_state=target_state,
    )
