"""Durable Product authority for installed Continuity Plugin deletions."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from concurrent.futures import Future
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, cast

from loushang.harness.continuity.mutation import (
    AcceptedContinuityDeletion,
    ContinuityDeletionAuthorization,
    ContinuityDeletionPlanV1,
    ContinuityDeletionReceiptV1,
)
from loushang.harness.continuity.types import ContinuityProviderSourceDescriptor
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JournalLockUnavailable,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.runtime.registration import _await_cancellation_atomic

PluginContinuityDeletionEventKind = Literal["accepted", "completed", "cancelled"]
PluginContinuityDeletionState = Literal["accepted", "completed", "cancelled"]

_SOURCE_FIELDS = {
    "contributionId",
    "implementation",
    "implementationVersion",
    "instanceId",
    "instanceRevision",
    "ownerBindingFingerprint",
    "pluginId",
    "providerId",
    "source",
    "sourceId",
    "sourceTrustClass",
    "sourceTrustPolicyRevision",
}


class PluginContinuityDeletionJournalError(RuntimeError):
    """Fail-closed durable mutation-journal failure."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PluginContinuityDeletionEventV1:
    """One append-only authorization transition with exact recovery inputs."""

    journal_revision: int
    event_kind: PluginContinuityDeletionEventKind
    authorization_id: str
    attempt: int
    plan: ContinuityDeletionPlanV1
    source: ContinuityProviderSourceDescriptor
    receipt: ContinuityDeletionReceiptV1 | None = None
    event_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or type(self.attempt) is not int
            or self.attempt < 1
        ):
            raise ValueError("Continuity deletion journal counters must be positive")
        if type(self.event_version) is not int or self.event_version != 1:
            raise ValueError("Unsupported Continuity deletion event version")
        if self.event_kind not in {"accepted", "completed", "cancelled"}:
            raise ValueError("Unsupported Continuity deletion event kind")
        if type(self.plan) is not ContinuityDeletionPlanV1:
            raise TypeError("Continuity deletion event requires an exact plan")
        _validate_plugin_source(self.source)
        if self.plan.target.provider_id != self.source.provider_id:
            raise ValueError("Continuity deletion event source does not own target")
        expected_id = _authorization_id(self.plan, self.source, self.attempt)
        if self.authorization_id != expected_id:
            raise ValueError("Continuity deletion authorization id does not match")
        if self.event_kind == "completed":
            if (
                type(self.receipt) is not ContinuityDeletionReceiptV1
                or self.receipt.target != self.plan.target
                or self.receipt.plan_fingerprint != self.plan.fingerprint
            ):
                raise ValueError("Continuity deletion completion receipt is invalid")
        elif self.receipt is not None:
            raise ValueError("Non-completion deletion event cannot carry a receipt")

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt": self.attempt,
            "authorizationId": self.authorization_id,
            "eventKind": self.event_kind,
            "eventVersion": self.event_version,
            "journalRevision": self.journal_revision,
            "plan": self.plan.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "source": self.source.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginContinuityDeletionEventV1:
        try:
            if type(value) is not dict or set(value) != {
                "attempt",
                "authorizationId",
                "eventKind",
                "eventVersion",
                "journalRevision",
                "plan",
                "receipt",
                "source",
            }:
                raise ValueError("Continuity deletion event fields are invalid")
            event_kind = value["eventKind"]
            if event_kind not in {"accepted", "completed", "cancelled"}:
                raise ValueError("Continuity deletion event kind is invalid")
            typed_kind = cast(PluginContinuityDeletionEventKind, event_kind)
            raw_receipt = value["receipt"]
            return cls(
                journal_revision=cast(int, value["journalRevision"]),
                event_kind=typed_kind,
                authorization_id=cast(str, value["authorizationId"]),
                attempt=cast(int, value["attempt"]),
                plan=ContinuityDeletionPlanV1.from_dict(value["plan"]),
                source=_source_from_dict(value["source"]),
                receipt=(
                    None
                    if raw_receipt is None
                    else ContinuityDeletionReceiptV1.from_dict(raw_receipt)
                ),
                event_version=cast(int, value["eventVersion"]),
            )
        except JournalCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Continuity deletion event record is invalid",
                code="invalid_plugin_continuity_deletion_event",
            ) from exc


