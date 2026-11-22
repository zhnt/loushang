"""Backup-expiry histories and POSIX Journal over the existing storage owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import ClassVar, Generic, Literal, Protocol, Self, TypeVar

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    JournalLoadPolicy,
    JournalRecordCodec,
    JsonlJournal,
    JsonlSnapshot,
    journal_file_lock,
    journal_file_read_lock,
)
from loushang.harness.journal._path_admission import (
    private_journal_exists,
    require_private_journal_parent,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
    decode_nullable,
)

from .private_data_restore_journal import (
    PrivateDataRestoreConfirmation,
    PrivateDataRestoreEvent,
)
from .records import PluginInstallationKeyV1


class ExpiryPlan(Protocol):
    @property
    def installation_key(self) -> PluginInstallationKeyV1: ...
    @property
    def backup_id(self) -> str: ...
    @property
    def source_target_id(self) -> str: ...
    @property
    def desired_inventory_revision(self) -> int: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def confirmation_id(self) -> str: ...
    @property
    def restore_completion_digest(self) -> str: ...
    @property
    def restored_target_id(self) -> str: ...
    @property
    def archive_root_identity(self) -> tuple[int, int, int, int, int]: ...
    @property
    def archive_target_id(self) -> str: ...


class ExpiryHistoryEvent(Protocol):
    @property
    def revision(self) -> int: ...
    @property
    def phase(self) -> str: ...
    @property
    def plan(self) -> ExpiryPlan: ...
    @property
    def confirmation(self) -> object: ...
    @property
    def archive(self) -> object: ...
    @property
    def record_version(self) -> int: ...
    @property
    def receipt(self) -> object | None: ...


class _ExpiryWireRecord(Protocol):
    @classmethod
    def from_dict(cls, value: object) -> Self: ...

    def to_dict(self) -> dict[str, object]: ...


def expiry_event_schema(
    event_type: type[ExpiryHistoryEvent],
    *,
    plan: type[_ExpiryWireRecord],
    confirmation: type[_ExpiryWireRecord],
    archive: type[_ExpiryWireRecord],
    receipt: type[_ExpiryWireRecord],
) -> RecordSchema:
    """Use the same nested record fields for both native expiry journals."""
    return RecordSchema.for_dataclass(
        event_type,
        lambda value: value,
        RecordField("plan", decoder=plan.from_dict, encoder=plan.to_dict),
        RecordField(
            "confirmation", decoder=confirmation.from_dict, encoder=confirmation.to_dict
        ),
        RecordField(
            "archive", decoder=partial(decode_nullable, decoder=archive.from_dict),
            encoder=_encode_optional,
        ),
        RecordField(
            "receipt", decoder=partial(decode_nullable, decoder=receipt.from_dict),
            encoder=_encode_optional,
        ),
    )


def _encode_optional(value: _ExpiryWireRecord | None) -> dict[str, object] | None:
    return None if value is None else value.to_dict()


class _ExpiryConfirmation(Protocol):
    @property
    def plan_fingerprint(self) -> str: ...


class _ArchiveReference(Protocol):
    @property
    def root_identity(self) -> tuple[int, int, int, int, int] | None: ...
    @property
    def target_id(self) -> str: ...


_PlanT = TypeVar("_PlanT", bound=ExpiryPlan)
_RecordConfirmationT = TypeVar("_RecordConfirmationT", bound=_ExpiryConfirmation)


def matches_expiry_archive(archive: _ArchiveReference, plan: ExpiryPlan) -> bool:
    return (
        archive.root_identity == plan.archive_root_identity
        and archive.target_id == plan.archive_target_id
    )


def validate_expiry_event(
    event: ExpiryHistoryEvent,
    *,
    plan_type: type[_PlanT],
    confirmation_type: type[_RecordConfirmationT],
    archive_type: type[_ArchiveReference],
    receipt_for: Callable[[_PlanT, _RecordConfirmationT], object],
    label: str,
    unstarted_effects_error: str,
    unfinished_receipt_error: str,
    receipt_type: type | None = None,
) -> None:
    if (
        type(event.revision) is not int
        or event.revision < 1
        or event.phase not in {"confirmed", "started", "renamed", "completed"}
    ):
        raise ValueError(f"{label} backup expiry event is invalid")
    plan, confirmation = event.plan, event.confirmation
    if (
        not isinstance(plan, plan_type)
        or not isinstance(confirmation, confirmation_type)
        or confirmation.plan_fingerprint != plan.fingerprint
        or event.record_version != 1
    ):
        raise ValueError(f"{label} backup expiry event is invalid")
    archive, receipt = event.archive, event.receipt
    if event.phase == "confirmed":
        if archive is not None or receipt is not None:
            raise ValueError(unstarted_effects_error)
        return
    if not isinstance(archive, archive_type) or not matches_expiry_archive(
        archive, plan
    ):
        raise ValueError(f"{label} backup expiry archive changed")
    if event.phase == "completed":
        if (
            receipt_type is not None and not isinstance(receipt, receipt_type)
        ) or receipt != receipt_for(plan, confirmation):
            raise ValueError(f"{label} backup expiry receipt changed")
    elif receipt is not None:
        raise ValueError(unfinished_receipt_error)


def require_expiry_restore_history(
    plan: ExpiryPlan,
    *,
    confirmations: Callable[[], tuple[PrivateDataRestoreConfirmation, ...]],
    restores: Callable[[], tuple[PrivateDataRestoreEvent, ...]],
    label: str,
) -> None:
    if not any(
        item.installation_key == plan.installation_key
        and item.backup_id == plan.backup_id
        and item.confirmation_id == plan.confirmation_id
        and item.restore_completion_digest == plan.restore_completion_digest
        and item.restored_target_id == plan.restored_target_id
        for item in confirmations()
    ):
        raise ValueError(f"{label} backup expiry confirmation changed")
    if not any(
        item.phase == "completed"
        and item.installation_key == plan.installation_key
        and item.backup_id == plan.backup_id
        and item.record_digest == plan.restore_completion_digest
        for item in restores()
    ):
        raise ValueError(f"{label} backup expiry restore history changed")


def validate_expiry_history(
    events: tuple[ExpiryHistoryEvent, ...], *, label: str
) -> None:
    previous: ExpiryHistoryEvent | None = None
    completed: set[str] = set()
    for revision, event in enumerate(events, start=1):
        if event.revision != revision:
            raise ValueError(f"{label} backup expiry revision changed")
        if event.phase == "confirmed":
            if previous is not None and previous.phase != "completed":
                raise ValueError(f"{label} backup expiry history overlaps")
            if event.plan.backup_id in completed:
                raise ValueError(f"{label} backup expiry was repeated")
        elif (
            previous is None
            or previous.plan != event.plan
            or previous.confirmation != event.confirmation
            or (event.phase == "started" and previous.phase != "confirmed")
            or (event.phase == "renamed" and previous.phase != "started")
            or (event.phase == "completed" and previous.phase != "renamed")
            or (
                event.phase in {"renamed", "completed"}
                and previous.archive != event.archive
            )
        ):
            raise ValueError(f"{label} backup expiry history changed")
        if event.phase == "completed":
            completed.add(event.plan.backup_id)
        previous = event


_AdvanceEventT = TypeVar("_AdvanceEventT", bound=ExpiryHistoryEvent)
_ConfirmationT = TypeVar("_ConfirmationT")
_ArchiveT = TypeVar("_ArchiveT")
_EventT = TypeVar("_EventT", bound=ExpiryHistoryEvent)


class ExpiryJournalTransitions(Generic[_AdvanceEventT]):
    """Exact confirmation and checkpoints over the native expiry journals."""

    __slots__ = ()
    _label: ClassVar[str]
    _completed_phrase: ClassVar[str] = "was already completed"

    @property
    def _event_factory(self) -> Callable[..., _AdvanceEventT]:
        raise NotImplementedError

    @property
    def _receipt_factory(self) -> Callable[..., object]:
        raise NotImplementedError

    def _scan(self) -> tuple[tuple[_AdvanceEventT, ...], int | None]:
        raise NotImplementedError

    def _append_current(
        self,
        before: tuple[_AdvanceEventT, ...],
        staged: int | None,
        event: _AdvanceEventT,
    ) -> _AdvanceEventT:
        raise NotImplementedError

    def _record_confirmation(self, plan: ExpiryPlan, confirmation: object) -> None:
        events, staged = self._scan()
        completed_error = f"{self._label} backup expiry {self._completed_phrase}"
        if events:
            last = events[-1]
            if last.phase != "completed":
                if staged is not None:
                    message = f"{self._label} backup expiry event needs recovery"
                    raise ValueError(message)
                if last.plan == plan and last.confirmation == confirmation:
                    return
                raise ValueError(f"Another {self._label} backup expiry is unfinished")
            if last.plan == plan:
                if staged is not None or last.confirmation != confirmation:
                    raise ValueError(completed_error)
                return
            if any(
                event.phase == "completed" and event.plan.backup_id == plan.backup_id
                for event in events
            ):
                raise ValueError(completed_error)
        event = self._event_factory(
            revision=len(events) + 1,
            phase="confirmed",
            plan=plan,
            confirmation=confirmation,
        )
        self._append_current(events, staged, event)

    def _begin_current(
        self, plan: ExpiryPlan, confirmation: object, archive: object
    ) -> _AdvanceEventT:
        events, staged = self._scan()
        if not events or (
            events[-1].plan != plan or events[-1].confirmation != confirmation
        ):
            raise ValueError(f"{self._label} backup expiry confirmation changed")
        prior = events[-1]
        if prior.phase != "confirmed":
            if staged is not None or prior.archive != archive:
                raise ValueError(f"{self._label} backup expiry archive changed")
            return prior
        event = self._event_factory(
            revision=len(events) + 1,
            phase="started",
            plan=plan,
            confirmation=confirmation,
            archive=archive,
        )
        return self._append_current(events, staged, event)

    def _advance_current(
        self, prior: _AdvanceEventT, phase: Literal["renamed", "completed"]
    ) -> _AdvanceEventT:
        events, staged = self._scan()
        if not events or events[-1] != prior:
            raise ValueError(f"{self._label} backup expiry checkpoint changed")
        if prior.phase == phase:
            if staged is not None:
                raise ValueError(f"{self._label} backup expiry event needs recovery")
            return prior
        if (phase == "renamed" and prior.phase != "started") or (
            phase == "completed" and prior.phase != "renamed"
        ):
            raise ValueError(f"{self._label} backup expiry checkpoint is out of order")
        event = self._event_factory(
            revision=len(events) + 1,
            phase=phase,
            plan=prior.plan,
            confirmation=prior.confirmation,
            archive=prior.archive,
            receipt=(
                self._receipt_factory(prior.plan, prior.confirmation)
                if phase == "completed"
                else None
            ),
        )
        return self._append_current(events, staged, event)


class PrivateDataExpiryJournal(
    ExpiryJournalTransitions[_EventT],
    Generic[_PlanT, _ConfirmationT, _ArchiveT, _EventT],
):
    """One append-only exact attempt at a time in the Product state root."""

    def __init__(self, path: Path, *, codec: JournalRecordCodec[_EventT]) -> None:
        self._path = path
        self._journal: JsonlJournal[None, _EventT] = JsonlJournal(
            path,
            record_codec=codec,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=replace(DURABLE_LOCKED_JOURNAL, locking=False),
        )
        self._write_policy = JournalLoadPolicy(partial_tail="repair")
        self._read_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)

    @property
    def path(self) -> Path:
        return self._path

    def events(self) -> tuple[_EventT, ...]:
        self._require_private_parent()
        with journal_file_read_lock(self._path, "shared", create_lock=False):
            return self._load(self._read_policy)

    def confirm(
        self,
        plan: _PlanT,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> _ConfirmationT:
        confirmation = self._confirmation_factory(
            plan, actor_id=actor_id, policy_revision=policy_revision
        )
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            self._record_confirmation(plan, confirmation)
        return confirmation

    def begin(
        self,
        plan: _PlanT,
        confirmation: _ConfirmationT,
        archive: _ArchiveT,
    ) -> _EventT:
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            return self._begin_current(plan, confirmation, archive)

    def advance(
        self, prior: _EventT, phase: Literal["renamed", "completed"]
    ) -> _EventT:
        if phase not in {"renamed", "completed"}:
            raise ValueError(f"{self._label} backup expiry transition is invalid")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            return self._advance_current(prior, phase)

    def _append(self, event: _EventT) -> None:
        if event.revision > self._max_records:
            raise ValueError(f"{self._label} backup expiry journal is full")
        self._journal.append(event)

    def _load(self, policy: JournalLoadPolicy) -> tuple[_EventT, ...]:
        if not private_journal_exists(
            self._path,
            message=f"{self._label} backup expiry journal is unsafe",
            posix_only=False,
            max_bytes=self._max_bytes,
        ):
            return ()
        loaded: JsonlSnapshot[None, _EventT] = self._journal.load(
            load_policy=replace(policy, collect_duplicate_keys=True)
        )
        loaded.require_unique_keys(f"{self._label} backup expiry repeats a field")
        events = loaded.records
        if len(events) > self._max_records:
            raise ValueError(f"{self._label} backup expiry journal is full")
        validate_expiry_history(events, label=self._label)
        return events

    def _require_private_parent(self) -> None:
        require_private_journal_parent(
            self._path,
            message=f"{self._label} backup expiry state root is not private",
            posix_only=False,
        )

    @property
    def _confirmation_factory(self) -> Callable[..., _ConfirmationT]:
        raise NotImplementedError

    @property
    def _max_records(self) -> int:
        raise NotImplementedError

    @property
    def _max_bytes(self) -> int:
        raise NotImplementedError

    def _scan(self) -> tuple[tuple[_EventT, ...], int | None]:
        return self._load(self._write_policy), None

    def _append_current(
        self, before: tuple[_EventT, ...], staged: int | None, event: _EventT
    ) -> _EventT:
        self._append(event)
        return event
