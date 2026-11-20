"""Private-data observation and receipt programs over original authorities.

Product identities, exact policies and nominal values remain borrowed
intermediate dependencies; no new persistence or repair owner is created.
"""

from __future__ import annotations

from contextlib import contextmanager

from loushang.coding.package import private_data_windows_backup_client as _binding


@contextmanager
def backup_scope(
    self: _binding.CodingWindowsArchBackupCandidateClientV1,
) -> _binding.Iterator[_binding.CodingWindowsArchPrivateDataBackupOwner]:
    self._assert_workspace_identity()
    if not _binding.coding_fenced_product_exists(self.layout):
        raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_01"])
    application = _binding.open_coding_fenced_product_application_owner(
        self.layout,
        workspace=self.workspace,
        runtime_version=self.runtime_version,
        runtime_protocol_epoch=self.runtime_protocol_epoch,
        windows_candidate=True,
    )
    try:
        product = application.runtime_owner.product_owner
        if not isinstance(
            product, _binding.WindowsLocalWheelProductSessionOwner
        ) or not isinstance(
            application.epoch_runtime, _binding.PackageProductWindowsFencedRuntimeOwner
        ):
            raise ValueError(_binding._PRIVATE_DATA_FLOW_VALUES["message_02"])
        owner = _binding.CodingWindowsArchPrivateDataBackupOwner(self.layout, product)
        yield owner
        self._assert_workspace_identity()
    finally:
        application.close()
