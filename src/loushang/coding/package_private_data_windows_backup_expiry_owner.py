"""Offline Windows candidate for receipt-backed Arch backup expiry.

The archive is renamed through its verified handle before individual members
are deleted. Durable Product receipts permit exact retry after either effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingArchPrivateDataBackupExpiryPlanV1,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from .package_private_data_windows_backup_expiry_journal import (
    CodingWindowsArchBackupExpiryJournal,
    CodingWindowsArchBackupExpiryTransaction,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataBackupExpiryOwner:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchBackupExpiryJournal(self.layout, self.product)

    def confirm(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        with CodingWindowsArchBackupExpiryJournal(
            self.layout, self.product
        ).transaction() as transaction:
            return transaction.confirm(
                plan, actor_id=actor_id, policy_revision=policy_revision
            )

    def expire(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
    ) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        if (
            not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or not isinstance(
                confirmation, CodingArchPrivateDataBackupExpiryConfirmationV1
            )
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError("Windows Coding Arch backup expiry acceptance is invalid")
        with CodingWindowsArchBackupExpiryJournal(
            self.layout, self.product
        ).transaction() as transaction:
            return self._expire_locked(transaction, plan, confirmation)

    def _expire_locked(
        self,
        transaction: CodingWindowsArchBackupExpiryTransaction,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
    ) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        # The concrete transaction creates only the original receipt type.
        return cast(
            CodingArchPrivateDataBackupExpiryReceiptV1,
            transaction.execute_expiry(plan, confirmation),
        )


__all__ = ["CodingWindowsArchPrivateDataBackupExpiryOwner"]
