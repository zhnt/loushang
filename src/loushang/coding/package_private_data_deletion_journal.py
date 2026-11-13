"""Product-private start and receipt history for exact Arch data deletion.

The journal records authority and recovery state. It performs no filesystem
deletion; the Coding data-domain owner must hold Product quiescence around it.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalCodecError,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionEventV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.private_data_deletion_journal import (
    PrivateDataDeletionJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)

from .package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)

_JOURNAL_NAME = "private-data-deletions.jsonl"


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataDeletionEventV1(
    PluginPrivateDataDeletionEventV1[CodingArchPrivateDataTargetSnapshotV1]
):
    target: CodingArchPrivateDataTargetSnapshotV1
    target_type = CodingArchPrivateDataTargetSnapshotV1


def _tombstone_name(started: CodingArchPrivateDataDeletionEventV1) -> str:
    digest = sha256(
        b"loushang.coding-arch-private-data-tombstone/v1\0"
        + started.plan.fingerprint.encode("ascii")
        + b"\0"
        + started.confirmation.confirmation_id.encode("utf-8")
    ).hexdigest()
    return ".deleting-" + digest



def _decode(value: object) -> CodingArchPrivateDataDeletionEventV1:
    try:
        return CodingArchPrivateDataDeletionEventV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Coding Arch private-data deletion event is invalid",
            code="coding_arch_private_data_deletion_record_invalid",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingArchPrivateDataDeletionEventV1.to_dict,
    decoder=_decode,
)


class CodingArchPrivateDataDeletionJournal(
    PrivateDataDeletionJournal[
        CodingArchPrivateDataTargetSnapshotV1, CodingArchPrivateDataDeletionEventV1
    ]
):
    def __init__(self, state_root: Path) -> None:
        if (
            not isinstance(state_root, Path)
            or not state_root.is_absolute()
            or ".." in state_root.parts
        ):
            raise ValueError("Coding Arch deletion Product state root is invalid")
        super().__init__(
            state_root / _JOURNAL_NAME,
            event_type=CodingArchPrivateDataDeletionEventV1,
            codec=_CODEC,
            label="Coding Arch deletion",
        )


_SCHEMA_DELETION_EVENT_V1 = RecordSchema(
    lambda value: value,
    (
        RecordField("revision"),
        RecordField("phase"),
        RecordField(
            "plan",
            decoder=PluginPrivateDataDeletionPlanV1.from_dict,
            encoder=PluginPrivateDataDeletionPlanV1.to_dict,
        ),
        RecordField(
            "confirmation",
            decoder=PluginPrivateDataDeletionConfirmationV1.from_dict,
            encoder=PluginPrivateDataDeletionConfirmationV1.to_dict,
        ),
        RecordField(
            "target",
            decoder=CodingArchPrivateDataTargetSnapshotV1.from_dict,
            encoder=CodingArchPrivateDataTargetSnapshotV1.to_dict,
        ),
        RecordField(
            "receipt",
            decoder=lambda item: (
                None
                if item is None
                else PluginPrivateDataDeletionReceiptV1.from_dict(item)
            ),
            encoder=lambda item: None if item is None else item.to_dict(),
        ),
        RecordField("record_version"),
    ),
)

CodingArchPrivateDataDeletionEventV1.schema = _SCHEMA_DELETION_EVENT_V1

__all__ = [
    "CodingArchPrivateDataDeletionEventV1",
    "CodingArchPrivateDataDeletionJournal",
]
