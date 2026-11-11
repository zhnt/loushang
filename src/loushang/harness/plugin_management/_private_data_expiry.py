"""Backup-expiry histories and POSIX Journal over the existing storage owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import ClassVar, Generic, Literal, Protocol, TypeVar

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

from .records import PluginInstallationKeyV1


class ExpiryPlan(Protocol):
    @property
    def installation_key(self) -> PluginInstallationKeyV1: ...
    @property
    def backup_id(self) -> str: ...


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
_PlanT = TypeVar("_PlanT", bound=ExpiryPlan)
_ConfirmationT = TypeVar("_ConfirmationT")
_ArchiveT = TypeVar("_ArchiveT")
_EventT = TypeVar("_EventT", bound=ExpiryHistoryEvent)


class ExpiryAdvance(Generic[_AdvanceEventT]):
    """One original checkpoint advance; stores retain scanning and publication."""

    __slots__ = ()
    _label: ClassVar[str]

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
    ExpiryAdvance[_EventT], Generic[_PlanT, _ConfirmationT, _ArchiveT, _EventT]
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
            events = self._load(self._write_policy)
            if events and events[-1].phase != "completed":
                last = events[-1]
                if last.plan == plan and last.confirmation == confirmation:
                    return confirmation
                raise ValueError(f"Another {self._label} backup expiry is unfinished")
            if events and events[-1].plan == plan:
                if events[-1].confirmation == confirmation:
                    return confirmation
                raise ValueError(f"{self._label} backup expiry was already completed")
            if any(
                event.phase == "completed" and event.plan.backup_id == plan.backup_id
                for event in events
            ):
                raise ValueError(f"{self._label} backup expiry was already completed")
            event = self._event_factory(
                revision=len(events) + 1,
                phase="confirmed",
                plan=plan,
                confirmation=confirmation,
            )
            self._append(event)
            return confirmation

    def begin(
        self,
        plan: _PlanT,
        confirmation: _ConfirmationT,
        archive: _ArchiveT,
    ) -> _EventT:
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load(self._write_policy)
            if not events or (
                events[-1].plan != plan or events[-1].confirmation != confirmation
            ):
                raise ValueError(f"{self._label} backup expiry confirmation changed")
            last = events[-1]
            if last.phase != "confirmed":
                if last.archive == archive:
                    return last
                raise ValueError(f"{self._label} backup expiry archive changed")
            event = self._event_factory(
                revision=len(events) + 1,
                phase="started",
                plan=plan,
                confirmation=confirmation,
                archive=archive,
            )
            self._append(event)
            return event

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
