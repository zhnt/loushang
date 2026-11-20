"""Durable exact-owner evidence for Coding Plugin Session families."""

from __future__ import annotations

import hashlib as hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import cast as cast

from loushang.coding.harness.plugin_management import (
    owner_evidence_record as _evidence_programs,
)
from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
)
from loushang.harness.journal import (
    JournalCodecError as JournalCodecError,
)
from loushang.harness.resources.plugins._strict_json import (
    StrictPluginJsonCodec as StrictPluginJsonCodec,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
)
from loushang.harness.session.plugin_lifecycle._owner_evidence import (
    _canonical_receipts as _canonical_receipts,
)
from loushang.harness.session.plugin_lifecycle._owner_evidence import (
    _OwnerGenerationEvidenceLedger,
)
from loushang.harness.session.plugin_lifecycle._owner_evidence import (
    _receipt_identity as _receipt_identity,
)
from loushang.harness.session.plugin_lifecycle._owner_evidence import (
    _validate_receipts as _validate_owner_receipts,
)

CodingOwnerGenerationEventKind = Literal["prepared", "published", "retired"]
CodingOwnerGenerationPublicationState = Literal[
    "prepared",
    "published",
    "retired",
]


_OWNER_EVIDENCE_PROGRAM_VALUES = {
    "value_001": "Coding owner evidence ",
    "value_002": "Coding owner evidence revision must be positive",
    "value_003": "Coding owner evidence kind is invalid",
    "value_004": "Coding owner evidence Instance reference is invalid",
    "value_005": "Unsupported Coding owner evidence version",
    "value_006": "Coding owner evidence id does not match",
    "value_007": "Coding owner evidence fields are invalid",
    "value_008": "Coding owner evidence receipts must be an array",
    "value_009": "invalid_coding_owner_generation_evidence",
}

_OWNER_EVIDENCE_PROGRAM_BYTES = {
    "value_001": b"loushang.coding-owner-generation-evidence/v1\x00"
}


class CodingOwnerGenerationEvidenceError(RuntimeError):
    """Fail-closed owner-generation publication/retirement evidence error."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class CodingOwnerGenerationEvidenceEventV1:
    journal_revision: int
    event_id: str
    event_kind: CodingOwnerGenerationEventKind
    family_id: str
    instance_revision_ref: PluginInstanceRevisionRef
    receipts: tuple[OwnerGenerationRetirementReceipt, ...]
    outcome_reference: str
    record_version: int = 1

    def __post_init__(self) -> None:
        return _evidence_programs.validate_event(self)

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        event_kind: CodingOwnerGenerationEventKind,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        outcome_reference: str,
    ) -> CodingOwnerGenerationEvidenceEventV1:
        return _evidence_programs.create_event(
            cls,
            journal_revision=journal_revision,
            event_kind=event_kind,
            family_id=family_id,
            instance_revision_ref=instance_revision_ref,
            receipts=receipts,
            outcome_reference=outcome_reference,
        )

    def to_dict(self) -> dict[str, object]:
        return _evidence_programs.encode_event(self)

    @classmethod
    def from_dict(
        cls,
        value: object,
    ) -> CodingOwnerGenerationEvidenceEventV1:
        return _evidence_programs.decode_event(cls, value)


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

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)

    def prepare(
        self,
        *,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        preparation_reference: str,
    ) -> CodingOwnerGenerationFamilyEvidence:
        return super().prepare(
            family_id=family_id,
            instance_revision_ref=instance_revision_ref,
            receipts=receipts,
            preparation_reference=preparation_reference,
        )

    def publish(
        self,
        *,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        publication_reference: str,
    ) -> CodingOwnerGenerationFamilyEvidence:
        return super().publish(
            family_id=family_id,
            instance_revision_ref=instance_revision_ref,
            receipts=receipts,
            publication_reference=publication_reference,
        )

    def retire(
        self,
        *,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        outcome_reference: str,
    ) -> CodingOwnerGenerationFamilyEvidence:
        return super().retire(
            family_id=family_id,
            instance_revision_ref=instance_revision_ref,
            receipts=receipts,
            outcome_reference=outcome_reference,
        )

    def family(self, family_id: str) -> CodingOwnerGenerationFamilyEvidence | None:
        return super().family(family_id)

    def retired_receipts_for_instance(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
    ) -> tuple[OwnerGenerationRetirementReceipt, ...]:
        return super().retired_receipts_for_instance(instance_revision_ref)

    def retired_families_for_instance(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
    ) -> tuple[CodingOwnerGenerationFamilyEvidence, ...]:
        return super().retired_families_for_instance(instance_revision_ref)


def _validate_receipts(receipts: tuple[OwnerGenerationRetirementReceipt, ...]) -> None:
    _validate_owner_receipts(receipts, label="Coding")


def _event_id(
    *,
    event_kind: CodingOwnerGenerationEventKind,
    family_id: str,
    instance_revision_ref: PluginInstanceRevisionRef,
    receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    outcome_reference: str,
) -> str:
    return _evidence_programs.event_identity(
        event_kind=event_kind,
        family_id=family_id,
        instance_revision_ref=instance_revision_ref,
        receipts=receipts,
        outcome_reference=outcome_reference,
    )


__all__ = [
    "CodingOwnerGenerationEvidenceError",
    "CodingOwnerGenerationEvidenceEventV1",
    "CodingOwnerGenerationEvidenceLedger",
    "CodingOwnerGenerationFamilyEvidence",
]
