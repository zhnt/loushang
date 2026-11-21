"""Private-data observation and receipt programs over original authorities.

Product identities, exact policies and nominal values remain borrowed
intermediate dependencies; no new persistence or repair owner is created.
"""

from __future__ import annotations

from loushang.coding.package import (
    private_data_windows_backup_expiry_preview as _binding,
)


def preview_locked(
    self: _binding.CodingWindowsArchPrivateDataBackupExpiryPreview,
    transaction: _binding.CodingWindowsArchPrivateDataRestoreTransaction,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
    confirmation_id: str,
) -> _binding.CodingArchPrivateDataBackupExpiryPlanV1:
    _binding.coding_arch_installation_private_data_root(self.layout, key)
    if (
        not _binding._digest(backup_id)
        or not isinstance(confirmation_id, str)
        or not confirmation_id.startswith(
            _binding._PRIVATE_DATA_FLOW_VALUES["message_07"]
        )
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
    desired = self.product.desired_state.snapshot()
    state = desired.installation(key)
    if (
        state.latest_instance_revision_ref is None
        or state.selection.desired_state != "absent"
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_02"])
    parent_path = _binding.backup_parent(self.layout, key)
    parent_identity = _binding.inspect_windows_product_private_directory_identity(
        parent_path
    )
    with _binding.WindowsPrivateDirectoryAcl() as acl:
        with _binding._archive_io._parent_scope(
            parent_path,
            parent_identity,
            acl,
            changed=_binding._PRIVATE_DATA_FLOW_VALUES["message_08"],
        ) as parent_fd:
            if any(
                name.endswith(".staging")
                for name in _binding.windows_listdir_at(parent_fd)
            ):
                raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_08"])
            receipt, source = _binding._read_archive_manifest(parent_fd, backup_id, acl)
            if receipt.installation_key != key or receipt.backup_id != backup_id:
                raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_09"])
    deletion = _binding.CodingWindowsArchPrivateDataDeletionTransaction(
        self.product.state_root, transaction.state_fd
    )
    try:
        events = deletion.events()
    finally:
        deletion._close()
    if events and events[-1].phase != "completed":
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_03"])
    deletion_receipt = _binding.latest_deleted_target_receipt(
        events, key, receipt.source_target_id
    )
    if deletion_receipt is None:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_04"])
    restore_plan = _binding.CodingArchPrivateDataRestorePlanV1(
        installation_key=key,
        backup_id=backup_id,
        deletion_receipt_id=deletion_receipt.receipt_id,
        source_target_id=source.target_id,
        desired_inventory_revision=desired.inventory_revision,
        target_state="absent",
    )
    restore_plan = _binding.replace(
        restore_plan,
        desired_inventory_revision=(
            transaction.completed_plan_revision_for(restore_plan)
        ),
    )
    confirmation = transaction.verify_confirmation(restore_plan, confirmation_id)
    completion, restored = transaction._completed_restore(restore_plan)
    archive = _binding.capture_windows_arch_backup_archive(
        self.layout, key, backup_id, source, receipt
    )
    if archive.root_identity is None:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_05"])
    if transaction.verify_confirmation(restore_plan, confirmation_id) != confirmation:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_06"])
    return _binding.CodingArchPrivateDataBackupExpiryPlanV1(
        installation_key=key,
        backup_id=backup_id,
        backup_receipt_id=receipt.receipt_id,
        source_target_id=source.target_id,
        confirmation_id=confirmation.confirmation_id,
        restore_completion_digest=completion.record_digest,
        restored_target_id=restored.target_id,
        desired_inventory_revision=desired.inventory_revision,
        archive_root_identity=archive.root_identity,
        archive_target_id=archive.target_id,
    )
