"""Private-data observation and receipt programs over original authorities.

Product identities, exact policies and nominal values remain borrowed
intermediate dependencies; no new persistence or repair owner is created.
"""

from __future__ import annotations

from loushang.coding.package import (
    private_data_windows_backup_expiry_recovery as _binding,
)


def require_expiry_recovery_authority(
    layout: _binding.CodingPluginLifecycleStateLayout,
    product: _binding.WindowsLocalWheelProductSessionOwner,
    restore: _binding.CodingWindowsArchPrivateDataRestoreTransaction,
    plan: _binding.CodingArchPrivateDataBackupExpiryPlanV1,
) -> None:
    """Verify immutable history and current restored bytes after archive rename."""

    if not isinstance(plan, _binding.CodingArchPrivateDataBackupExpiryPlanV1):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
    root = _binding.coding_arch_installation_private_data_root(
        layout, plan.installation_key
    )
    restore._require_active()
    desired = product.desired_state.snapshot()
    installation = desired.installation(plan.installation_key)
    if (
        desired.inventory_revision != plan.desired_inventory_revision
        or installation.latest_instance_revision_ref is None
        or installation.selection.desired_state != "absent"
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_02"])

    deletion = _binding.CodingWindowsArchPrivateDataDeletionTransaction(
        product.state_root, restore.state_fd
    )
    try:
        deletion_events = deletion.events()
    finally:
        deletion._close()
    deletion_receipt = _binding.latest_deleted_target_receipt(
        deletion_events, plan.installation_key, plan.source_target_id
    )
    if deletion_receipt is None:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_03"])

    confirmations, staged = restore._scan_confirmations()
    confirmation = next(
        (
            item
            for item in reversed(confirmations)
            if item.confirmation_id == plan.confirmation_id
        ),
        None,
    )
    if (
        staged is not None
        or confirmation is None
        or confirmation.installation_key != plan.installation_key
        or confirmation.backup_id != plan.backup_id
        or confirmation.deletion_receipt_id != deletion_receipt.receipt_id
        or confirmation.restore_completion_digest != plan.restore_completion_digest
        or confirmation.restored_target_id != plan.restored_target_id
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_04"])

    restore_plan = _binding.CodingArchPrivateDataRestorePlanV1(
        installation_key=plan.installation_key,
        backup_id=plan.backup_id,
        deletion_receipt_id=confirmation.deletion_receipt_id,
        source_target_id=plan.source_target_id,
        desired_inventory_revision=plan.desired_inventory_revision,
        target_state="absent",
    )
    restore_events = restore.events()
    completion = restore_events[-1] if restore_events else None
    started = restore_events[-2] if len(restore_events) >= 2 else None
    if (
        completion is None
        or completion.phase != "completed"
        or completion.installation_key != plan.installation_key
        or completion.backup_id != plan.backup_id
        or completion.deletion_receipt_id != confirmation.deletion_receipt_id
        or completion.restore_id != confirmation.restore_id
        or completion.record_digest != plan.restore_completion_digest
        or started is None
        or started.phase != "started"
        or started.restore_id != completion.restore_id
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_05"])
    publication = restore.publication_for(started, restore_plan)
    if publication is None:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_06"])

    parent_identity = _binding.inspect_windows_product_private_directory_identity(
        root.parent
    )
    if parent_identity != publication.parent_identity:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_07"])
    _binding._native_io.require_recovery_parent_view(
        root,
        parent_identity,
        stage_prefix=_binding._PRIVATE_DATA_FLOW_VALUES["message_08"],
        changed=_binding._PRIVATE_DATA_FLOW_VALUES["message_09"],
    )
    bound_root = _binding.inspect_coding_windows_arch_installation_root(
        layout, plan.installation_key, state_root=product.state_root
    )
    if bound_root != publication.stage_identity[:2]:
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_10"])
    restored = _binding._capture_windows_target_snapshot(root, expected_root=bound_root)
    if (
        restored.root_identity != publication.stage_identity
        or restored.target_id != plan.restored_target_id
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_11"])
