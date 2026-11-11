"""Offline Windows candidate that restores one deleted Coding Arch private root.

The owner needs an exact preview plan. It leaves every incomplete stage in
place for review or exact retry and never replaces an existing root.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationV1,
)
from .package_private_data_restore_records import (
    CodingArchPrivateDataRestorePlanV1,
    CodingArchPrivateDataRestoreResultV1,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
)
from .package_private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreJournal,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataRestoreOwner:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)

    def restore(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataRestoreResultV1:
        """Copy a verified archive and atomically publish an absent root."""

        if not isinstance(plan, CodingArchPrivateDataRestorePlanV1):
            raise ValueError("Windows Coding Arch restore plan is invalid")
        coding_arch_installation_private_data_root(self.layout, plan.installation_key)
        with CodingWindowsArchPrivateDataRestoreJournal(
            self.layout, self.product
        ).transaction() as transaction:
            disposition, restore_id = transaction.execute_restore(plan)
            return CodingArchPrivateDataRestoreResultV1(
                backup_id=plan.backup_id,
                disposition=disposition,
                restore_id=restore_id,
            )

    def confirm(
        self, plan: CodingArchPrivateDataRestorePlanV1
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        """Explicitly attest to current restored bytes after completion."""

        with CodingWindowsArchPrivateDataRestoreJournal(
            self.layout, self.product
        ).transaction() as transaction:
            return transaction.confirm_restore(plan)

    def verify_confirmation(
        self, plan: CodingArchPrivateDataRestorePlanV1, confirmation_id: str
    ) -> CodingArchPrivateDataRestoreConfirmationV1:
        with CodingWindowsArchPrivateDataRestoreJournal(
            self.layout, self.product
        ).transaction() as transaction:
            return transaction.verify_confirmation(plan, confirmation_id)


__all__ = ["CodingWindowsArchPrivateDataRestoreOwner"]
