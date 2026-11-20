"""Private-data observation and receipt programs over original authorities.

Product identities, exact policies and nominal values remain borrowed
intermediate dependencies; no new persistence or repair owner is created.
"""

from __future__ import annotations

from contextlib import contextmanager

from loushang.coding.package import private_data_backup_sdk as _binding


def read_retention_status(
    self: _binding.CodingArchPrivateDataBackupClientV1,
) -> _binding.PluginBackupRetentionRecordV1:
    """Read the backup owner's typed status without changing retention."""

    self._assert_workspace_identity()
    if (
        _binding.os.name != "posix"
        or not _binding.sys.platform.startswith("linux")
        or not _binding.coding_fenced_product_exists(self.layout)
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
    layout = _binding.resolve_coding_package_epoch_layout(self.layout)
    epoch = _binding.PackageProductPosixFencedRuntimeOwner.open(
        **layout.fenced_runtime_open_kwargs(), read_only=True
    )
    try:
        self._assert_workspace_identity()
        [record] = (
            _binding.CodingArchPrivateDataBackupReadSource(self.layout, epoch)
            .snapshot()
            .records
        )
        if record.installation_key != self.installation_key:
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_02"])
        self._assert_workspace_identity()
        return record
    finally:
        epoch.close()


@contextmanager
def read_scope(
    self: _binding.CodingArchPrivateDataBackupClientV1,
) -> _binding.Iterator[_binding.CodingArchPrivateDataReadOwner]:
    self._assert_workspace_identity()
    if (
        _binding.os.name != "posix"
        or not _binding.sys.platform.startswith("linux")
        or not _binding.coding_fenced_product_exists(self.layout)
    ):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
    reader = _binding.CodingArchPrivateDataReadOwner.open(
        layout=self.layout,
        workspace=self.workspace,
        workspace_identity=self.workspace_identity,
    )
    try:
        yield reader
    finally:
        try:
            self._assert_workspace_identity()
        finally:
            reader.close()


@contextmanager
def product_scope(
    self: _binding.CodingArchPrivateDataBackupClientV1,
) -> _binding.Iterator[_binding.PosixLocalWheelProductSessionOwner]:
    application = self._open_application()
    try:
        product = application.runtime_owner.product_owner
        if not isinstance(
            product, _binding.PosixLocalWheelProductSessionOwner
        ) or not isinstance(
            application.epoch_runtime, _binding.PackageProductPosixFencedRuntimeOwner
        ):
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_03"])
        yield product
    finally:
        application.close()
