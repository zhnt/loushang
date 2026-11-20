"""Durable exact-owner evidence for Coding Plugin Session families."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalCodecError,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
)
from loushang.harness.session.plugin_lifecycle._owner_evidence import (
    _canonical_receipts,
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
        if (
            isinstance(self.journal_revision, bool)
            or not isinstance(self.journal_revision, int)
            or self.journal_revision < 1
        ):
            raise ValueError("Coding owner evidence revision must be positive")
        if self.event_kind not in {"prepared", "published", "retired"}:
            raise ValueError("Coding owner evidence kind is invalid")
        for value, name in (
            (self.family_id, "family id"),
            (self.outcome_reference, "outcome reference"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Coding owner evidence {name} must not be empty")
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Coding owner evidence Instance reference is invalid")
        _validate_receipts(self.receipts)
        if self.record_version != 1:
            raise ValueError("Unsupported Coding owner evidence version")
        if self.event_id != _event_id(
            event_kind=self.event_kind,
            family_id=self.family_id,
            instance_revision_ref=self.instance_revision_ref,
            receipts=self.receipts,
            outcome_reference=self.outcome_reference,
        ):
            raise ValueError("Coding owner evidence id does not match")

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
        canonical = _canonical_receipts(receipts)
        return cls(
            journal_revision=journal_revision,
            event_id=_event_id(
                event_kind=event_kind,
                family_id=family_id,
                instance_revision_ref=instance_revision_ref,
                receipts=canonical,
                outcome_reference=outcome_reference,
            ),
            event_kind=event_kind,
            family_id=family_id,
            instance_revision_ref=instance_revision_ref,
            receipts=canonical,
            outcome_reference=outcome_reference,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "eventId": self.event_id,
            "eventKind": self.event_kind,
            "familyId": self.family_id,
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "journalRevision": self.journal_revision,
            "outcomeReference": self.outcome_reference,
            "receipts": [item.to_dict() for item in self.receipts],
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(
        cls,
        value: object,
    ) -> CodingOwnerGenerationEvidenceEventV1:
        try:
            if not isinstance(value, dict) or set(value) != {
                "eventId",
                "eventKind",
                "familyId",
                "instanceRevisionRef",
                "journalRevision",
                "outcomeReference",
                "receipts",
                "recordVersion",
            }:
                raise ValueError("Coding owner evidence fields are invalid")
            raw_receipts = value["receipts"]
            if not isinstance(raw_receipts, list):
                raise TypeError("Coding owner evidence receipts must be an array")
            return cls(
                journal_revision=cast(int, value["journalRevision"]),
                event_id=cast(str, value["eventId"]),
                event_kind=cast(CodingOwnerGenerationEventKind, value["eventKind"]),
                family_id=cast(str, value["familyId"]),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    value["instanceRevisionRef"]
                ),
                receipts=tuple(
                    OwnerGenerationRetirementReceipt.from_dict(item)
                    for item in raw_receipts
                ),
                outcome_reference=cast(str, value["outcomeReference"]),
                record_version=cast(int, value["recordVersion"]),
            )
        except JournalCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                str(exc),
                code="invalid_coding_owner_generation_evidence",
            ) from exc


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
    return hashlib.sha256(
        b"loushang.coding-owner-generation-evidence/v1\0"
        + StrictPluginJsonCodec.encode(
            {
                "eventKind": event_kind,
                "familyId": family_id,
                "instanceRevisionRef": instance_revision_ref.to_dict(),
                "outcomeReference": outcome_reference,
                "receipts": [item.to_dict() for item in receipts],
            }
        )
    ).hexdigest()


__all__ = [
    "CodingOwnerGenerationEvidenceError",
    "CodingOwnerGenerationEvidenceEventV1",
    "CodingOwnerGenerationEvidenceLedger",
    "CodingOwnerGenerationFamilyEvidence",
]
