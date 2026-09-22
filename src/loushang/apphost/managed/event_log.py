"""Finite lifecycle diagnostics on borrowed storage, never an audit or permit.

The process composition must establish instance lifetime before using this
consumer. It retains the original directory owner through all native settlement.
Lock order is log directory then short registry transaction, never the reverse.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from threading import TIMEOUT_MAX
from time import monotonic

from ._files import (
    ManagedDataFileSnapshot,
    ManagedStorageError,
    PrivateManagedDirectory,
    _check_deadline,
    _on_event_loop,
)
from .contracts import _HEX32, _HEX64, ManagedContractError, _match
from .paths import LIFECYCLE_LOG_NAMES, MANAGED_LOG_DIRECTORY_NAMES
from .storage_budget import ManagedStorageAllocationV1, ManagedStorageBudgetV1

_EVENTS = frozenset({"starting", "ready", "stopping", "stopped", "failed"})
_CODES = frozenset({"startup_failed", "application_failed", "cleanup_incomplete", "stop_requested"})
_CAPACITY = 10 * 1024**2
_FRAME_BYTES = 256
_MAX_SEQUENCE = 2**63 - 1
_NAMES = LIFECYCLE_LOG_NAMES
_LOCK = "lifecycle.lock"


@dataclass(frozen=True, slots=True)
class ManagedLifecycleEventV1:
    event: str
    instance_id: str
    code: str | None = None

    def __post_init__(self) -> None:
        if (type(self.event) is not str or self.event not in _EVENTS
                or (self.code is not None and (type(self.code) is not str or self.code not in _CODES))):
            raise ManagedContractError()
        _match(self.instance_id, _HEX32)


def _encode(event: ManagedLifecycleEventV1, sequence: int) -> bytes:
    if type(event) is not ManagedLifecycleEventV1:
        raise ManagedContractError()
    event.__post_init__()
    if type(sequence) is not int or not 1 <= sequence <= _MAX_SEQUENCE:
        raise ManagedStorageError("capacity")
    value = {"v": 1, "event": event.event, "instanceId": event.instance_id,
             "code": event.code, "sequence": sequence}
    result = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    if len(result) > _FRAME_BYTES:
        raise ManagedStorageError("capacity")
    return result


def _sequence(snapshot: ManagedDataFileSnapshot) -> int:
    if snapshot.size == 0:
        return 0
    tail = snapshot.tail
    if not tail.endswith(b"\n"):
        raise ManagedStorageError("invalid_record")
    boundary = tail.rfind(b"\n", 0, len(tail) - 1)
    if boundary == -1 and snapshot.size != len(tail):
        raise ManagedStorageError("invalid_record")
    frame = tail[boundary + 1:]
    return _decode_frame(frame).sequence


@dataclass(frozen=True, slots=True)
class ManagedLifecycleRecordV1:
    sequence: int
    event: ManagedLifecycleEventV1

    def __post_init__(self) -> None:
        _encode(self.event, self.sequence)


def _decode_frame(frame: bytes) -> ManagedLifecycleRecordV1:
    if not 0 < len(frame) <= _FRAME_BYTES:
        raise ManagedStorageError("invalid_record")
    try:
        row = json.loads(frame)
        if (type(row) is not dict or set(row) != {"v", "event", "instanceId", "code", "sequence"}
                or type(row["v"]) is not int or row["v"] != 1):
            raise ValueError()
        event = ManagedLifecycleEventV1(row["event"], row["instanceId"], row["code"])
        # Exact canonical bytes also reject duplicate keys, extra whitespace,
        # alternate encodings and bool/huge sequence values without text leaks.
        if _encode(event, row["sequence"]) != frame:
            raise ValueError()
        return ManagedLifecycleRecordV1(row["sequence"], event)
    except (ValueError, TypeError, KeyError, ManagedStorageError):
        raise ManagedStorageError("invalid_record") from None


class ManagedLifecycleLogV1:
    """Five fixed charged segments. Failure seals this consumer, never retries.

    segment_bytes may lower the physical ceiling for deterministic validation;
    durable reservations always charge the full production segment capacity.
    No resources or closing rights are transferred from the injected owners.
    Synchronous native-worker API: running event loops are rejected before IO.
    """

    def __init__(self, directory: PrivateManagedDirectory, budget: ManagedStorageBudgetV1,
                 service_id: str, *, segment_bytes: int = _CAPACITY) -> None:
        if (type(directory) is not PrivateManagedDirectory or type(budget) is not ManagedStorageBudgetV1
                or type(segment_bytes) is not int or not _FRAME_BYTES <= segment_bytes <= _CAPACITY):
            raise ManagedContractError()
        _match(service_id, _HEX64)
        self._directory, self._budget = directory, budget
        self._service_id, self._segment_bytes = service_id, segment_bytes
        self._failed = False

    def _allocation(self, slot: int) -> ManagedStorageAllocationV1:
        directory = self._directory
        directory._check()
        return ManagedStorageAllocationV1(self._service_id, "log", None, slot, _CAPACITY,
            sha256(os.fsencode(directory._root)).hexdigest(), directory._identity)

    def write(self, event: ManagedLifecycleEventV1, *, deadline: float | None = None) -> int | None:
        """Return the sequence, or None when initial lock contention drops this event.

        A dropped event is never replayed. Failures after admission still seal
        the writer, including uncertain append and lock-release effects.
        """
        _encode(event, _MAX_SEQUENCE)  # All event validation precedes IO.
        if _on_event_loop():
            raise ManagedStorageError("busy")
        # Reuse the native owner's serialization: a waiting call must observe
        # failure before admission, including errors during flock release.
        _check_deadline(deadline)
        timeout = -1 if deadline is None else min(TIMEOUT_MAX, max(0, deadline - monotonic()))
        if not self._directory._mutex.acquire(timeout=timeout):
            raise ManagedStorageError("busy")
        try:
            return self._write(event, deadline=deadline)
        finally:
            self._directory._mutex.release()

    def _write(self, event: ManagedLifecycleEventV1, *, deadline: float | None = None) -> int | None:
        _check_deadline(deadline)
        if self._failed:
            raise ManagedStorageError("closed")
        directory = self._directory
        admitted = False
        try:
            with directory.lock(_LOCK, create=True, deadline=deadline, wait_for_lock=deadline is not None):
                admitted = True
                snapshots = self._snapshots(deadline=deadline)
                sequences = [0 if snapshot is None else _sequence(snapshot) for snapshot in snapshots]
                nonzero = [value for value in sequences if value]
                if len(set(nonzero)) != len(nonzero):
                    raise ManagedStorageError("invalid_record")
                latest = max(sequences)
                content = _encode(event, latest + 1)
                slot = sequences.index(latest)
                snapshot = snapshots[slot]
                rotate = snapshot is not None and snapshot.size + len(content) > self._segment_bytes
                if rotate:
                    slot = (slot + 1) % len(_NAMES)
                    snapshot = snapshots[slot]
                if snapshot is None:
                    allocation = self._allocation(slot)
                    # Exclusive insert is the current attempt's receipt, not
                    # an idempotent lookup of an abandoned unbound reservation.
                    reservation = self._budget.reserve(allocation, exclusive=True,
                        deadline=deadline, wait_for_lock=deadline is not None)
                    _check_deadline(deadline)
                    snapshot = directory.append_data(_NAMES[slot], b"", expected=None,
                                                       capacity=self._segment_bytes)
                    self._budget.bind_file(reservation, snapshot.identity,
                        deadline=deadline, wait_for_lock=deadline is not None)
                _check_deadline(deadline)
                directory.append_data(_NAMES[slot], content, expected=snapshot,
                                      capacity=self._segment_bytes, truncate=rotate)
                return latest + 1
        except BaseException as error:
            if (not admitted and isinstance(error, ManagedStorageError)
                    and error.code == "busy" and not directory.cleanup_pending):
                return None
            self._failed = True
            raise

    def _snapshots(self, *, deadline: float | None = None) -> list[ManagedDataFileSnapshot | None]:
        directory = self._directory
        if set(directory.names(limit=len(MANAGED_LOG_DIRECTORY_NAMES))) - MANAGED_LOG_DIRECTORY_NAMES:
            raise ManagedStorageError("invalid_record")
        result = []
        for slot, name in enumerate(_NAMES):
            _check_deadline(deadline)
            reservation = self._budget.lookup(self._allocation(slot), deadline=deadline,
                                               wait_for_lock=deadline is not None)
            snapshot = directory.data_snapshot(name, capacity=self._segment_bytes)
            if reservation is None:
                if snapshot is not None:
                    raise ManagedStorageError("conflict")
            elif (reservation.file_identity is None or snapshot is None
                  or snapshot.identity != reservation.file_identity):
                raise ManagedStorageError("conflict")
            result.append(snapshot)
        _check_deadline(deadline)
        return result

    def read_tail(self, *, limit: int = 50, deadline: float | None = None) -> tuple[ManagedLifecycleRecordV1, ...]:
        """Read up to limit visible records, not a complete history or audit.

        At most five 16 KiB tails are read. A cut first frame is omitted; every
        remaining visible frame is validated before returning any records.
        This neither creates a missing lock nor binds, repairs or rotates files.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ManagedContractError()
        _check_deadline(deadline)
        if _on_event_loop():
            raise ManagedStorageError("busy")
        with self._directory.lock(_LOCK, deadline=deadline, wait_for_lock=deadline is not None):
            records = []
            for snapshot in self._snapshots(deadline=deadline):
                if snapshot is None or snapshot.size == 0:
                    continue
                _sequence(snapshot)  # Require the final frame to be complete.
                frames = snapshot.tail.split(b"\n")[:-1]
                if snapshot.size > len(snapshot.tail):
                    frames = frames[1:]
                previous = 0
                for frame in frames:
                    record = _decode_frame(frame + b"\n")
                    if record.sequence <= previous:
                        raise ManagedStorageError("invalid_record")
                    previous = record.sequence
                    records.append(record)
            sequences = [record.sequence for record in records]
            if len(sequences) != len(set(sequences)):
                raise ManagedStorageError("invalid_record")
            _check_deadline(deadline)
            result = tuple(sorted(records, key=lambda record: record.sequence)[-limit:])
        _check_deadline(deadline)
        return result


__all__ = ["ManagedLifecycleEventV1", "ManagedLifecycleRecordV1", "ManagedLifecycleLogV1"]
