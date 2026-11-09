"""Private confirmation and crash-recovery history for one Arch backup expiry.

Only the archive owner may perform filesystem effects. This journal records
the exact reviewed plan, original archive tree, rename checkpoint, and receipt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.journal import FunctionalJournalRecordCodec, JournalCodecError
from loushang.harness.plugin_management._private_data_expiry import (
    PrivateDataExpiryJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)

from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingArchPrivateDataBackupExpiryPlanV1,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)

_JOURNAL_NAME = "private-data-backup-expiries.jsonl"
_MAX_RECORDS = 4096
_MAX_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupExpiryEventV1:
    revision: int
    phase: Literal["confirmed", "started", "renamed", "completed"]
    plan: CodingArchPrivateDataBackupExpiryPlanV1
    confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1
    archive: CodingArchPrivateDataTargetSnapshotV1 | None = None
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
            raise ValueError("Coding Arch backup expiry event is invalid")
        if self.phase == "confirmed":
            if self.archive is not None or self.receipt is not None:
                raise ValueError("Unstarted backup expiry has effects")
            return
        if (
            not isinstance(self.archive, CodingArchPrivateDataTargetSnapshotV1)
            or self.archive.root_identity != self.plan.archive_root_identity
            or self.archive.target_id != self.plan.archive_target_id
        ):
            raise ValueError("Coding Arch backup expiry archive changed")
        if self.phase == "completed":
            if not isinstance(
                self.receipt, CodingArchPrivateDataBackupExpiryReceiptV1
            ) or self.receipt != CodingArchPrivateDataBackupExpiryReceiptV1.create(
                self.plan, self.confirmation
            ):
                raise ValueError("Coding Arch backup expiry receipt changed")
        elif self.receipt is not None:
            raise ValueError("Unfinished backup expiry cannot claim a receipt")

    def to_dict(self) -> dict[str, object]:
        return _SCHEMA_BACKUP_EXPIRY_EVENT_V1.encode(self, sort_keys=True)

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataBackupExpiryEventV1:
        if type(value) is not dict or set(value) != _SCHEMA_BACKUP_EXPIRY_EVENT_V1.keys:
            raise ValueError("Coding Arch backup expiry event fields are invalid")
        return _SCHEMA_BACKUP_EXPIRY_EVENT_V1.decode(cls, value)


def _decode(value: object) -> CodingArchPrivateDataBackupExpiryEventV1:
    try:
        return CodingArchPrivateDataBackupExpiryEventV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Coding Arch backup expiry event is invalid",
            code="coding_arch_backup_expiry_record_invalid",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingArchPrivateDataBackupExpiryEventV1.to_dict,
    decoder=_decode,
)


class CodingArchPrivateDataBackupExpiryJournal(
    PrivateDataExpiryJournal[
        CodingArchPrivateDataBackupExpiryPlanV1,
        CodingArchPrivateDataBackupExpiryConfirmationV1,
        CodingArchPrivateDataTargetSnapshotV1,
        CodingArchPrivateDataBackupExpiryEventV1,
    ]
):
    """Bind original Arch identity, limits and records to the shared Journal."""

    def __init__(self, state_root: Path) -> None:
        if (
            not isinstance(state_root, Path)
            or not state_root.is_absolute()
            or ".." in state_root.parts
        ):
            raise ValueError("Coding Arch backup expiry state root is invalid")
        super().__init__(state_root / _JOURNAL_NAME, codec=_CODEC)

    _label = "Coding Arch"

    @property
    def _event_factory(self) -> type[CodingArchPrivateDataBackupExpiryEventV1]:
        return CodingArchPrivateDataBackupExpiryEventV1

    @property
    def _confirmation_factory(
        self,
    ) -> Callable[..., CodingArchPrivateDataBackupExpiryConfirmationV1]:
        return CodingArchPrivateDataBackupExpiryConfirmationV1.create

    @property
    def _receipt_factory(
        self,
    ) -> Callable[..., CodingArchPrivateDataBackupExpiryReceiptV1]:
        return CodingArchPrivateDataBackupExpiryReceiptV1.create

    @property
    def _max_records(self) -> int:
        return _MAX_RECORDS

    @property
    def _max_bytes(self) -> int:
        return _MAX_BYTES


_SCHEMA_BACKUP_EXPIRY_EVENT_V1 = RecordSchema.for_dataclass(
    CodingArchPrivateDataBackupExpiryEventV1,
    lambda value: value,
    RecordField(
        "plan",
        decoder=CodingArchPrivateDataBackupExpiryPlanV1.from_dict,
        encoder=CodingArchPrivateDataBackupExpiryPlanV1.to_dict,
    ),
    RecordField(
        "confirmation",
        decoder=CodingArchPrivateDataBackupExpiryConfirmationV1.from_dict,
        encoder=CodingArchPrivateDataBackupExpiryConfirmationV1.to_dict,
    ),
    RecordField(
        "archive",
        decoder=lambda item: (
            None
            if item is None
            else CodingArchPrivateDataTargetSnapshotV1.from_dict(item)
        ),
        encoder=lambda item: None if item is None else item.to_dict(),
    ),
    RecordField(
        "receipt",
        decoder=lambda item: (
            None
            if item is None
            else CodingArchPrivateDataBackupExpiryReceiptV1.from_dict(item)
        ),
        encoder=lambda item: None if item is None else item.to_dict(),
    ),
)

__all__ = [
    "CodingArchPrivateDataBackupExpiryConfirmationV1",
    "CodingArchPrivateDataBackupExpiryEventV1",
    "CodingArchPrivateDataBackupExpiryJournal",
    "CodingArchPrivateDataBackupExpiryReceiptV1",
]
