"""Exact POSIX Coding Arch Installation private-data deletion owner.

Only a separately confirmed, removed Installation may enter this owner. The
Product runtime lease fence remains held through physical deletion and the
durable receipt; Package removal and root GC never call this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.coding.harness.plugin_management import (
    private_data_deletion_owner as _programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationJournal,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
    PrivateDataDeletionDisposition,
    remove_started_private_tree,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

from .installation_private_data import coding_arch_installation_private_data_root
from .private_data_backup import _private_io
from .private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
    CodingArchPrivateDataDeletionJournal,
)
from .private_data_deletion_journal import _tombstone_name as _tombstone_name
from .private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    _capture_target_snapshot,
)

_OWNER_ID = "coding.arch.private-data:posix-v1"


_PRIVATE_DATA_PROGRAM_VALUES = {
    "value_01": "Coding Arch private-data deletion command is invalid",
    "value_02": "Coding Arch private-data confirmation is missing",
    "value_03": "Coding Arch Installation must be removed first",
    "value_04": "Coding Arch private-data deletion plan is stale",
}


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataDeletionOwner:
    layout: CodingPluginLifecycleStateLayout
    product: PosixLocalWheelProductSessionOwner
    confirmations: PluginPrivateDataConfirmationJournal
    journal: CodingArchPrivateDataDeletionJournal

    def __post_init__(self) -> None:
        if os.name != "posix":
            raise RuntimeError("Coding Arch POSIX deletion owner is unavailable")
        CodingArchPrivateDataDeletionPreview(self.layout, self.product)
        if (
            not isinstance(self.confirmations, PluginPrivateDataConfirmationJournal)
            or not isinstance(self.journal, CodingArchPrivateDataDeletionJournal)
            or self.confirmations.path
            != self.product.state_root / "private-data-confirmations.jsonl"
            or self.journal.path
            != self.product.state_root / "private-data-deletions.jsonl"
        ):
            raise ValueError("Coding Arch private-data owners are not bound")

    def plan_for(self, key: PluginInstallationKeyV1) -> PluginPrivateDataDeletionPlanV1:
        return _programs.plan_for(self, key)

    def receipt_for(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1 | None:
        coding_arch_installation_private_data_root(self.layout, plan.installation_key)
        with self._preview._offline():
            return self.journal.receipt_for(plan, confirmation)

    def delete_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1:
        return _programs.delete_confirmed(self, plan, confirmation)

    @property
    def _preview(self) -> CodingArchPrivateDataDeletionPreview:
        return CodingArchPrivateDataDeletionPreview(self.layout, self.product)


def _delete_started(
    root: Path,
    started: CodingArchPrivateDataDeletionEventV1,
    private_base: Path,
    journal: CodingArchPrivateDataDeletionJournal,
) -> tuple[PrivateDataDeletionDisposition, CodingArchPrivateDataDeletionEventV1]:
    return remove_started_private_tree(
        root,
        started,
        io=_private_io,
        capture=lambda path: _capture_target_snapshot(path, private_base=private_base),
        make_tombstone_name=lambda: _tombstone_name(started),
        record_renamed=journal.record_renamed,
    )


def _receipt_id(
    plan: PluginPrivateDataDeletionPlanV1,
    confirmation: PluginPrivateDataDeletionConfirmationV1,
) -> str:
    return sha256(
        b"loushang.coding-arch-private-data-receipt/v1\0"
        + plan.fingerprint.encode("ascii")
        + b"\0"
        + confirmation.confirmation_id.encode("utf-8")
    ).hexdigest()


__all__ = ["CodingArchPrivateDataDeletionOwner"]