PLUGIN_CONTINUITY_DELETION_EVENT_CODEC = FunctionalJournalRecordCodec[
    PluginContinuityDeletionEventV1
](
    encoder=PluginContinuityDeletionEventV1.to_dict,
    decoder=PluginContinuityDeletionEventV1.from_dict,
)


@dataclass(frozen=True, slots=True)
class PluginContinuityDeletionSnapshotV1:
    authorization_id: str
    attempt: int
    plan: ContinuityDeletionPlanV1
    source: ContinuityProviderSourceDescriptor
    state: PluginContinuityDeletionState
    receipt: ContinuityDeletionReceiptV1 | None
    accepted_revision: int
    terminal_revision: int | None = None


class PluginContinuityDeletionJournal:
    """Append-only exact-plan authorization and recovery journal."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @classmethod
    def for_instance_runtime(
        cls,
        runtime_path: str | Path,
    ) -> PluginContinuityDeletionJournal:
        return cls(plugin_continuity_deletion_journal_path(runtime_path))

    @property
    def path(self) -> Path:
        return self._path

    def accept(
        self,
        plan: ContinuityDeletionPlanV1,
        source: ContinuityProviderSourceDescriptor,
    ) -> PluginContinuityDeletionSnapshotV1:
        _validate_plan_source(plan, source)
        with self._exclusive():
            events = self._load_unlocked()
            states = _project_events(events)
            key = _operation_key(plan, source)
            prior = states.get(key)
            if prior is not None and prior.state in {"accepted", "completed"}:
                return prior
            attempt = 1 if prior is None else prior.attempt + 1
            event = PluginContinuityDeletionEventV1(
                journal_revision=len(events) + 1,
                event_kind="accepted",
                authorization_id=_authorization_id(plan, source, attempt),
                attempt=attempt,
                plan=plan,
                source=source,
            )
            self._append_unlocked(event)
            return _snapshot_from_acceptance(event)

    def complete(
        self,
        authorization_id: str,
        receipt: ContinuityDeletionReceiptV1,
    ) -> PluginContinuityDeletionSnapshotV1:
        with self._exclusive():
            events = self._load_unlocked()
            current = _state_for_authorization(events, authorization_id, path=self._path)
            if current.state == "completed":
                if current.receipt != receipt:
                    raise self._conflict("Deletion completion receipt changed")
                return current
            if current.state != "accepted":
                raise self._conflict("Cancelled deletion cannot be completed")
            event = PluginContinuityDeletionEventV1(
                journal_revision=len(events) + 1,
                event_kind="completed",
                authorization_id=current.authorization_id,
                attempt=current.attempt,
                plan=current.plan,
                source=current.source,
                receipt=receipt,
            )
            self._append_unlocked(event)
            return replace(
                current,
                state="completed",
                receipt=receipt,
                terminal_revision=event.journal_revision,
            )

    def cancel(self, authorization_id: str) -> PluginContinuityDeletionSnapshotV1:
        with self._exclusive():
            events = self._load_unlocked()
            current = _state_for_authorization(events, authorization_id, path=self._path)
            if current.state == "cancelled":
                return current
            if current.state != "accepted":
                raise self._conflict("Completed deletion cannot be cancelled")
            event = PluginContinuityDeletionEventV1(
                journal_revision=len(events) + 1,
                event_kind="cancelled",
                authorization_id=current.authorization_id,
                attempt=current.attempt,
                plan=current.plan,
                source=current.source,
            )
            self._append_unlocked(event)
            return replace(
                current,
                state="cancelled",
                terminal_revision=event.journal_revision,
            )

    def authorization(
        self,
        authorization_id: str,
    ) -> PluginContinuityDeletionSnapshotV1:
        with self._exclusive():
            return _state_for_authorization(
                self._load_unlocked(),
                authorization_id,
                path=self._path,
            )

    def pending(self) -> tuple[PluginContinuityDeletionSnapshotV1, ...]:
        with self._exclusive():
            states = _project_events(self._load_unlocked())
            return tuple(
                sorted(
                    (item for item in states.values() if item.state == "accepted"),
                    key=lambda item: item.accepted_revision,
                )
            )

    def records(self) -> tuple[PluginContinuityDeletionEventV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _append_unlocked(self, event: PluginContinuityDeletionEventV1) -> None:
        append_jsonl_record(
            self._path,
            event,
            record_codec=PLUGIN_CONTINUITY_DELETION_EVENT_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_unlocked(self) -> tuple[PluginContinuityDeletionEventV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PluginContinuityDeletionEventV1] = load_jsonl(
                self._path,
                record_codec=PLUGIN_CONTINUITY_DELETION_EVENT_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = snapshot.records
            if any(
                item.journal_revision != index
                for index, item in enumerate(records, start=1)
            ):
                raise ValueError("Continuity deletion revisions are not contiguous")
            _project_events(records)
            return records
        except (JournalCodecError, JournalFileError, TypeError, ValueError) as exc:
            raise PluginContinuityDeletionJournalError(
                "Continuity deletion journal is corrupt.",
                code="plugin_continuity_deletion_journal_corrupt",
                path=self._path,
            ) from exc

    def _conflict(self, message: str) -> PluginContinuityDeletionJournalError:
        return PluginContinuityDeletionJournalError(
            message,
            code="plugin_continuity_deletion_journal_conflict",
            path=self._path,
        )


_ProcessOperationFlight = Future[
    tuple[PluginContinuityDeletionSnapshotV1 | None, BaseException | None]
]
_PROCESS_OPERATION_FLIGHTS: dict[
    tuple[str, str, str],
    _ProcessOperationFlight,
] = {}
_PROCESS_OPERATION_FLIGHT_GUARD = threading.Lock()


@dataclass(frozen=True, slots=True)
class PluginContinuityDeletionAuthority:
    """Concrete durable Product authority used by installed Plugin generations."""

    journal: PluginContinuityDeletionJournal = field(repr=False, compare=False)
    _held_executions: dict[str, AbstractContextManager[None]] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )
    _execution_guard: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
        compare=False,
    )
    def __post_init__(self) -> None:
        if not isinstance(self.journal, PluginContinuityDeletionJournal):
            raise TypeError("Continuity deletion authority requires its journal")

    async def authorize_delete(
        self,
        plan: ContinuityDeletionPlanV1,
        source: ContinuityProviderSourceDescriptor,
    ) -> ContinuityDeletionAuthorization:
        _validate_plan_source(plan, source)
        operation_key = _process_operation_key(self.journal.path, plan, source)
        while True:
            flight, leader = self._join_operation_flight(operation_key)
            if not leader:
                snapshot, error = await asyncio.shield(
                    asyncio.wrap_future(flight)
                )
                if error is not None:
                    raise error
                if snapshot is None or snapshot.state == "cancelled":
                    continue
                break
            try:
                snapshot = await self._acquire_execution_as_leader(plan, source)
            except asyncio.CancelledError:
                self._finish_operation_flight(
                    operation_key,
                    flight,
                    snapshot=None,
                )
                raise
            except BaseException as error:
                self._finish_operation_flight(
                    operation_key,
                    flight,
                    snapshot=None,
                    error=error,
                )
                raise
            if snapshot.state == "completed":
                self._finish_operation_flight(
                    operation_key,
                    flight,
                    snapshot=snapshot,
                )
            break
        return ContinuityDeletionAuthorization._issue(
            self,
            authorization_id=snapshot.authorization_id,
            plan=snapshot.plan,
            source=snapshot.source,
            settled_receipt=(
                snapshot.receipt if snapshot.state == "completed" else None
            ),
        )

    async def _acquire_execution_as_leader(
        self,
        plan: ContinuityDeletionPlanV1,
        source: ContinuityProviderSourceDescriptor,
    ) -> PluginContinuityDeletionSnapshotV1:
        while True:
            task = asyncio.create_task(
                asyncio.to_thread(self._try_acquire_execution, plan, source)
            )
            try:
                snapshot = await _await_cancellation_atomic(task)
            except asyncio.CancelledError as cancellation:
                snapshot = task.result()
                if snapshot is not None:
                    cleanup = asyncio.create_task(
                        asyncio.to_thread(
                            self._cancel_acquired_execution,
                            snapshot,
                        )
                    )
                    with suppress(asyncio.CancelledError):
                        await _await_cancellation_atomic(cleanup)
                raise cancellation
            if snapshot is not None:
                return snapshot
            # A non-blocking OS-lock miss never occupies an executor worker.
            # Yield with a bounded delay so settlement always has executor
            # capacity even under a duplicate-request storm.
            await asyncio.sleep(0.01)

    async def complete_delete(
        self,
        authorization: ContinuityDeletionAuthorization,
        receipt: ContinuityDeletionReceiptV1,
    ) -> None:
        await asyncio.to_thread(self._complete_execution, authorization, receipt)

    async def cancel_delete(
        self,
        authorization: ContinuityDeletionAuthorization,
    ) -> None:
        await asyncio.to_thread(self._cancel_execution, authorization)

    async def pending_deletions(self) -> tuple[AcceptedContinuityDeletion, ...]:
        pending = await asyncio.to_thread(self.journal.pending)
        return tuple(
            AcceptedContinuityDeletion(plan=item.plan, source=item.source)
            for item in pending
        )

    def _try_acquire_execution(
        self,
        plan: ContinuityDeletionPlanV1,
        source: ContinuityProviderSourceDescriptor,
    ) -> PluginContinuityDeletionSnapshotV1 | None:
        _validate_plan_source(plan, source)
        lock_target = _execution_lock_target(self.journal.path, plan, source)
        execution = journal_file_lock(lock_target, "exclusive", blocking=False)
        try:
            execution.__enter__()
        except JournalLockUnavailable:
            return None
        retained = False
        try:
            snapshot = self.journal.accept(plan, source)
            if snapshot.state == "completed":
                return snapshot
            with self._execution_guard:
                if snapshot.authorization_id in self._held_executions:
                    raise RuntimeError(
                        "Continuity deletion execution ownership repeated"
                    )
                self._held_executions[snapshot.authorization_id] = execution
                retained = True
            return snapshot
        finally:
            if not retained:
                execution.__exit__(None, None, None)

    def _complete_execution(
        self,
        authorization: ContinuityDeletionAuthorization,
        receipt: ContinuityDeletionReceiptV1,
    ) -> None:
        snapshot = self.journal.authorization(authorization.authorization_id)
        _validate_evidence(authorization, authority=self, snapshot=snapshot)
        terminal = self.journal.complete(authorization.authorization_id, receipt)
        self._release_execution(authorization.authorization_id)
        self._finish_operation_flight_for_snapshot(
            terminal,
            snapshot=terminal,
        )

    def _cancel_execution(
        self,
        authorization: ContinuityDeletionAuthorization,
    ) -> None:
        snapshot = self.journal.authorization(authorization.authorization_id)
        _validate_evidence(authorization, authority=self, snapshot=snapshot)
        terminal = self.journal.cancel(authorization.authorization_id)
        self._release_execution(authorization.authorization_id)
        self._finish_operation_flight_for_snapshot(
            terminal,
            snapshot=terminal,
        )

    def _cancel_acquired_execution(
        self,
        snapshot: PluginContinuityDeletionSnapshotV1,
    ) -> None:
        terminal: PluginContinuityDeletionSnapshotV1 | None = None
        try:
            if snapshot.state == "accepted":
                terminal = self.journal.cancel(snapshot.authorization_id)
            else:
                terminal = self.journal.authorization(snapshot.authorization_id)
        finally:
            try:
                self._release_execution(snapshot.authorization_id)
            finally:
                self._finish_operation_flight_for_snapshot(
                    snapshot,
                    snapshot=terminal,
                )

    def _release_execution(self, authorization_id: str) -> None:
        with self._execution_guard:
            execution = self._held_executions.get(authorization_id)
            if execution is not None:
                execution.__exit__(None, None, None)
                del self._held_executions[authorization_id]

    def _join_operation_flight(
        self,
        operation_key: tuple[str, str, str],
    ) -> tuple[_ProcessOperationFlight, bool]:
        with _PROCESS_OPERATION_FLIGHT_GUARD:
            flight = _PROCESS_OPERATION_FLIGHTS.get(operation_key)
            if flight is not None:
                return flight, False
            flight = Future()
            _PROCESS_OPERATION_FLIGHTS[operation_key] = flight
            return flight, True

    def _finish_operation_flight_for_snapshot(
        self,
        operation: PluginContinuityDeletionSnapshotV1,
        *,
        snapshot: PluginContinuityDeletionSnapshotV1 | None,
    ) -> None:
        operation_key = _process_operation_key(
            self.journal.path,
            operation.plan,
            operation.source,
        )
        with _PROCESS_OPERATION_FLIGHT_GUARD:
            flight = _PROCESS_OPERATION_FLIGHTS.get(operation_key)
        if flight is not None:
            self._finish_operation_flight(
                operation_key,
                flight,
                snapshot=snapshot,
            )

    def _finish_operation_flight(
        self,
        operation_key: tuple[str, str, str],
        flight: _ProcessOperationFlight,
        *,
        snapshot: PluginContinuityDeletionSnapshotV1 | None,
        error: BaseException | None = None,
    ) -> None:
        with _PROCESS_OPERATION_FLIGHT_GUARD:
            if _PROCESS_OPERATION_FLIGHTS.get(operation_key) is not flight:
                return
            del _PROCESS_OPERATION_FLIGHTS[operation_key]
            flight.set_result((snapshot, error))


def _project_events(
    events: tuple[PluginContinuityDeletionEventV1, ...],
) -> dict[tuple[str, str], PluginContinuityDeletionSnapshotV1]:
    result: dict[tuple[str, str], PluginContinuityDeletionSnapshotV1] = {}
    authorization_ids: set[str] = set()
    for event in events:
        key = _operation_key(event.plan, event.source)
        current = result.get(key)
        if event.event_kind == "accepted":
            expected_attempt = 1 if current is None else current.attempt + 1
            if (
                (current is not None and current.state != "cancelled")
                or event.attempt != expected_attempt
                or event.authorization_id in authorization_ids
            ):
                raise ValueError("Continuity deletion acceptance transition is invalid")
            authorization_ids.add(event.authorization_id)
            result[key] = _snapshot_from_acceptance(event)
            continue
        if (
            current is None
            or current.state != "accepted"
            or current.authorization_id != event.authorization_id
            or current.attempt != event.attempt
            or current.plan != event.plan
            or current.source != event.source
        ):
            raise ValueError("Continuity deletion terminal transition is invalid")
        result[key] = replace(
            current,
            state=event.event_kind,
            receipt=event.receipt,
            terminal_revision=event.journal_revision,
        )
    return result


def _snapshot_from_acceptance(
    event: PluginContinuityDeletionEventV1,
) -> PluginContinuityDeletionSnapshotV1:
    return PluginContinuityDeletionSnapshotV1(
        authorization_id=event.authorization_id,
        attempt=event.attempt,
        plan=event.plan,
        source=event.source,
        state="accepted",
        receipt=None,
        accepted_revision=event.journal_revision,
    )


def _state_for_authorization(
    events: tuple[PluginContinuityDeletionEventV1, ...],
    authorization_id: str,
    *,
    path: Path,
) -> PluginContinuityDeletionSnapshotV1:
    _require_sha256(authorization_id, name="authorization id")
    states = _project_events(events)
    matches = tuple(
        item for item in states.values() if item.authorization_id == authorization_id
    )
    if len(matches) != 1:
        raise PluginContinuityDeletionJournalError(
            "Continuity deletion authorization is unknown.",
            code="plugin_continuity_deletion_authorization_unknown",
            path=path,
        )
    return matches[0]


def _validate_evidence(
    authorization: ContinuityDeletionAuthorization,
    *,
    authority: PluginContinuityDeletionAuthority,
    snapshot: PluginContinuityDeletionSnapshotV1,
) -> None:
    if (
        type(authorization) is not ContinuityDeletionAuthorization
        or authorization._authority is not authority
        or authorization.authorization_id != snapshot.authorization_id
        or authorization.plan_fingerprint != snapshot.plan.fingerprint
        or authorization.source_fingerprint != _source_fingerprint(snapshot.source)
    ):
        raise PluginContinuityDeletionJournalError(
            "Continuity deletion authorization evidence is invalid.",
            code="plugin_continuity_deletion_authorization_mismatch",
            path=authority.journal.path,
        )


def _validate_plan_source(
    plan: ContinuityDeletionPlanV1,
    source: ContinuityProviderSourceDescriptor,
) -> None:
    if type(plan) is not ContinuityDeletionPlanV1:
        raise TypeError("Installed Continuity deletion requires an exact plan")
    _validate_plugin_source(source)
    if plan.target.provider_id != source.provider_id:
        raise ValueError("Installed Continuity deletion source does not own target")


def _validate_plugin_source(source: ContinuityProviderSourceDescriptor) -> None:
    if (
        type(source) is not ContinuityProviderSourceDescriptor
        or source.source != "plugin"
    ):
        raise TypeError("Installed Continuity deletion requires Plugin provenance")
    StrictPluginJsonCodec.encode(source.to_dict())


def _operation_key(
    plan: ContinuityDeletionPlanV1,
    source: ContinuityProviderSourceDescriptor,
) -> tuple[str, str]:
    return plan.fingerprint, _source_fingerprint(source)


def _process_operation_key(
    journal_path: Path,
    plan: ContinuityDeletionPlanV1,
    source: ContinuityProviderSourceDescriptor,
) -> tuple[str, str, str]:
    plan_fingerprint, source_fingerprint = _operation_key(plan, source)
    return str(journal_path.resolve()), plan_fingerprint, source_fingerprint


def _execution_lock_target(
    journal_path: Path,
    plan: ContinuityDeletionPlanV1,
    source: ContinuityProviderSourceDescriptor,
) -> Path:
    payload = StrictPluginJsonCodec.encode(
        {
            "planFingerprint": plan.fingerprint,
            "sourceFingerprint": _source_fingerprint(source),
        }
    )
    identity = hashlib.sha256(
        b"loushang.plugin-continuity-deletion-execution/v1\0" + payload
    ).hexdigest()
    directory = journal_path.with_name(
        f".{journal_path.name}.continuity-deletion-locks"
    )
    return directory / identity


def _authorization_id(
    plan: ContinuityDeletionPlanV1,
    source: ContinuityProviderSourceDescriptor,
    attempt: int,
) -> str:
    payload = StrictPluginJsonCodec.encode(
        {
            "attempt": attempt,
            "planFingerprint": plan.fingerprint,
            "sourceFingerprint": _source_fingerprint(source),
        }
    )
    return hashlib.sha256(
        b"loushang.plugin-continuity-deletion-authorization/v1\0" + payload
    ).hexdigest()


def _source_fingerprint(source: ContinuityProviderSourceDescriptor) -> str:
    return hashlib.sha256(
        b"loushang.continuity-provider-source/v1\0"
        + StrictPluginJsonCodec.encode(source.to_dict())
    ).hexdigest()


def _source_from_dict(value: object) -> ContinuityProviderSourceDescriptor:
    if type(value) is not dict or set(value) != _SOURCE_FIELDS:
        raise ValueError("Continuity deletion source fields are invalid")
    source = ContinuityProviderSourceDescriptor(
        provider_id=cast(str, value["providerId"]),
        source=cast(Literal["plugin"], value["source"]),
        source_id=cast(str, value["sourceId"]),
        implementation=cast(str, value["implementation"]),
        implementation_version=cast(int, value["implementationVersion"]),
        plugin_id=cast(str, value["pluginId"]),
        contribution_id=cast(str, value["contributionId"]),
        instance_id=cast(str, value["instanceId"]),
        instance_revision=cast(int, value["instanceRevision"]),
        source_trust_class=cast(str, value["sourceTrustClass"]),
        source_trust_policy_revision=cast(
            str,
            value["sourceTrustPolicyRevision"],
        ),
        owner_binding_fingerprint=cast(str, value["ownerBindingFingerprint"]),
    )
    _validate_plugin_source(source)
    return source


def _require_sha256(value: object, *, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Continuity deletion {name} must be SHA-256 hex")


def plugin_continuity_deletion_journal_path(runtime_path: str | Path) -> Path:
    """Derive the canonical Product mutation journal beside Instance state."""

    canonical = Path(runtime_path).resolve()
    name = f"{canonical.name}.continuity-deletions.jsonl"
    return canonical.with_name(name)


__all__ = [
    "PLUGIN_CONTINUITY_DELETION_EVENT_CODEC",
    "PluginContinuityDeletionAuthority",
    "PluginContinuityDeletionEventV1",
    "PluginContinuityDeletionJournal",
    "PluginContinuityDeletionJournalError",
    "PluginContinuityDeletionSnapshotV1",
    "plugin_continuity_deletion_journal_path",
]
