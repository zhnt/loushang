"""Original exact-owner family evidence over the existing Journal."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Generic,
    Literal,
    Protocol,
    Self,
    TypeVar,
    cast,
)

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JournalRecordCodec,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
from loushang.harness.runtime.registration import OwnerGenerationRetirementReceipt

OwnerGenerationEventKind = Literal["prepared", "published", "retired"]


def owner_generation_event_payload(
    *,
    event_kind: OwnerGenerationEventKind,
    family_id: str,
    instance_revision_ref: PluginInstanceRevisionRef,
    receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    outcome_reference: str,
) -> dict[str, object]:
    return {
        "eventKind": event_kind,
        "familyId": family_id,
        "instanceRevisionRef": instance_revision_ref.to_dict(),
        "outcomeReference": outcome_reference,
        "receipts": [item.to_dict() for item in receipts],
    }


def owner_generation_event_identity(
    *,
    digest_domain: bytes,
    event_kind: OwnerGenerationEventKind,
    family_id: str,
    instance_revision_ref: PluginInstanceRevisionRef,
    receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    outcome_reference: str,
) -> str:
    payload = owner_generation_event_payload(
        event_kind=event_kind,
        family_id=family_id,
        instance_revision_ref=instance_revision_ref,
        receipts=receipts,
        outcome_reference=outcome_reference,
    )
    return sha256(digest_domain + StrictPluginJsonCodec.encode(payload)).hexdigest()


class _OwnerGenerationEvidenceEvent:
    """Canonical evidence record behavior for the product's nominal wire type."""

    __slots__ = ()

    if TYPE_CHECKING:
        _product_label: ClassVar[str]
        _event_digest_domain: ClassVar[bytes]
        _invalid_event_code: ClassVar[str]

        journal_revision: int
        event_id: str
        event_kind: OwnerGenerationEventKind
        family_id: str
        instance_revision_ref: PluginInstanceRevisionRef
        receipts: tuple[OwnerGenerationRetirementReceipt, ...]
        outcome_reference: str
        record_version: int

        def __init__(
            self,
            *,
            journal_revision: int,
            event_id: str,
            event_kind: OwnerGenerationEventKind,
            family_id: str,
            instance_revision_ref: PluginInstanceRevisionRef,
            receipts: tuple[OwnerGenerationRetirementReceipt, ...],
            outcome_reference: str,
            record_version: int = 1,
        ) -> None: ...

    def __post_init__(self) -> None:
        if (
            isinstance(self.journal_revision, bool)
            or not isinstance(self.journal_revision, int)
            or self.journal_revision < 1
        ):
            raise ValueError(
                f"{self._product_label} owner evidence revision must be positive"
            )
        if self.event_kind not in {"prepared", "published", "retired"}:
            raise ValueError(f"{self._product_label} owner evidence kind is invalid")
        for value, name in (
            (self.family_id, "family id"),
            (self.outcome_reference, "outcome reference"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{self._product_label} owner evidence {name} must not be empty"
                )
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError(
                f"{self._product_label} owner evidence Instance reference is invalid"
            )
        _validate_receipts(self.receipts, label=self._product_label)
        if self.record_version != 1:
            raise ValueError(
                f"Unsupported {self._product_label} owner evidence version"
            )
        if self.event_id != owner_generation_event_identity(
            digest_domain=self._event_digest_domain,
            event_kind=self.event_kind,
            family_id=self.family_id,
            instance_revision_ref=self.instance_revision_ref,
            receipts=self.receipts,
            outcome_reference=self.outcome_reference,
        ):
            raise ValueError(f"{self._product_label} owner evidence id does not match")

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        event_kind: OwnerGenerationEventKind,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        outcome_reference: str,
    ) -> Self:
        canonical = _canonical_receipts(receipts)
        return cls(
            journal_revision=journal_revision,
            event_id=owner_generation_event_identity(
                digest_domain=cls._event_digest_domain,
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
        payload = owner_generation_event_payload(
            event_kind=self.event_kind,
            family_id=self.family_id,
            instance_revision_ref=self.instance_revision_ref,
            receipts=self.receipts,
            outcome_reference=self.outcome_reference,
        )
        payload.update(
            eventId=self.event_id,
            journalRevision=self.journal_revision,
            recordVersion=self.record_version,
        )
        return dict(sorted(payload.items()))

    @classmethod
    def from_dict(
        cls,
        value: object,
    ) -> Self:
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
                raise ValueError(
                    f"{cls._product_label} owner evidence fields are invalid"
                )
            raw_receipts = value["receipts"]
            if not isinstance(raw_receipts, list):
                raise TypeError(
                    f"{cls._product_label} owner evidence receipts must be an array"
                )
            return cls(
                journal_revision=cast(int, value["journalRevision"]),
                event_id=cast(str, value["eventId"]),
                event_kind=cast(OwnerGenerationEventKind, value["eventKind"]),
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
                code=cls._invalid_event_code,
            ) from exc


class _Family(Protocol):
    @property
    def family_id(self) -> str: ...
    @property
    def instance_revision_ref(self) -> PluginInstanceRevisionRef: ...
    @property
    def receipts(self) -> tuple[OwnerGenerationRetirementReceipt, ...]: ...
    @property
    def publication_state(self) -> OwnerGenerationEventKind: ...
    @property
    def retired(self) -> bool: ...
    @property
    def retirement_outcome_reference(self) -> str | None: ...
    def __init__(
        self,
        *,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        publication_state: OwnerGenerationEventKind,
        retirement_outcome_reference: str | None,
    ) -> None: ...


class _EvidenceErrorFactory(Protocol):
    def __call__(self, message: str, *, code: str, path: Path) -> RuntimeError: ...


EventT = TypeVar("EventT", bound=_OwnerGenerationEvidenceEvent)
FamilyT = TypeVar("FamilyT", bound=_Family)


class _OwnerGenerationEvidenceLedger(Generic[EventT, FamilyT]):
    """Append-only family binding from live publication to exact disposal."""

    _event_type: type[EventT]
    _family_type: type[FamilyT]
    _record_codec: JournalRecordCodec[EventT]
    _error_type: _EvidenceErrorFactory
    _error_code_prefix: str
    _product_label: str

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
    ) -> FamilyT:
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
    ) -> FamilyT:
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
    ) -> FamilyT:
        return self._append_transition(
            event_kind="retired",
            family_id=family_id,
            instance_revision_ref=instance_revision_ref,
            receipts=receipts,
            outcome_reference=outcome_reference,
        )

    def family(self, family_id: str) -> FamilyT | None:
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
    ) -> tuple[FamilyT, ...]:
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
            raise self._error_type(
                f"{self._product_label} owner generations remain live",
                code=f"{self._error_code_prefix}_cleanup_pending",
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
        event_kind: OwnerGenerationEventKind,
        family_id: str,
        instance_revision_ref: PluginInstanceRevisionRef,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
        outcome_reference: str,
    ) -> FamilyT:
        canonical = _canonical_receipts(receipts)
        _validate_receipts(canonical, label=self._product_label)
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
                        f"{self._product_label} owner retirement has no prepared generation"
                    )
                if event_kind == "published":
                    raise self._conflict(
                        f"{self._product_label} owner publication requires prepared generation"
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
                        f"{self._product_label} owner generation belongs to another Session family"
                    )
            else:
                if (
                    existing.instance_revision_ref != instance_revision_ref
                    or existing.receipts != canonical
                ):
                    raise self._conflict(
                        f"{self._product_label} Session family reused owner generation evidence"
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
            event = self._event_type.create(
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
                record_codec=self._record_codec,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return self._replay((*records, event))[family_id]

    def _load_unlocked(
        self,
    ) -> tuple[EventT, ...]:
        if not self.path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[
                None,
                EventT,
            ] = load_jsonl(
                self.path,
                record_codec=self._record_codec,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = snapshot.records
            if any(
                item.journal_revision != index
                for index, item in enumerate(records, start=1)
            ):
                raise ValueError(
                    f"{self._product_label} owner evidence revisions are not contiguous"
                )
            return records
        except (JournalCodecError, JournalFileError, ValueError) as exc:
            raise self._error_type(
                f"{self._product_label} owner generation evidence journal is corrupt",
                code=f"{self._error_code_prefix}_evidence_corrupt",
                path=self.path,
            ) from exc

    def _replay(
        self,
        records: tuple[EventT, ...],
    ) -> dict[str, FamilyT]:
        families: dict[str, FamilyT] = {}
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
                            f"{self._product_label} owner generation belongs to multiple families"
                        )
                families[event.family_id] = self._family_type(
                    family_id=event.family_id,
                    instance_revision_ref=event.instance_revision_ref,
                    receipts=event.receipts,
                    publication_state=event.event_kind,
                    retirement_outcome_reference=None,
                )
                continue
            if event.event_kind == "prepared":
                raise self._corrupt(
                    f"{self._product_label} owner preparation repeats a family"
                )
            if event.event_kind == "published":
                if (
                    existing is None
                    or existing.publication_state != "prepared"
                    or existing.instance_revision_ref != event.instance_revision_ref
                    or existing.receipts != event.receipts
                ):
                    raise self._corrupt(
                        f"{self._product_label} owner publication contradicts its preparation"
                    )
                families[event.family_id] = self._family_type(
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
                    f"{self._product_label} owner retirement contradicts its publication"
                )
            families[event.family_id] = self._family_type(
                family_id=existing.family_id,
                instance_revision_ref=existing.instance_revision_ref,
                receipts=existing.receipts,
                publication_state="retired",
                retirement_outcome_reference=event.outcome_reference,
            )
        return families

    def _conflict(self, message: str) -> RuntimeError:
        return self._error_type(
            message,
            code=f"{self._error_code_prefix}_evidence_conflict",
            path=self.path,
        )

    def _corrupt(self, message: str) -> RuntimeError:
        return self._error_type(
            message,
            code=f"{self._error_code_prefix}_evidence_corrupt",
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
    *,
    label: str,
) -> None:
    if not receipts:
        raise ValueError(f"{label} owner generation receipts must not be empty")
    if receipts != _canonical_receipts(receipts) or any(
        not isinstance(item, OwnerGenerationRetirementReceipt) for item in receipts
    ):
        raise ValueError(f"{label} owner generation receipts must be canonical")
    generations = tuple(
        (item.owner_reference, item.owner_generation_reference) for item in receipts
    )
    handles = tuple(item.retirement_handle for item in receipts)
    if len(generations) != len(set(generations)) or len(handles) != len(set(handles)):
        raise ValueError(f"{label} owner generation receipts must be exact and unique")
