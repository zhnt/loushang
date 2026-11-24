"""Durable exact-owner evidence for Coding Plugin Session families."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import cast as cast

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
)
from loushang.harness.journal import (
    JournalCodecError as JournalCodecError,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
)
from loushang.harness.session.plugin_lifecycle._owner_evidence import (
    _canonical_receipts as _canonical_receipts,
)
from loushang.harness.session.plugin_lifecycle._owner_evidence import (
    _OwnerGenerationEvidenceEvent,
    _OwnerGenerationEvidenceLedger,
)
from loushang.harness.session.plugin_lifecycle._owner_evidence import (
    _receipt_identity as _receipt_identity,
)

CodingOwnerGenerationEventKind = Literal["prepared", "published", "retired"]
CodingOwnerGenerationPublicationState = Literal[
    "prepared",
    "published",
    "retired",
]


class CodingOwnerGenerationEvidenceError(RuntimeError):
    """Fail-closed owner-generation publication/retirement evidence error."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class CodingOwnerGenerationEvidenceEventV1(_OwnerGenerationEvidenceEvent):
    journal_revision: int
    event_id: str
    event_kind: CodingOwnerGenerationEventKind
    family_id: str
    instance_revision_ref: PluginInstanceRevisionRef
    receipts: tuple[OwnerGenerationRetirementReceipt, ...]
    outcome_reference: str
    record_version: int = 1

    _product_label = "Coding"
    _event_digest_domain = b"loushang.coding-owner-generation-evidence/v1\x00"
    _invalid_event_code = "invalid_coding_owner_generation_evidence"


CODING_OWNER_GENERATION_EVIDENCE_CODEC = FunctionalJournalRecordCodec[
    CodingOwnerGenerationEvidenceEventV1
](
    encoder=CodingOwnerGenerationEvidenceEventV1.to_dict,
    decoder=CodingOwnerGenerationEvidenceEventV1.from_dict,
)


@dataclass(frozen=True, slots=True)
class CodingOwnerGenerationFamilyEvidence:
    family_id: str
    instance_revision_ref: PluginInstanceRevisionRef
    receipts: tuple[OwnerGenerationRetirementReceipt, ...]
    publication_state: CodingOwnerGenerationPublicationState
    retirement_outcome_reference: str | None

    @property
    def retired(self) -> bool:
        return self.publication_state == "retired"


class CodingOwnerGenerationEvidenceLedger(
    _OwnerGenerationEvidenceLedger[
        CodingOwnerGenerationEvidenceEventV1, CodingOwnerGenerationFamilyEvidence
    ]
):
    """Coding value/codec policy over the Session-owned evidence mechanism."""

    _event_type = CodingOwnerGenerationEvidenceEventV1
    _family_type = CodingOwnerGenerationFamilyEvidence
    _record_codec = CODING_OWNER_GENERATION_EVIDENCE_CODEC
    _error_type = CodingOwnerGenerationEvidenceError
    _error_code_prefix = "coding_owner_generation"
    _product_label = "Coding"


__all__ = [
    "CodingOwnerGenerationEvidenceError",
    "CodingOwnerGenerationEvidenceEventV1",
    "CodingOwnerGenerationEvidenceLedger",
    "CodingOwnerGenerationFamilyEvidence",
]
