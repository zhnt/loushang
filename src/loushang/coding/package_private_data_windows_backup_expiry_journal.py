"""Native Product-private confirmation and start receipts for Windows expiry.

This candidate records operator acceptance and an exact archive snapshot.
Rename, member deletion, and terminal completion require a separate owner.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal.codec import decode_json_record
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_backup_windows import (
    WindowsArchiveExpiryIO,
)
from loushang.harness.plugin_management._private_data_expiry_windows import (
    WindowsPrivateExpiryTransaction,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages._private_tree_windows import (
    PrivateWindowsTreeIO,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_windows_receipt import (
    _receipt_io,
)
from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingArchPrivateDataBackupExpiryPlanV1,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from .package_private_data_backup_records import backup_parent
from .package_private_data_windows_archive_snapshot import (
    CodingWindowsArchBackupArchiveSnapshotV1,
    capture_windows_arch_backup_archive,
)
from .package_private_data_windows_backup import _archive_io, _read_archive_manifest
from .package_private_data_windows_backup_expiry_preview import (
    CodingWindowsArchPrivateDataBackupExpiryPreview,
)
from .package_private_data_windows_backup_expiry_recovery import (
    require_windows_arch_backup_expiry_recovery_authority,
)
from .package_private_data_windows_preview import _native_io
from .package_private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreJournal,
    CodingWindowsArchPrivateDataRestoreTransaction,
)

_EVENT_PREFIX = "arch-backup-expiry-"
_EVENT_NAME = re.compile(r"arch-backup-expiry-([0-9]{8})\.json(\.stage)?\Z")
_MAX_EVENTS = 4096
_MAX_EVENT_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsArchBackupExpiryEventV1:
    revision: int
    phase: Literal["confirmed", "started", "renamed", "completed"]
    plan: CodingArchPrivateDataBackupExpiryPlanV1
    confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1
    archive: CodingWindowsArchBackupArchiveSnapshotV1 | None = None
    receipt: CodingArchPrivateDataBackupExpiryReceiptV1 | None = None
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.revision) is not int
            or self.revision < 1
            or self.phase not in {"confirmed", "started", "renamed", "completed"}
            or not isinstance(self.plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or not isinstance(
                self.confirmation, CodingArchPrivateDataBackupExpiryConfirmationV1
            )
            or self.confirmation.plan_fingerprint != self.plan.fingerprint
            or self.record_version != 1
        ):
            raise ValueError("Windows Coding Arch backup expiry event is invalid")
        if self.phase == "confirmed":
            if self.archive is not None or self.receipt is not None:
                raise ValueError(
                    "Unstarted Windows Coding Arch backup expiry has effects"
                )
            return
        if (
            not isinstance(self.archive, CodingWindowsArchBackupArchiveSnapshotV1)
            or self.archive.root_identity != self.plan.archive_root_identity
            or self.archive.target_id != self.plan.archive_target_id
        ):
            raise ValueError("Windows Coding Arch backup expiry archive changed")
        if self.phase == "completed":
            if self.receipt != CodingArchPrivateDataBackupExpiryReceiptV1.create(
                self.plan, self.confirmation
            ):
                raise ValueError("Windows Coding Arch backup expiry receipt changed")
        elif self.receipt is not None:
            raise ValueError("Unfinished Windows Coding Arch backup expiry has receipt")

    def to_dict(self) -> dict[str, object]:
        return {
            "archive": None if self.archive is None else self.archive.to_dict(),
            "confirmation": self.confirmation.to_dict(),
            "phase": self.phase,
            "plan": self.plan.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "recordVersion": self.record_version,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWindowsArchBackupExpiryEventV1:
        if type(value) is not dict or set(value) != {
            "archive",
            "confirmation",
            "phase",
            "plan",
            "receipt",
            "recordVersion",
            "revision",
        }:
            raise ValueError("Windows Coding Arch backup expiry event fields changed")
        archive = value["archive"]
        receipt = value["receipt"]
        return cls(
            revision=value["revision"],
            phase=value["phase"],
            plan=CodingArchPrivateDataBackupExpiryPlanV1.from_dict(value["plan"]),
            confirmation=CodingArchPrivateDataBackupExpiryConfirmationV1.from_dict(
                value["confirmation"]
            ),
            archive=(
                None
                if archive is None
                else CodingWindowsArchBackupArchiveSnapshotV1.from_dict(archive)
            ),
            receipt=(
                None
                if receipt is None
                else CodingArchPrivateDataBackupExpiryReceiptV1.from_dict(receipt)
            ),
            record_version=value["recordVersion"],
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsArchBackupExpiryJournal:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataBackupExpiryPreview(self.layout, self.product)

    @contextmanager
    def transaction(self) -> Iterator[CodingWindowsArchBackupExpiryTransaction]:
        with CodingWindowsArchPrivateDataRestoreJournal(
            self.layout, self.product
        ).transaction() as restore:
            yield CodingWindowsArchBackupExpiryTransaction(
                self.layout, self.product, restore
            )


@dataclass(frozen=True, slots=True)
class CodingWindowsArchBackupExpiryTransaction(
    WindowsPrivateExpiryTransaction[
        CodingArchPrivateDataBackupExpiryPlanV1,
        CodingArchPrivateDataBackupExpiryConfirmationV1,
        CodingWindowsArchBackupArchiveSnapshotV1,
        CodingWindowsArchBackupExpiryEventV1,
    ]
):
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner
    restore: CodingWindowsArchPrivateDataRestoreTransaction

    def confirm(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        if not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1):
            raise ValueError("Windows Coding Arch backup expiry plan is invalid")
        self._require_current_plan(plan)
        return self._confirm_current(
            plan, actor_id=actor_id, policy_revision=policy_revision
        )

    def begin(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
        archive: CodingWindowsArchBackupArchiveSnapshotV1,
    ) -> CodingWindowsArchBackupExpiryEventV1:
        if (
            not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1)
            or not isinstance(
                confirmation, CodingArchPrivateDataBackupExpiryConfirmationV1
            )
            or confirmation.plan_fingerprint != plan.fingerprint
            or not isinstance(archive, CodingWindowsArchBackupArchiveSnapshotV1)
            or archive.root_identity != plan.archive_root_identity
            or archive.target_id != plan.archive_target_id
        ):
            raise ValueError("Windows Coding Arch backup expiry start is invalid")
        self._require_current_plan(plan)
        return self._begin_current(plan, confirmation, archive)

    def advance(
        self,
        prior: CodingWindowsArchBackupExpiryEventV1,
        phase: Literal["renamed", "completed"],
    ) -> CodingWindowsArchBackupExpiryEventV1:
        if not isinstance(prior, CodingWindowsArchBackupExpiryEventV1) or phase not in {
            "renamed",
            "completed",
        }:
            raise ValueError("Windows Coding Arch backup expiry transition is invalid")
        return self._advance_current(prior, phase)

    _label: ClassVar[str] = "Windows Coding Arch"
    _tree_io: ClassVar[PrivateWindowsTreeIO] = _native_io
    _archive_io: ClassVar[WindowsArchiveExpiryIO] = _archive_io

    def _backup_parent(self, key: PluginInstallationKeyV1) -> Path:
        return backup_parent(self.layout, key)

    def _tombstone_name(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
    ) -> str:
        from .package_private_data_windows_backup_expiry_owner import _tombstone_name

        return _tombstone_name(plan, confirmation)

    def _require_pre_effect_archive(
        self,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        parent_fd: int,
        acl: WindowsPrivateDirectoryAcl,
    ) -> CodingWindowsArchBackupArchiveSnapshotV1:
        self._require_current_plan(plan)
        receipt, source = _read_archive_manifest(parent_fd, plan.backup_id, acl)
        archive = capture_windows_arch_backup_archive(
            self.layout, plan.installation_key, plan.backup_id, source, receipt
        )
        if archive.target_id != plan.archive_target_id:
            raise ValueError("Windows Coding Arch backup archive changed")
        return archive

    def _require_recovery_authority(
        self, plan: CodingArchPrivateDataBackupExpiryPlanV1
    ) -> None:
        require_windows_arch_backup_expiry_recovery_authority(
            self.layout, self.product, self.restore, plan
        )

    _event_factory = CodingWindowsArchBackupExpiryEventV1
    _confirmation_factory = staticmethod(
        CodingArchPrivateDataBackupExpiryConfirmationV1.create
    )
    _receipt_factory = staticmethod(CodingArchPrivateDataBackupExpiryReceiptV1.create)
    _event_prefix: ClassVar[str] = _EVENT_PREFIX
    _event_name: ClassVar[re.Pattern[str]] = _EVENT_NAME
    _max_events: ClassVar[int] = _MAX_EVENTS
    _max_event_bytes: ClassVar[int] = _MAX_EVENT_BYTES
    _receipt_io: ClassVar[WindowsPrivateReceiptIO] = _receipt_io

    @property
    def _state_root(self) -> Path:
        return self.product.state_root

    def _decode_event(self, raw: bytes) -> CodingWindowsArchBackupExpiryEventV1:
        return decode_json_record(
            raw,
            CodingWindowsArchBackupExpiryEventV1.from_dict,
            label="Windows Coding Arch backup expiry event",
            duplicate_message="Windows Coding Arch backup expiry repeats a field",
        )

    def _require_current_plan(
        self, plan: CodingArchPrivateDataBackupExpiryPlanV1
    ) -> None:
        current = CodingWindowsArchPrivateDataBackupExpiryPreview(
            self.layout, self.product
        )._preview_locked(
            self.restore,
            plan.installation_key,
            plan.backup_id,
            plan.confirmation_id,
        )
        if current != plan:
            raise ValueError("Windows Coding Arch backup expiry plan changed")


__all__ = [
    "CodingWindowsArchBackupExpiryEventV1",
    "CodingWindowsArchBackupExpiryJournal",
    "CodingWindowsArchBackupExpiryTransaction",
]
