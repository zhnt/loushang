"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from typing import cast

from loushang.coding.plugin_manager import owner_generations as _binding


def validate_event(self: _binding.CodingOwnerGenerationEvidenceEventV1) -> None:
    if (
        isinstance(self.journal_revision, bool)
        or not isinstance(self.journal_revision, int)
        or self.journal_revision < 1
    ):
        raise ValueError(_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_002"])
    if self.event_kind not in {"prepared", "published", "retired"}:
        raise ValueError(_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_003"])
    for value, name in (
        (self.family_id, "family id"),
        (self.outcome_reference, "outcome reference"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{_binding._OWNER_EVIDENCE_PROGRAM_VALUES['value_001']}{name} must not be empty"
            )
    if not isinstance(self.instance_revision_ref, _binding.PluginInstanceRevisionRef):
        raise TypeError(_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_004"])
    _binding._validate_receipts(self.receipts)
    if self.record_version != 1:
        raise ValueError(_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_005"])
    if self.event_id != _binding._event_id(
        event_kind=self.event_kind,
        family_id=self.family_id,
        instance_revision_ref=self.instance_revision_ref,
        receipts=self.receipts,
        outcome_reference=self.outcome_reference,
    ):
        raise ValueError(_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_006"])


def create_event(
    cls: type[_binding.CodingOwnerGenerationEvidenceEventV1],
    *,
    journal_revision: int,
    event_kind: _binding.CodingOwnerGenerationEventKind,
    family_id: str,
    instance_revision_ref: _binding.PluginInstanceRevisionRef,
    receipts: tuple[_binding.OwnerGenerationRetirementReceipt, ...],
    outcome_reference: str,
) -> _binding.CodingOwnerGenerationEvidenceEventV1:
    canonical = _binding._canonical_receipts(receipts)
    return cls(
        journal_revision=journal_revision,
        event_id=_binding._event_id(
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


def encode_event(
    self: _binding.CodingOwnerGenerationEvidenceEventV1,
) -> dict[str, object]:
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


def decode_event(
    cls: type[_binding.CodingOwnerGenerationEvidenceEventV1], value: object
) -> _binding.CodingOwnerGenerationEvidenceEventV1:
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
            raise ValueError(_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_007"])
        raw_receipts = value["receipts"]
        if not isinstance(raw_receipts, list):
            raise TypeError(_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_008"])
        return cls(
            journal_revision=cast(int, value["journalRevision"]),
            event_id=cast(str, value["eventId"]),
            event_kind=cast(
                _binding.CodingOwnerGenerationEventKind, value["eventKind"]
            ),
            family_id=cast(str, value["familyId"]),
            instance_revision_ref=_binding.PluginInstanceRevisionRef.from_dict(
                value["instanceRevisionRef"]
            ),
            receipts=tuple(
                _binding.OwnerGenerationRetirementReceipt.from_dict(item)
                for item in raw_receipts
            ),
            outcome_reference=cast(str, value["outcomeReference"]),
            record_version=cast(int, value["recordVersion"]),
        )
    except _binding.JournalCodecError:
        raise
    except (TypeError, ValueError) as exc:
        raise _binding.JournalCodecError(
            str(exc),
            code=_binding._OWNER_EVIDENCE_PROGRAM_VALUES["value_009"],
        ) from exc


def event_identity(
    *,
    event_kind: _binding.CodingOwnerGenerationEventKind,
    family_id: str,
    instance_revision_ref: _binding.PluginInstanceRevisionRef,
    receipts: tuple[_binding.OwnerGenerationRetirementReceipt, ...],
    outcome_reference: str,
) -> str:
    return _binding.hashlib.sha256(
        _binding._OWNER_EVIDENCE_PROGRAM_BYTES["value_001"]
        + _binding.StrictPluginJsonCodec.encode(
            {
                "eventKind": event_kind,
                "familyId": family_id,
                "instanceRevisionRef": instance_revision_ref.to_dict(),
                "outcomeReference": outcome_reference,
                "receipts": [item.to_dict() for item in receipts],
            }
        )
    ).hexdigest()
