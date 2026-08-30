"""Durable exact-owner evidence for Coding Plugin Session families."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
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


class CodingOwnerGenerationEvidenceLedger:
    """Append-only family binding from live publication to exact disposal."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    def prepare(
        self,
        *,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        preparation_reference: str,
    ) -> CodingOwnerGenerationFamilyEvidence:
        """Write exact cleanup identities before any owner becomes effective."""

        return self._append_transition(
            event_kind="prepared",
            family_id=family_id,
            instance_revision_ref=instance_revision_ref,
            receipts=receipts,
            outcome_reference=preparation_reference,
        )

    def publish(
        self,
        *,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        publication_reference: str,
    ) -> CodingOwnerGenerationFamilyEvidence:
        return self._append_transition(
            event_kind="published",
            family_id=family_id,
            instance_revision_ref=instance_revision_ref,
            receipts=receipts,
            outcome_reference=publication_reference,
        )

    def retire(
        self,
        *,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        outcome_reference: str,
    ) -> CodingOwnerGenerationFamilyEvidence:
        return self._append_transition(
            event_kind="retired",
            family_id=family_id,
            instance_revision_ref=instance_revision_ref,
            receipts=receipts,
            outcome_reference=outcome_reference,
        )

    def family(self, family_id: str) -> CodingOwnerGenerationFamilyEvidence | None:
        with journal_file_lock(
            self.path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            return self._replay(self._load_unlocked()).get(family_id)

    def retired_receipts_for_instance(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
    ) -> tuple[OwnerGenerationRetirementReceipt, ...]:
        families = self.retired_families_for_instance(instance_revision_ref)
        return _canonical_receipts(
            tuple(receipt for item in families for receipt in item.receipts)
        )

    def retired_families_for_instance(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
    ) -> tuple[CodingOwnerGenerationFamilyEvidence, ...]:
        with journal_file_lock(
            self.path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            families = self._replay(self._load_unlocked())
        matching = tuple(
            item
            for item in families.values()
            if item.instance_revision_ref == instance_revision_ref
        )
        pending = tuple(item.family_id for item in matching if not item.retired)
        if pending:
            raise CodingOwnerGenerationEvidenceError(
                "Coding owner generations remain live",
                code="coding_owner_generation_cleanup_pending",
                path=self.path,
            )
        return tuple(
            sorted(
                matching,
                key=lambda item: item.family_id,
            )
        )

    def _append_transition(
        self,
        *,
        event_kind: CodingOwnerGenerationEventKind,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        outcome_reference: str,
    ) -> CodingOwnerGenerationFamilyEvidence:
        canonical = _canonical_receipts(receipts)
        _validate_receipts(canonical)
        with journal_file_lock(
            self.path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            records = self._load_unlocked()
            families = self._replay(records)
            existing = families.get(family_id)
            if existing is None:
                if event_kind == "retired":
                    raise self._conflict(
                        "Coding owner retirement has no prepared generation"
                    )
                occupied = {
                    _receipt_identity(receipt): item.family_id
                    for item in families.values()
                    for receipt in item.receipts
                }
                if any(
                    identity in occupied
                    for identity in map(_receipt_identity, canonical)
                ):
                    raise self._conflict(
                        "Coding owner generation belongs to another Session family"
                    )
            else:
                if (
                    existing.instance_revision_ref != instance_revision_ref
                    or existing.receipts != canonical
                ):
                    raise self._conflict(
                        "Coding Session family reused owner generation evidence"
                    )
                if event_kind == "prepared":
                    return existing
                if event_kind == "published" and existing.publication_state in {
                    "published",
                    "retired",
                }:
                    return existing
                if event_kind == "retired" and existing.retired:
                    return existing
            event = CodingOwnerGenerationEvidenceEventV1.create(
                journal_revision=len(records) + 1,
                event_kind=event_kind,
                family_id=family_id,
                instance_revision_ref=instance_revision_ref,
                receipts=canonical,
                outcome_reference=outcome_reference,
            )
            append_jsonl_record(
                self.path,
                event,
                record_codec=CODING_OWNER_GENERATION_EVIDENCE_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return self._replay((*records, event))[family_id]

    def _load_unlocked(
        self,
    ) -> tuple[CodingOwnerGenerationEvidenceEventV1, ...]:
        if not self.path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[
                None,
                CodingOwnerGenerationEvidenceEventV1,
            ] = load_jsonl(
                self.path,
                record_codec=CODING_OWNER_GENERATION_EVIDENCE_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = snapshot.records
            if any(
                item.journal_revision != index
                for index, item in enumerate(records, start=1)
            ):
                raise ValueError("Coding owner evidence revisions are not contiguous")
            return records
        except (JournalCodecError, JournalFileError, ValueError) as exc:
            raise CodingOwnerGenerationEvidenceError(
                "Coding owner generation evidence journal is corrupt",
                code="coding_owner_generation_evidence_corrupt",
                path=self.path,
            ) from exc

    def _replay(
        self,
        records: tuple[CodingOwnerGenerationEvidenceEventV1, ...],
    ) -> dict[str, CodingOwnerGenerationFamilyEvidence]:
        families: dict[str, CodingOwnerGenerationFamilyEvidence] = {}
        receipt_owners: dict[
            tuple[str, str, str],
            str,
        ] = {}
        for event in records:
            existing = families.get(event.family_id)
            if event.event_kind in {"prepared", "published"} and existing is None:
                for receipt in event.receipts:
                    identity = _receipt_identity(receipt)
                    owner_family = receipt_owners.setdefault(identity, event.family_id)
                    if owner_family != event.family_id:
                        raise self._corrupt(
                            "Coding owner generation belongs to multiple families"
                        )
                families[event.family_id] = CodingOwnerGenerationFamilyEvidence(
                    family_id=event.family_id,
                    instance_revision_ref=event.instance_revision_ref,
                    receipts=event.receipts,
                    publication_state=event.event_kind,
                    retirement_outcome_reference=None,
                )
                continue
            if event.event_kind == "prepared":
                raise self._corrupt("Coding owner preparation repeats a family")
            if event.event_kind == "published":
                if (
                    existing is None
                    or existing.publication_state != "prepared"
                    or existing.instance_revision_ref != event.instance_revision_ref
                    or existing.receipts != event.receipts
                ):
                    raise self._corrupt(
                        "Coding owner publication contradicts its preparation"
                    )
                families[event.family_id] = CodingOwnerGenerationFamilyEvidence(
                    family_id=existing.family_id,
                    instance_revision_ref=existing.instance_revision_ref,
                    receipts=existing.receipts,
                    publication_state="published",
                    retirement_outcome_reference=None,
                )
                continue
            if (
                existing is None
                or existing.retired
                or existing.instance_revision_ref != event.instance_revision_ref
                or existing.receipts != event.receipts
            ):
                raise self._corrupt(
                    "Coding owner retirement contradicts its publication"
                )
            families[event.family_id] = CodingOwnerGenerationFamilyEvidence(
                family_id=existing.family_id,
                instance_revision_ref=existing.instance_revision_ref,
                receipts=existing.receipts,
                publication_state="retired",
                retirement_outcome_reference=event.outcome_reference,
            )
        return families

    def _conflict(self, message: str) -> CodingOwnerGenerationEvidenceError:
        return CodingOwnerGenerationEvidenceError(
            message,
            code="coding_owner_generation_evidence_conflict",
            path=self.path,
        )

    def _corrupt(self, message: str) -> CodingOwnerGenerationEvidenceError:
        return CodingOwnerGenerationEvidenceError(
            message,
            code="coding_owner_generation_evidence_corrupt",
            path=self.path,
        )


def _canonical_receipts(
    receipts: tuple[OwnerGenerationRetirementReceipt, ...],
) -> tuple[OwnerGenerationRetirementReceipt, ...]:
    return tuple(
        sorted(
            receipts,
            key=lambda item: (
                item.owner_reference,
                item.owner_generation_reference,
                item.retirement_handle,
                item.contribution_ids,
            ),
        )
    )


def _receipt_identity(
    receipt: OwnerGenerationRetirementReceipt,
) -> tuple[str, str, str]:
    return (
        receipt.owner_reference,
        receipt.owner_generation_reference,
        receipt.retirement_handle,
    )


def _validate_receipts(
    receipts: tuple[OwnerGenerationRetirementReceipt, ...],
) -> None:
    if not receipts:
        raise ValueError("Coding owner generation receipts must not be empty")
    if receipts != _canonical_receipts(receipts) or any(
        not isinstance(item, OwnerGenerationRetirementReceipt) for item in receipts
    ):
        raise ValueError("Coding owner generation receipts must be canonical")
    generations = tuple(
        (item.owner_reference, item.owner_generation_reference) for item in receipts
    )
    handles = tuple(item.retirement_handle for item in receipts)
    if len(generations) != len(set(generations)) or len(handles) != len(set(handles)):
        raise ValueError("Coding owner generation receipts must be exact and unique")


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
