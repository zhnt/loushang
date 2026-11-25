"""Product-bound Windows deletion of one confirmed Coding Arch private root.

The owner holds the Product's offline gate across every filesystem effect and
durable phase. It accepts only the currently observed Arch cache shape.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._tree_observation import require_tree_subset

from .installation_private_data import coding_arch_installation_private_data_root
from .private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1
from .private_data_windows_confirmation import (
    CodingWindowsArchPrivateDataConfirmationOwner,
)
from .private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionJournal,
)
from .private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _native_io,
)

_OWNER_ID = "coding.arch.private-data:windows-v1"


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataDeletionOwner:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        CodingWindowsArchPrivateDataDeletionJournal(self.layout, self.product)

    def plan_for(self, key: PluginInstallationKeyV1) -> PluginPrivateDataDeletionPlanV1:
        return CodingWindowsArchPrivateDataConfirmationOwner(
            self.layout, self.product
        ).plan_for(key)

    def receipt_for(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1 | None:
        self._require_command(plan, confirmation)
        coding_arch_installation_private_data_root(self.layout, plan.installation_key)
        with self._journal.transaction() as transaction:
            return transaction.receipt_for(plan, confirmation)

    def delete_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1:
        self._require_command(plan, confirmation)
        root = coding_arch_installation_private_data_root(
            self.layout, plan.installation_key
        )
        # Preserve confirmation admission before acquiring the mutation fence.
        CodingWindowsArchPrivateDataConfirmationOwner(self.layout, self.product)
        with self._journal.transaction() as transaction:
            return transaction.execute(root, plan, confirmation)

    @property
    def _journal(self) -> CodingWindowsArchPrivateDataDeletionJournal:
        return CodingWindowsArchPrivateDataDeletionJournal(self.layout, self.product)

    @staticmethod
    def _require_command(
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> None:
        if (
            not isinstance(plan, PluginPrivateDataDeletionPlanV1)
            or not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1)
            or plan.owner_id != _OWNER_ID
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError("Windows Coding Arch deletion command is invalid")


def _require_remaining_subset(
    remaining: CodingArchPrivateDataTargetSnapshotV1,
    original: CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    require_tree_subset(remaining, original, label="Windows Coding Arch")


_remove_members = _native_io.remove_members


_require_directory = _native_io.require_directory


__all__ = ["CodingWindowsArchPrivateDataDeletionOwner"]
