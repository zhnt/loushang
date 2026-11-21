"""Private-data observation and receipt programs over original authorities.

Product identities, exact policies and nominal values remain borrowed
intermediate dependencies; no new persistence or repair owner is created.
"""

from __future__ import annotations

from loushang.coding.package import private_data_windows_preview as _binding


def snapshot_for(
    self: _binding.CodingWindowsArchPrivateDataReadPreview,
    key: _binding.PluginInstallationKeyV1,
) -> _binding.CodingArchPrivateDataTargetSnapshotV1:
    root = _binding.coding_arch_installation_private_data_root(self.layout, key)
    state_root = (
        _binding.resolve_coding_package_epoch_layout(self.layout).control_root
        / "product-state"
    )
    with self._offline():
        expected = _binding.inspect_coding_windows_arch_installation_root(
            self.layout, key, state_root=state_root
        )
        if expected is None:
            return _binding.CodingArchPrivateDataTargetSnapshotV1(
                root_path_digest=_binding.sha256(
                    _binding.os.fsencode(str(root))
                ).hexdigest(),
                root_identity=None,
                members=(),
            )
        snapshot = _binding._capture_windows_target_snapshot(
            root, expected_root=expected
        )
        if (
            _binding.inspect_coding_windows_arch_installation_root(
                self.layout, key, state_root=state_root
            )
            != expected
        ):
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
        return snapshot
