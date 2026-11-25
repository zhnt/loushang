"""Product-private start and receipt history for exact Arch data deletion.

The journal records authority/recovery and sequences a caller-supplied deletion.
Native IO and admission remain with their owners; the Coding data-domain owner
must hold Product quiescence around execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionEventV1,
    PluginPrivateDataDeletionPlanV1,
    confirmed_deletion_digest,
)
from loushang.harness.plugin_management.private_data_deletion_journal import (
    PrivateDataDeletionJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
)

from .private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1

_JOURNAL_NAME = "private-data-deletions.jsonl"


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataDeletionEventV1(
    PluginPrivateDataDeletionEventV1[CodingArchPrivateDataTargetSnapshotV1]
):
    target: CodingArchPrivateDataTargetSnapshotV1
    target_type = CodingArchPrivateDataTargetSnapshotV1


def _tombstone_name(started: CodingArchPrivateDataDeletionEventV1) -> str:
    digest = confirmed_deletion_digest(
        started.plan, started.confirmation,
        domain=b"loushang.coding-arch-private-data-tombstone/v1\0",
    )
    return ".deleting-" + digest


def _receipt_id(
    plan: PluginPrivateDataDeletionPlanV1,
    confirmation: PluginPrivateDataDeletionConfirmationV1,
) -> str:
    return confirmed_deletion_digest(
        plan, confirmation, domain=b"loushang.coding-arch-private-data-receipt/v1\0"
    )



_CODEC = FunctionalJournalRecordCodec.with_decode_error(
    encoder=CodingArchPrivateDataDeletionEventV1.to_dict,
    decoder=lambda value: CodingArchPrivateDataDeletionEventV1.from_dict(value),
    message="Coding Arch private-data deletion event is invalid",
    code="coding_arch_private_data_deletion_record_invalid",
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


_SCHEMA_DELETION_EVENT_V1 = CodingArchPrivateDataDeletionEventV1._bind_target_schema(
    RecordField(
        "target",
        decoder=CodingArchPrivateDataTargetSnapshotV1.from_dict,
        encoder=CodingArchPrivateDataTargetSnapshotV1.to_dict,
    ),
)

__all__ = [
    "CodingArchPrivateDataDeletionEventV1",
    "CodingArchPrivateDataDeletionJournal",
]
