"""Private-data observation and receipt programs over original authorities.

Product identities, exact policies and nominal values remain borrowed
intermediate dependencies; no new persistence or repair owner is created.
"""

from __future__ import annotations

from loushang.coding.package import private_data_windows_backup as _binding

from . import private_data_backup_records


def retain(
    self: _binding.CodingWindowsArchPrivateDataBackupOwner,
    key: _binding.PluginInstallationKeyV1,
) -> _binding.CodingArchPrivateDataBackupReceiptV1:
    preview = _binding.CodingWindowsArchPrivateDataReadPreview(
        self.layout, self.product
    )
    source_root = _binding.coding_arch_installation_private_data_root(self.layout, key)
    state_root = (
        _binding.resolve_coding_package_epoch_layout(self.layout).control_root
        / "product-state"
    )
    with preview._offline():
        state = self.product.desired_state.snapshot().installation(key)
        if state.latest_instance_revision_ref is None:
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
        expected_root = _binding.inspect_coding_windows_arch_installation_root(
            self.layout, key, state_root=state_root
        )
        if expected_root is None:
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_02"])
        source = _binding._capture_windows_target_snapshot(
            source_root, expected_root=expected_root
        )
        receipt = private_data_backup_records.make_backup_receipt(key, source)
        parent_path = _binding.backup_parent(self.layout, key)
        _binding.prepare_windows_product_private_directory_chain(
            self.layout.package_root, "installation-backups", parent_path.name
        )
        return _binding._archive_io.retain(
            source_root,
            source,
            receipt,
            key,
            parent_path,
            source_is_current=lambda: (
                not (
                    _binding._capture_windows_target_snapshot(
                        source_root, expected_root=expected_root
                    )
                    != source
                    or _binding.inspect_coding_windows_arch_installation_root(
                        self.layout, key, state_root=state_root
                    )
                    != expected_root
                )
            ),
        )


def verify(
    self: _binding.CodingWindowsArchPrivateDataBackupOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id_value: str,
) -> _binding.CodingArchPrivateDataBackupReceiptV1:
    preview = _binding.CodingWindowsArchPrivateDataReadPreview(
        self.layout, self.product
    )
    _binding.coding_arch_installation_private_data_root(self.layout, key)
    if len(backup_id_value) != 64 or any(
        character not in "0123456789abcdef" for character in backup_id_value
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_03"])
    with preview._offline(), _binding.WindowsPrivateDirectoryAcl() as acl:
        state = self.product.desired_state.snapshot().installation(key)
        if state.latest_instance_revision_ref is None:
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
        parent_path = _binding.backup_parent(self.layout, key)
        return _binding._archive_io.verify_retained(
            parent_path, backup_id_value, key, acl
        )
