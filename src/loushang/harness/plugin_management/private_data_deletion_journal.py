"""Exact deletion action history over the original Journal and pathname admission.

The caller retains Product quiescence. This owner keeps the original POSIX
phase/replay contract and does not perform native deletion or authorize it.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Generic, TypeVar

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

from .private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionEventV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
    PrivateDataDeletionTarget,
)

_TargetT = TypeVar("_TargetT", bound=PrivateDataDeletionTarget)
_EventT = TypeVar(
    "_EventT", bound=PluginPrivateDataDeletionEventV1[PrivateDataDeletionTarget]
)


class PrivateDataDeletionJournal(Generic[_TargetT, _EventT]):
    """Own exact deletion phases and replay; the caller retains the Product fence."""

    def __init__(
        self,
        path: Path,
        *,
        event_type: type[_EventT],
        codec: JournalRecordCodec[_EventT],
        label: str,
    ) -> None:
        self._path = path
        self._event_type = event_type
        self._label = label
        self._journal: JsonlJournal[None, _EventT] = JsonlJournal(
            self._path,
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
        self._require_safe_journal()
        with journal_file_read_lock(self._path, "shared", create_lock=False):
            return self._load_unlocked(self._read_policy)

    def started_for(self, plan: PluginPrivateDataDeletionPlanV1) -> _EventT | None:
        events = self.events()
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if event.plan.installation_key == plan.installation_key:
                if event.phase == "completed":
                    return None
                return event if event.plan == plan else None
        return None

    def current_start(self) -> _EventT | None:
        return _open_start(self.events())

    def receipt_for(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1 | None:
        for event in reversed(self.events()):
            if (
                event.phase == "completed"
                and event.plan == plan
                and event.confirmation == confirmation
            ):
                return event.receipt
        return None

    def record_start(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
        target: _TargetT,
    ) -> _EventT:
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load_unlocked(self._write_policy)
            open_start = _open_start(events)
            if open_start is not None:
                if (
                    open_start.plan == plan
                    and open_start.confirmation == confirmation
                    and open_start.target == target
                ):
                    return open_start
                raise ValueError("Another private-data deletion is unfinished")
            if any(
                event.phase == "completed"
                and event.confirmation.confirmation_id == confirmation.confirmation_id
                for event in events
            ):
                raise ValueError("Private-data confirmation was already consumed")
            event = self._event_type(
                revision=len(events) + 1,
                phase="started",
                plan=plan,
                confirmation=confirmation,
                target=target,
            )
            self._append(event)
            return event

    def record_completion(
        self,
        started: _EventT,
        receipt: PluginPrivateDataDeletionReceiptV1,
    ) -> _EventT:
        if started.phase not in {"started", "renamed"}:
            raise ValueError("Private-data deletion start is required")
        if (started.target.root_identity is None) != (started.phase == "started"):
            raise ValueError("Private-data deletion rename evidence is required")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load_unlocked(self._write_policy)
            if not events or _open_start(events) != started:
                replay = next(
                    (
                        event
                        for event in reversed(events)
                        if event.phase == "completed"
                        and event.plan == started.plan
                        and event.confirmation == started.confirmation
                    ),
                    None,
                )
                if replay is not None and replay.receipt == receipt:
                    return replay
                raise ValueError("Private-data deletion start changed")
            event = self._event_type(
                revision=len(events) + 1,
                phase="completed",
                plan=started.plan,
                confirmation=started.confirmation,
                target=started.target,
                receipt=receipt,
            )
            self._append(event)
            return event

    def record_renamed(self, started: _EventT) -> _EventT:
        if (
            started.phase not in {"started", "renamed"}
            or started.target.root_identity is None
        ):
            raise ValueError("Present private-data deletion start is required")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            events = self._load_unlocked(self._write_policy)
            current = _open_start(events)
            if current is None or (
                current.plan != started.plan
                or current.confirmation != started.confirmation
                or current.target != started.target
            ):
                raise ValueError("Private-data deletion start changed")
            if current.phase == "renamed":
                return current
            event = self._event_type(
                revision=len(events) + 1,
                phase="renamed",
                plan=started.plan,
                confirmation=started.confirmation,
                target=started.target,
            )
            self._append(event)
            return event

    def _append(self, event: _EventT) -> None:
        self._journal.append(event)

    def _load_unlocked(self, policy: JournalLoadPolicy) -> tuple[_EventT, ...]:
        if not self._require_safe_journal():
            return ()
        loaded: JsonlSnapshot[None, _EventT] = self._journal.load(
            load_policy=replace(policy, collect_duplicate_keys=True)
        )
        loaded.require_unique_keys(
            "Private-data deletion record has a duplicate JSON key"
        )
        events = loaded.records
        pending: _EventT | None = None
        seen_confirmations: set[str] = set()
        for revision, event in enumerate(events, start=1):
            if event.revision != revision:
                raise ValueError("Private-data deletion revisions are inconsistent")
            if event.phase == "started":
                if (
                    pending is not None
                    or event.confirmation.confirmation_id in seen_confirmations
                ):
                    raise ValueError("Private-data deletion starts are inconsistent")
                pending = event
                seen_confirmations.add(event.confirmation.confirmation_id)
            elif event.phase == "renamed":
                if (
                    pending is None
                    or pending.phase != "started"
                    or pending.plan != event.plan
                    or pending.confirmation != event.confirmation
                    or pending.target != event.target
                ):
                    raise ValueError("Private-data deletion rename has no exact start")
                pending = event
            elif (
                pending is None
                or event.plan != pending.plan
                or event.confirmation != pending.confirmation
                or event.target != pending.target
                or (
                    (event.target.root_identity is None) != (pending.phase == "started")
                )
            ):
                raise ValueError("Private-data deletion completion has no exact start")
            else:
                pending = None
        return events

    def _require_safe_journal(self) -> bool:
        return private_journal_exists(
            self._path,
            message=f"{self._label} journal is unsafe",
            posix_only=True,
        )

    def _require_private_parent(self) -> None:
        require_private_journal_parent(
            self._path,
            message=f"{self._label} Product state is not private",
            posix_only=True,
        )


def _open_start(
    events: tuple[_EventT, ...],
) -> _EventT | None:
    if events and events[-1].phase in {"started", "renamed"}:
        return events[-1]
    return None
