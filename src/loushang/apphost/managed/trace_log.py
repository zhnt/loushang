"""Two charged trace segments on a borrowed native directory and registry.

Only the original diagnostics worker may call write. This consumer neither
owns the directory nor retries uncertain writes, releases charges, or schedules
work. Its caller retains it and the dependencies through native settlement.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from threading import TIMEOUT_MAX
from time import monotonic
from typing import Any

from ._files import (
    ManagedDataFileSnapshot,
    ManagedStorageError,
    PrivateManagedDirectory,
    _check_deadline,
    _on_event_loop,
)
from .contracts import _HEX32, _HEX64, ManagedContractError, _match
from .paths import MANAGED_LOG_DIRECTORY_NAMES, TRACE_LOG_NAMES
from .storage_budget import ManagedStorageAllocationV1, ManagedStorageBudgetV1

_CAPACITY = 10 * 1024**2
_MAX_SEQUENCE = 2**63 - 1


@contextmanager
def _writer_lock(directory: PrivateManagedDirectory, deadline: float) -> Iterator[None]:
    _check_deadline(deadline)
    if not directory._mutex.acquire(timeout=min(TIMEOUT_MAX, max(0, deadline - monotonic()))):
        raise ManagedStorageError("busy")
    try:
        _check_deadline(deadline)
        yield
    finally:
        directory._mutex.release()


def _json(value: object) -> bytes:
    return (json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _payload(frame: bytes) -> dict[str, Any]:
    if type(frame) is not bytes or not 0 < len(frame) <= 512:
        raise ManagedStorageError("invalid_record")
    try:
        row = json.loads(frame)
        if type(row) is not dict or type(row.get("v")) is not int or row["v"] != 1:
            raise ValueError()
        identity = row.get("instanceId")
        if type(identity) is not str:
            raise ValueError()
        _match(identity, _HEX32)
        base = {"v", "instanceId", "event"}
        if row.get("event") == "problem":
            if (row.keys() != base | {"code"} or type(row["code"]) is not str
                    or row["code"] not in {"startup_failed", "application_failed", "cleanup_incomplete"}):
                raise ValueError()
        elif row.get("event") == "turn":
            fields = row.keys() - base
            if (not base <= row.keys() or not fields
                    or not fields <= {"total_ms", "startup_ms", "local_ready_ms"}):
                raise ValueError()
            for key in fields:
                number = row[key]
                if type(number) not in (int, float) or not 0 <= number <= 86400000:
                    raise ValueError()
        else:
            raise ValueError()
        if _json(row) != frame:
            raise ValueError()  # Reject duplicates, trailing data and alternate encodings.
        return row
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ManagedStorageError("invalid_record") from None


def _encode(frame: bytes, sequence: int) -> bytes:
    if type(sequence) is not int or not 1 <= sequence <= _MAX_SEQUENCE:
        raise ManagedStorageError("capacity")
    return _json({"sequence": sequence, "record": _payload(frame)})


def _sequence(snapshot: ManagedDataFileSnapshot | None) -> int:
    if snapshot is None or snapshot.size == 0:
        return 0
    tail = snapshot.tail
    if not tail.endswith(b"\n"):
        raise ManagedStorageError("invalid_record")
    boundary = tail.rfind(b"\n", 0, len(tail) - 1)
    if boundary == -1 and snapshot.size != len(tail):
        raise ManagedStorageError("invalid_record")
    frame = tail[boundary + 1:]
    if len(frame) > 640:
        raise ManagedStorageError("invalid_record")
    try:
        row = json.loads(frame)
        if type(row) is not dict or row.keys() != {"sequence", "record"}:
            raise ValueError()
        if _encode(_json(row["record"]), row["sequence"]) != frame:
            raise ValueError()
        return row["sequence"]
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ManagedStorageError("invalid_record") from None


class ManagedTraceLog:
    def __init__(self, directory: PrivateManagedDirectory, budget: ManagedStorageBudgetV1,
                 service_id: str, *, segment_bytes: int = _CAPACITY) -> None:
        if (type(directory) is not PrivateManagedDirectory or type(budget) is not ManagedStorageBudgetV1
                or type(segment_bytes) is not int or not 1024 <= segment_bytes <= _CAPACITY):
            raise ManagedContractError()
        _match(service_id, _HEX64)
        self._directory, self._budget = directory, budget
        self._service_id, self._segment_bytes = service_id, segment_bytes
        self._failed = False

    def _allocation(self, slot: int) -> ManagedStorageAllocationV1:
        directory = self._directory
        directory._check()
        return ManagedStorageAllocationV1(self._service_id, "trace", None, slot, _CAPACITY,
            sha256(os.fsencode(directory._root)).hexdigest(), directory._identity)

    def _create_slot(self, slot: int, deadline: float) -> ManagedDataFileSnapshot:
        _check_deadline(deadline)
        reservation = self._budget.reserve(self._allocation(slot), exclusive=True, deadline=deadline, wait_for_lock=True)
        _check_deadline(deadline)
        snapshot = self._directory.append_data(TRACE_LOG_NAMES[slot], b"", expected=None,
                                               capacity=self._segment_bytes)
        self._budget.bind_file(reservation, snapshot.identity, deadline=deadline, wait_for_lock=True)
        return snapshot

    def prepare(self, *, deadline: float) -> None:
        """Admit both charged slots before an outer application receipt.

        This alone is not evidence that a sink or consumer has been installed.
        Partial/unknown admission seals this writer and retains all charges.
        """
        _check_deadline(deadline)
        if _on_event_loop():
            raise ManagedStorageError("busy")
        with _writer_lock(self._directory, deadline):
            if self._failed:
                raise ManagedStorageError("closed")
            try:
                with self._directory.lock("trace.lock", create=True, deadline=deadline):
                    snapshots = self._snapshots(deadline)
                    sequences = [_sequence(snapshot) for snapshot in snapshots]
                    if sequences[0] != 0 and sequences[0] == sequences[1]:
                        raise ManagedStorageError("invalid_record")
                    for slot, snapshot in enumerate(snapshots):
                        if snapshot is None:
                            self._create_slot(slot, deadline)
                    _check_deadline(deadline)
            except BaseException:
                self._failed = True
                raise

    def write(self, frame: bytes, *, deadline: float) -> int | None:
        _payload(frame)  # Reject non-projected data before native admission.
        _check_deadline(deadline)
        if _on_event_loop():
            raise ManagedStorageError("busy")
        with _writer_lock(self._directory, deadline):
            _check_deadline(deadline)
            if self._failed:
                raise ManagedStorageError("closed")
            admitted = False
            try:
                with self._directory.lock("trace.lock", create=True, deadline=deadline):
                    admitted = True
                    snapshots = self._snapshots(deadline)
                    sequences = [_sequence(item) for item in snapshots]
                    if sequences[0] != 0 and sequences[0] == sequences[1]:
                        raise ManagedStorageError("invalid_record")
                    sequence = max(sequences) + 1
                    content = _encode(frame, sequence)
                    slot = sequences.index(max(sequences))
                    snapshot = snapshots[slot]
                    rotate = snapshot is not None and snapshot.size + len(content) > self._segment_bytes
                    if rotate:
                        slot = 1 - slot
                        snapshot = snapshots[slot]
                    _check_deadline(deadline)
                    if snapshot is None:
                        snapshot = self._create_slot(slot, deadline)
                    _check_deadline(deadline)
                    self._directory.append_data(TRACE_LOG_NAMES[slot], content, expected=snapshot,
                                                capacity=self._segment_bytes, truncate=rotate)
                    return sequence
            except BaseException as error:
                if (not admitted and isinstance(error, ManagedStorageError) and error.code == "busy"
                        and not self._directory.cleanup_pending):
                    return None
                self._failed = True
                raise

    def _snapshots(self, deadline: float) -> list[ManagedDataFileSnapshot | None]:
        directory = self._directory
        if set(directory.names(limit=len(MANAGED_LOG_DIRECTORY_NAMES))) - MANAGED_LOG_DIRECTORY_NAMES:
            raise ManagedStorageError("invalid_record")
        result = []
        for slot, name in enumerate(TRACE_LOG_NAMES):
            _check_deadline(deadline)
            reservation = self._budget.lookup(self._allocation(slot), deadline=deadline, wait_for_lock=True)
            snapshot = directory.data_snapshot(name, capacity=self._segment_bytes)
            if reservation is None:
                if snapshot is not None:
                    raise ManagedStorageError("conflict")
            elif (snapshot is None or reservation.file_identity is None
                  or reservation.file_identity != snapshot.identity):
                raise ManagedStorageError("conflict")
            result.append(snapshot)
        return result
