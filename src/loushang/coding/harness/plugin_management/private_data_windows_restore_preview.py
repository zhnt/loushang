"""Private-data observation and receipt programs over original authorities.

Product identities, exact policies and nominal values remain borrowed
intermediate dependencies; no new persistence or repair owner is created.
"""

from __future__ import annotations

from loushang.coding.package import private_data_windows_restore_preview as _binding


def preview(
    self: _binding.CodingWindowsArchPrivateDataRestorePreview,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
) -> _binding.CodingArchPrivateDataRestorePlanV1:
    root = _binding.coding_arch_installation_private_data_root(self.layout, key)
    if len(backup_id) != 64 or any(
        character not in "0123456789abcdef" for character in backup_id
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
    preview = _binding.CodingWindowsArchPrivateDataReadPreview(
        self.layout, self.product
    )
    with preview._offline(), _binding.WindowsPrivateDirectoryAcl() as acl:
        desired = self.product.desired_state.snapshot()
        state = desired.installation(key)
        if (
            state.latest_instance_revision_ref is None
            or state.selection.desired_state != "absent"
        ):
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_02"])
        with self.product.epoch_runtime.borrow_product_state_root_descriptor() as fd:
            acl.validate(fd)
            transaction = _binding.CodingWindowsArchPrivateDataDeletionTransaction(
                self.product.state_root, fd
            )
            try:
                events = transaction.events()
            finally:
                transaction._close()
        if events and events[-1].phase != "completed":
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_03"])
        parent_path = _binding.backup_parent(self.layout, key)
        parent_identity = _binding.inspect_windows_product_private_directory_identity(
            parent_path
        )
        with _binding._archive_io._parent_scope(
            parent_path,
            parent_identity,
            acl,
            changed=_binding._PRIVATE_DATA_FLOW_VALUES["message_05"],
        ) as parent_fd:
            if any(
                name.endswith(".staging")
                for name in _binding.windows_listdir_at(parent_fd)
            ):
                raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_06"])
            receipt, source = _binding._read_archive_manifest(parent_fd, backup_id, acl)
            if receipt.installation_key != key or receipt.backup_id != backup_id:
                raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_07"])
            deletion_receipt = _binding.latest_deleted_target_receipt(
                events, key, receipt.source_target_id
            )
            if deletion_receipt is None:
                raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_08"])
            _binding._verify_archive(
                parent_fd, parent_path, backup_id, key, source, receipt, acl
            )
        if (
            _binding.inspect_coding_windows_arch_installation_root(
                self.layout, key, state_root=self.product.state_root
            )
            is not None
        ):
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_04"])
        _binding._require_no_restore_stage(root, acl)
        return _binding.CodingArchPrivateDataRestorePlanV1(
            installation_key=key,
            backup_id=backup_id,
            deletion_receipt_id=deletion_receipt.receipt_id,
            source_target_id=source.target_id,
            desired_inventory_revision=desired.inventory_revision,
            target_state="absent",
        )
