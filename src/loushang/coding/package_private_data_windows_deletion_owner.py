"""Product-bound Windows deletion of one confirmed Coding Arch private root.

The owner holds the Product's offline gate across every filesystem effect and
durable phase. It accepts only the currently observed Arch cache shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
    PrivateDataDeletionDisposition,
    execute_windows_private_deletion,
    remove_started_windows_private_tree,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._tree_observation import require_tree_subset

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)
from .package_private_data_windows_confirmation import (
    CodingWindowsArchPrivateDataConfirmationOwner,
)
from .package_private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionJournal,
    CodingWindowsArchPrivateDataDeletionTransaction,
    _capture_current_target,
    _tombstone_name,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
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
        confirmations = CodingWindowsArchPrivateDataConfirmationOwner(
            self.layout, self.product
        )
        with self._journal.transaction() as transaction:
            return execute_windows_private_deletion(
                transaction,
                plan,
                confirmation,
                capture_target=lambda: _capture_current_target(
                    confirmations, plan.installation_key
                ),
                remove_started=lambda started: _delete_started(
                    root, started, transaction, confirmations
                ),
            )

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


def _delete_started(
    root: Path,
    started: CodingArchPrivateDataDeletionEventV1,
    transaction: CodingWindowsArchPrivateDataDeletionTransaction,
    confirmations: CodingWindowsArchPrivateDataConfirmationOwner,
) -> PrivateDataDeletionDisposition:
    return remove_started_windows_private_tree(
        root,
        started,
        io=_native_io,
        capture_current=lambda: _capture_current_target(
            confirmations, started.plan.installation_key, allow_pending=True
        ),
        capture=lambda path, *, expected_root: _capture_windows_target_snapshot(
            path, expected_root=expected_root
        ),
        make_tombstone_name=lambda: _tombstone_name(started),
        current_start=lambda: transaction.current_start(),
        record_renamed=lambda value: transaction.record_renamed(value),
    )


def _require_remaining_subset(
    remaining: CodingArchPrivateDataTargetSnapshotV1,
    original: CodingArchPrivateDataTargetSnapshotV1,
) -> None:
    require_tree_subset(remaining, original, label="Windows Coding Arch")


_remove_members = _native_io.remove_members


_require_directory = _native_io.require_directory


__all__ = ["CodingWindowsArchPrivateDataDeletionOwner"]
