"""Durable PLC9D Package reservation and irreversible deletion-start fence.

This journal has no Store capability. It fences only owner graphs that
explicitly bind the same journal to desired, Instance, and Package writers.
"""

from __future__ import annotations

import json
import threading
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeAlias, cast

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
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageGcCandidateV1,
    PluginPackageLifecycleLedger,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1

PLUGIN_PACKAGE_GC_RESERVATION_EVENT_VERSION = 1
GcReservationEventKind = Literal["reserved", "cancelled"]


class PluginPackageGcReservationError(RuntimeError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


class _ReservationCodecError(JournalCodecError):
    pass


@dataclass
class _GateLockState:
    thread_lock: threading.RLock
    depth: int = 0


_GATE_STATES_LOCK = threading.Lock()
_GATE_STATES: weakref.WeakValueDictionary[Path, _GateLockState] = (
    weakref.WeakValueDictionary()
)


def _gate_lock_state(path: Path) -> _GateLockState:
    with _GATE_STATES_LOCK:
        state = _GATE_STATES.get(path)
        if state is None:
            state = _GateLockState(thread_lock=threading.RLock())
            _GATE_STATES[path] = state
        return state


@dataclass(frozen=True, slots=True)
class PluginPackageGcReservationEventV1:
    journal_revision: int
    kind: GcReservationEventKind
    reservation_id: str
    candidate: PluginPackageGcCandidateV1 | None
    operation_id: str
    idempotency_key: str
    reason_code: str | None = None
    event_version: int = PLUGIN_PACKAGE_GC_RESERVATION_EVENT_VERSION

    def __post_init__(self) -> None:
        if type(self.journal_revision) is not int or self.journal_revision < 1:
            raise ValueError("GC reservation journal revision must be positive")
        if self.kind not in {"reserved", "cancelled"}:
            raise ValueError("Unsupported GC reservation event kind")
        if not _is_sha256(self.reservation_id):
            raise ValueError("GC reservation identity is invalid")
        if not self.operation_id or not self.idempotency_key:
            raise ValueError("GC reservation operation identity is required")
        if self.kind == "reserved":
            if self.candidate is None or self.reason_code is not None:
                raise ValueError("GC reservation requires only a candidate")
            if self.reservation_id != _reservation_id(
                self.candidate, self.operation_id, self.idempotency_key
            ):
                raise ValueError("GC reservation identity does not match")
        elif self.candidate is not None or not self.reason_code:
            raise ValueError("GC cancellation requires only a reason")
        if self.event_version != PLUGIN_PACKAGE_GC_RESERVATION_EVENT_VERSION:
            raise ValueError("Unsupported GC reservation event version")

    def to_dict(self) -> dict[str, object]:
        candidate = self.candidate
        return {
            "candidate": (
                None
                if candidate is None
                else {
                    "candidateId": candidate.candidate_id,
                    "candidateVersion": candidate.candidate_version,
                    "desiredInventoryRevision": candidate.desired_inventory_revision,
                    "instanceRuntimeRevision": candidate.instance_runtime_revision,
                    "packageJournalRevision": candidate.package_journal_revision,
                    "packageRevision": candidate.package_revision.to_dict(),
                    "recoveryBarrierId": candidate.recovery_barrier_id,
                }
            ),
            "eventVersion": self.event_version,
            "idempotencyKey": self.idempotency_key,
            "journalRevision": self.journal_revision,
            "kind": self.kind,
            "operationId": self.operation_id,
            "reasonCode": self.reason_code,
            "reservationId": self.reservation_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackageGcReservationEventV1:
        try:
            item = _exact_dict(
                value,
                {
                    "candidate",
                    "eventVersion",
                    "idempotencyKey",
                    "journalRevision",
                    "kind",
                    "operationId",
                    "reasonCode",
                    "reservationId",
                },
            )
            candidate_value = item["candidate"]
            candidate = (
                None if candidate_value is None else _decode_candidate(candidate_value)
            )
            return cls(
                journal_revision=_integer(item["journalRevision"]),
                kind=_kind(item["kind"]),
                reservation_id=_string(item["reservationId"]),
                candidate=candidate,
                operation_id=_string(item["operationId"]),
                idempotency_key=_string(item["idempotencyKey"]),
                reason_code=(
                    None if item["reasonCode"] is None else _string(item["reasonCode"])
                ),
                event_version=_integer(item["eventVersion"]),
            )
        except (JournalCodecError, TypeError, ValueError) as exc:
            raise _ReservationCodecError(
                "Invalid GC reservation record",
                code="invalid_plugin_package_gc_reservation_record",
            ) from exc


@dataclass(frozen=True, slots=True)
class PluginPackageGcDeletionStartV2:
    """Irreversible fence recorded before any physical Store mutation."""

    journal_revision: int
    reservation_id: str
    operation_id: str
    idempotency_key: str
    target_settlement_ids: tuple[str, ...]
    kind: Literal["deletion_started"] = "deletion_started"
    event_version: int = 2

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or not _is_sha256(self.reservation_id)
            or not self.operation_id
            or not self.idempotency_key
            or not self.target_settlement_ids
            or self.target_settlement_ids
            != tuple(sorted(set(self.target_settlement_ids)))
            or not all(_is_sha256(value) for value in self.target_settlement_ids)
            or self.kind != "deletion_started"
            or self.event_version != 2
        ):
            raise ValueError("GC deletion start record is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "eventVersion": self.event_version,
            "idempotencyKey": self.idempotency_key,
            "journalRevision": self.journal_revision,
            "kind": self.kind,
            "operationId": self.operation_id,
            "reservationId": self.reservation_id,
            "targetSettlementIds": list(self.target_settlement_ids),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackageGcDeletionStartV2:
        try:
            item = _exact_dict(
                value,
                {
                    "eventVersion",
                    "idempotencyKey",
                    "journalRevision",
                    "kind",
                    "operationId",
                    "reservationId",
                    "targetSettlementIds",
                },
            )
            targets = item["targetSettlementIds"]
            if type(targets) is not list:
                raise ValueError("GC target settlements are invalid")
            return cls(
                journal_revision=_integer(item["journalRevision"]),
                reservation_id=_string(item["reservationId"]),
                operation_id=_string(item["operationId"]),
                idempotency_key=_string(item["idempotencyKey"]),
                target_settlement_ids=tuple(_string(value) for value in targets),
                kind=cast(Literal["deletion_started"], item["kind"]),
                event_version=_integer(item["eventVersion"]),
            )
        except (JournalCodecError, TypeError, ValueError) as exc:
            raise _ReservationCodecError(
                "Invalid GC deletion start record",
                code="invalid_plugin_package_gc_reservation_record",
            ) from exc


GcJournalEvent: TypeAlias = (
    PluginPackageGcReservationEventV1 | PluginPackageGcDeletionStartV2
)


def _encode_event(event: GcJournalEvent) -> dict[str, object]:
    return event.to_dict()


def _decode_event(value: object) -> GcJournalEvent:
    if type(value) is not dict:
        raise _ReservationCodecError(
            "Invalid GC reservation record",
            code="invalid_plugin_package_gc_reservation_record",
        )
    if value.get("eventVersion") == 2:
        return PluginPackageGcDeletionStartV2.from_dict(value)
    return PluginPackageGcReservationEventV1.from_dict(value)


_EVENT_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_event,
    decoder=_decode_event,
)


@dataclass(frozen=True, slots=True)
class PluginPackageGcReservationSnapshotV1:
    journal_revision: int
    active: tuple[PluginPackageGcReservationEventV1, ...]


class PluginPackageGcReservationJournal:
    """One explicit gate shared by every writer in an opted-in owner graph."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._lock_state = _gate_lock_state(self._path)
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def guard(self) -> Iterator[frozenset[PluginPackageRevisionRefV1]]:
        state = self._lock_state
        with state.thread_lock:
            if state.depth:
                state.depth += 1
                try:
                    yield self._active_packages_unlocked()
                finally:
                    state.depth -= 1
                return
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                state.depth = 1
                try:
                    yield self._active_packages_unlocked()
                finally:
                    state.depth = 0

    def snapshot(self) -> PluginPackageGcReservationSnapshotV1:
        with self.guard():
            events, active, _ = self._replay_unlocked()
            return PluginPackageGcReservationSnapshotV1(
                journal_revision=len(events),
                active=tuple(
                    sorted(active.values(), key=lambda item: item.reservation_id)
                ),
            )

    def reserve(
        self,
        candidate: PluginPackageGcCandidateV1,
        *,
        lifecycle: PluginPackageLifecycleLedger,
        operation_id: str,
        idempotency_key: str,
    ) -> PluginPackageGcReservationEventV1:
        if not isinstance(candidate, PluginPackageGcCandidateV1):
            raise TypeError("GC candidate is required")
        if not isinstance(lifecycle, PluginPackageLifecycleLedger):
            raise TypeError("Package lifecycle owner is required")
        if not lifecycle.gc_reservation_graph_bound_to(self):
            raise self._error(
                "GC owner graph is not fully fenced", "plugin_package_gc_graph_unbound"
            )
        if self._path in {
            path.resolve() for path in lifecycle.gc_reservation_peer_journal_paths
        }:
            raise self._error(
                "GC journal overlaps an owner", "plugin_package_gc_graph_unbound"
            )
        _require_identity(operation_id, idempotency_key)
        with self.guard():
            events, active, _ = self._replay_unlocked()
            repeated = _repeated(events, operation_id, idempotency_key, path=self._path)
            if repeated is not None:
                if not isinstance(repeated, PluginPackageGcReservationEventV1) or repeated.kind != "reserved" or repeated.candidate != candidate:
                    raise self._error(
                        "GC operation identity was reused", "plugin_package_gc_conflict"
                    )
                if repeated.reservation_id not in active:
                    raise self._error(
                        "GC reservation was cancelled", "plugin_package_gc_stale"
                    )
                lifecycle.recheck_gc_candidate(candidate)
                return repeated
            if any(
                item.candidate is not None
                and item.candidate.package_revision == candidate.package_revision
                for item in active.values()
            ):
                raise self._error(
                    "Package revision already reserved", "plugin_package_gc_conflict"
                )
            lifecycle.recheck_gc_candidate(candidate)
            event = PluginPackageGcReservationEventV1(
                journal_revision=len(events) + 1,
                kind="reserved",
                reservation_id=_reservation_id(
                    candidate, operation_id, idempotency_key
                ),
                candidate=candidate,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
            )
            self._append_unlocked(event)
            return event

    def cancel(
        self,
        reservation_id: str,
        *,
        operation_id: str,
        idempotency_key: str,
        reason_code: str,
    ) -> PluginPackageGcReservationEventV1:
        _require_identity(operation_id, idempotency_key)
        if not _is_sha256(reservation_id) or not reason_code:
            raise ValueError(
                "Exact GC reservation and cancellation reason are required"
            )
        with self.guard():
            events, active, started = self._replay_unlocked()
            repeated = _repeated(events, operation_id, idempotency_key, path=self._path)
            if repeated is not None:
                if (
                    not isinstance(repeated, PluginPackageGcReservationEventV1)
                    or repeated.kind != "cancelled"
                    or repeated.reservation_id != reservation_id
                    or repeated.reason_code != reason_code
                ):
                    raise self._error(
                        "GC operation identity was reused", "plugin_package_gc_conflict"
                    )
                return repeated
            if reservation_id not in active:
                raise self._error(
                    "GC reservation is not active", "plugin_package_gc_stale"
                )
            if reservation_id in started:
                raise self._error(
                    "GC deletion has started", "plugin_package_gc_deletion_started"
                )
            event = PluginPackageGcReservationEventV1(
                journal_revision=len(events) + 1,
                kind="cancelled",
                reservation_id=reservation_id,
                candidate=None,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                reason_code=reason_code,
            )
            self._append_unlocked(event)
            return event

    def begin_delete(
        self,
        reservation_id: str,
        *,
        lifecycle: PluginPackageLifecycleLedger,
        target_settlement_ids: tuple[str, ...],
        operation_id: str,
        idempotency_key: str,
    ) -> PluginPackageGcDeletionStartV2:
        """Persist the irreversible fence while the complete owner graph is locked."""

        _require_identity(operation_id, idempotency_key)
        if not _is_sha256(reservation_id):
            raise ValueError("Exact GC reservation is required")
        if not lifecycle.gc_reservation_graph_bound_to(self):
            raise self._error("GC owner graph is not fully fenced", "plugin_package_gc_graph_unbound")
        with self.guard():
            events, active, started = self._replay_unlocked()
            repeated = _repeated(events, operation_id, idempotency_key, path=self._path)
            if repeated is not None:
                if (
                    not isinstance(repeated, PluginPackageGcDeletionStartV2)
                    or repeated.reservation_id != reservation_id
                    or repeated.target_settlement_ids != target_settlement_ids
                ):
                    raise self._error("GC operation identity was reused", "plugin_package_gc_conflict")
                return repeated
            if reservation_id not in active:
                raise self._error("GC reservation is not active", "plugin_package_gc_stale")
            if reservation_id in started:
                raise self._error("GC deletion already started", "plugin_package_gc_conflict")
            if not lifecycle.gc_writer_epoch_sealed():
                raise self._error("GC writer epoch is not sealed", "plugin_package_gc_writer_epoch_unsealed")
            candidate = active[reservation_id].candidate
            if candidate is None:
                raise self._error("GC reservation is corrupt", "plugin_package_gc_journal_corrupt")
            lifecycle.recheck_gc_candidate(candidate)
            event = PluginPackageGcDeletionStartV2(
                journal_revision=len(events) + 1,
                reservation_id=reservation_id,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                target_settlement_ids=target_settlement_ids,
            )
            self._append_unlocked(event)
            return event

    def deletion_start(self, reservation_id: str) -> PluginPackageGcDeletionStartV2 | None:
        with self.guard():
            _, _, started = self._replay_unlocked()
            return started.get(reservation_id)

    def _active_packages_unlocked(self) -> frozenset[PluginPackageRevisionRefV1]:
        _, active, _ = self._replay_unlocked()
        return frozenset(
            item.candidate.package_revision
            for item in active.values()
            if item.candidate is not None
        )

    def _replay_unlocked(
        self,
    ) -> tuple[
        tuple[GcJournalEvent, ...],
        dict[str, PluginPackageGcReservationEventV1],
        dict[str, PluginPackageGcDeletionStartV2],
    ]:
        if not self._path.exists():
            return (), {}, {}
        try:
            loaded: JsonlSnapshot[None, GcJournalEvent] = load_jsonl(
                self._path,
                record_codec=_EVENT_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            events = loaded.records
        except JournalFileError as exc:
            raise self._error(
                "GC reservation journal is corrupt", "plugin_package_gc_journal_corrupt"
            ) from exc
        active: dict[str, PluginPackageGcReservationEventV1] = {}
        started: dict[str, PluginPackageGcDeletionStartV2] = {}
        active_packages: set[PluginPackageRevisionRefV1] = set()
        operations: set[str] = set()
        idempotency: set[str] = set()
        for revision, event in enumerate(events, start=1):
            if (
                event.journal_revision != revision
                or event.operation_id in operations
                or event.idempotency_key in idempotency
            ):
                raise self._error(
                    "GC reservation history is corrupt",
                    "plugin_package_gc_journal_corrupt",
                )
            if isinstance(event, PluginPackageGcDeletionStartV2):
                if event.reservation_id not in active or event.reservation_id in started:
                    raise self._error("GC deletion start lacks one reservation", "plugin_package_gc_journal_corrupt")
                started[event.reservation_id] = event
            elif event.kind == "reserved":
                candidate = event.candidate
                if (
                    candidate is None
                    or event.reservation_id in active
                    or candidate.package_revision in active_packages
                ):
                    raise self._error(
                        "GC reservation is duplicated",
                        "plugin_package_gc_journal_corrupt",
                    )
                active[event.reservation_id] = event
                active_packages.add(candidate.package_revision)
            elif event.reservation_id not in active or event.reservation_id in started:
                raise self._error(
                    "GC cancellation lacks a reservation",
                    "plugin_package_gc_journal_corrupt",
                )
            else:
                prior = active.pop(event.reservation_id)
                if prior.candidate is None:
                    raise self._error(
                        "GC reservation lacks its candidate",
                        "plugin_package_gc_journal_corrupt",
                    )
                active_packages.remove(prior.candidate.package_revision)
            operations.add(event.operation_id)
            idempotency.add(event.idempotency_key)
        return events, active, started

    def _append_unlocked(self, event: GcJournalEvent) -> None:
        try:
            append_jsonl_record(
                self._path,
                event,
                record_codec=_EVENT_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
        except JournalFileError as exc:
            raise self._error(
                "GC reservation append failed", "plugin_package_gc_journal_corrupt"
            ) from exc

    def _error(self, message: str, code: str) -> PluginPackageGcReservationError:
        return PluginPackageGcReservationError(message, code=code, path=self._path)


def _repeated(
    events: tuple[GcJournalEvent, ...],
    operation_id: str,
    idempotency_key: str,
    *,
    path: Path,
) -> GcJournalEvent | None:
    by_operation = next(
        (item for item in events if item.operation_id == operation_id), None
    )
    by_key = next(
        (item for item in events if item.idempotency_key == idempotency_key), None
    )
    if by_operation != by_key:
        raise PluginPackageGcReservationError(
            "GC operation and idempotency identities diverge",
            code="plugin_package_gc_conflict",
            path=path,
        )
    return by_operation


def _reservation_id(
    candidate: PluginPackageGcCandidateV1,
    operation_id: str,
    idempotency_key: str,
) -> str:
    payload = json.dumps(
        [candidate.candidate_id, operation_id, idempotency_key],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(b"plugin-package-gc-reservation-v1\0" + payload).hexdigest()


def _decode_candidate(value: object) -> PluginPackageGcCandidateV1:
    item = _exact_dict(
        value,
        {
            "candidateId",
            "candidateVersion",
            "desiredInventoryRevision",
            "instanceRuntimeRevision",
            "packageJournalRevision",
            "packageRevision",
            "recoveryBarrierId",
        },
    )
    return PluginPackageGcCandidateV1(
        candidate_id=_string(item["candidateId"]),
        candidate_version=_integer(item["candidateVersion"]),
        desired_inventory_revision=_integer(item["desiredInventoryRevision"]),
        instance_runtime_revision=_integer(item["instanceRuntimeRevision"]),
        package_journal_revision=_integer(item["packageJournalRevision"]),
        package_revision=PluginPackageRevisionRefV1.from_dict(item["packageRevision"]),
        recovery_barrier_id=_string(item["recoveryBarrierId"]),
    )


def _exact_dict(value: object, fields: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise ValueError("GC reservation record fields are invalid")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("GC reservation integer field is invalid")
    return value


def _string(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError("GC reservation string field is invalid")
    return value


def _kind(value: object) -> GcReservationEventKind:
    if value not in {"reserved", "cancelled"}:
        raise ValueError("GC reservation event kind is invalid")
    return cast(GcReservationEventKind, value)


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_identity(operation_id: str, idempotency_key: str) -> None:
    if type(operation_id) is not str or not operation_id:
        raise ValueError("GC operation id is required")
    if type(idempotency_key) is not str or not idempotency_key:
        raise ValueError("GC idempotency key is required")


__all__ = [
    "PLUGIN_PACKAGE_GC_RESERVATION_EVENT_VERSION",
    "PluginPackageGcReservationError",
    "PluginPackageGcReservationEventV1",
    "PluginPackageGcDeletionStartV2",
    "PluginPackageGcReservationJournal",
    "PluginPackageGcReservationSnapshotV1",
]
