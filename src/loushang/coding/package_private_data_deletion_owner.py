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

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)
from .package_private_data_backup import _private_io
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
    CodingArchPrivateDataDeletionJournal,
)
from .package_private_data_deletion_journal import (
    _tombstone_name as _tombstone_name,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    _capture_target_snapshot,
)

_OWNER_ID = "coding.arch.private-data:posix-v1"


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
        root = coding_arch_installation_private_data_root(self.layout, key)
        with self._preview._offline():
            pending = self.journal.current_start()
            if pending is not None:
                if pending.plan.installation_key != key:
                    raise ValueError("Another private-data deletion is unfinished")
                return pending.plan
            target = _capture_target_snapshot(
                root, private_base=self.layout.private_data_base
            )
            return PluginPrivateDataDeletionPlanV1(
                installation_key=key, owner_id=_OWNER_ID, target_id=target.target_id
            )

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
        if (
            not isinstance(plan, PluginPrivateDataDeletionPlanV1)
            or not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1)
            or plan.owner_id != _OWNER_ID
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError("Coding Arch private-data deletion command is invalid")
        root = coding_arch_installation_private_data_root(
            self.layout, plan.installation_key
        )
        with self._preview._offline():
            if not self.confirmations.is_confirmed(plan, confirmation):
                raise ValueError("Coding Arch private-data confirmation is missing")
            if (
                self.product.desired_state.snapshot()
                .installation(plan.installation_key)
                .selection.desired_state
                != "absent"
            ):
                raise ValueError("Coding Arch Installation must be removed first")
            replay = self.journal.receipt_for(plan, confirmation)
            if replay is not None:
                return replay
            started = self.journal.current_start()
            if started is None:
                target = _capture_target_snapshot(
                    root, private_base=self.layout.private_data_base
                )
                if plan.target_id != target.target_id:
                    raise ValueError("Coding Arch private-data deletion plan is stale")
                started = self.journal.record_start(plan, confirmation, target)
            elif started.plan != plan or started.confirmation != confirmation:
                raise ValueError("Another private-data deletion is unfinished")
            disposition, terminal_start = _delete_started(
                root, started, self.layout.private_data_base, self.journal
            )
            receipt = PluginPrivateDataDeletionReceiptV1(
                installation_key=plan.installation_key,
                owner_id=plan.owner_id,
                target_id=plan.target_id,
                plan_fingerprint=plan.fingerprint,
                confirmation_id=confirmation.confirmation_id,
                receipt_id=_receipt_id(plan, confirmation),
                disposition=disposition,
            )
            self.journal.record_completion(terminal_start, receipt)
            return receipt

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
