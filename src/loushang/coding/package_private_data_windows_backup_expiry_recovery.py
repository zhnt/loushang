"""Archive-free Product authority for resuming a Windows Arch backup expiry."""

from __future__ import annotations

import os

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_listdir_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
)
from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from .package_private_data_restore_records import CodingArchPrivateDataRestorePlanV1
from .package_private_data_windows_backup import _directory_identity
from .package_private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction,
)
from .package_private_data_windows_preview import _capture_windows_target_snapshot
from .package_private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreTransaction,
)


def require_windows_arch_backup_expiry_recovery_authority(
    layout: CodingPluginLifecycleStateLayout,
    product: WindowsLocalWheelProductSessionOwner,
    restore: CodingWindowsArchPrivateDataRestoreTransaction,
    plan: CodingArchPrivateDataBackupExpiryPlanV1,
) -> None:
    """Verify immutable history and current restored bytes after archive rename."""

    if not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1):
        raise ValueError("Windows Coding Arch backup expiry plan is invalid")
    root = coding_arch_installation_private_data_root(layout, plan.installation_key)
    restore._require_active()
    desired = product.desired_state.snapshot()
    installation = desired.installation(plan.installation_key)
    if (
        desired.inventory_revision != plan.desired_inventory_revision
        or installation.latest_instance_revision_ref is None
        or installation.selection.desired_state != "absent"
    ):
        raise ValueError("Windows Coding Arch backup expiry Desired State changed")

    deletion = CodingWindowsArchPrivateDataDeletionTransaction(
        product.state_root, restore.state_fd
    )
    try:
        deletion_events = deletion.events()
    finally:
        deletion._close()
    latest_deletion = next(
        (
            item
            for item in reversed(deletion_events)
            if item.plan.installation_key == plan.installation_key
        ),
        None,
    )
    if (
        latest_deletion is None
        or latest_deletion.phase != "completed"
        or latest_deletion.target.target_id != plan.source_target_id
        or latest_deletion.receipt is None
        or latest_deletion.receipt.disposition != "deleted"
    ):
        raise ValueError("Windows Coding Arch backup expiry deletion changed")

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
        or confirmation.deletion_receipt_id != latest_deletion.receipt.receipt_id
        or confirmation.restore_completion_digest != plan.restore_completion_digest
        or confirmation.restored_target_id != plan.restored_target_id
    ):
        raise ValueError("Windows Coding Arch backup expiry confirmation changed")

    restore_plan = CodingArchPrivateDataRestorePlanV1(
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
        raise ValueError("Windows Coding Arch backup expiry restore changed")
    publication = restore.publication_for(started, restore_plan)
    if publication is None:
        raise ValueError("Windows Coding Arch backup expiry publication is missing")

    parent_identity = inspect_windows_product_private_directory_identity(root.parent)
    if parent_identity != publication.parent_identity:
        raise ValueError("Windows Coding Arch backup expiry restore parent changed")
    with WindowsPrivateDirectoryAcl() as acl:
        parent_fd = open_windows_directory(
            root.parent, share_delete=False, read_control=True
        )
        try:
            acl.validate(parent_fd)
            if (
                _directory_identity(parent_fd) != parent_identity
                or root.name not in windows_listdir_at(parent_fd)
                or any(
                    name.startswith(".arch-restore-")
                    for name in windows_listdir_at(parent_fd)
                )
            ):
                raise ValueError("Windows Coding Arch backup expiry restore has debt")
        finally:
            os.close(parent_fd)
    bound_root = inspect_coding_windows_arch_installation_root(
        layout, plan.installation_key, state_root=product.state_root
    )
    if bound_root != publication.stage_identity[:2]:
        raise ValueError("Windows Coding Arch backup expiry root binding changed")
    restored = _capture_windows_target_snapshot(root, expected_root=bound_root)
    if (
        restored.root_identity != publication.stage_identity
        or restored.target_id != plan.restored_target_id
    ):
        raise ValueError("Windows Coding Arch backup expiry restored bytes changed")


__all__ = ["require_windows_arch_backup_expiry_recovery_authority"]
