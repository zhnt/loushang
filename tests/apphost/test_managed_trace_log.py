from __future__ import annotations

import json
from threading import Event, Thread
from time import monotonic

import pytest

from loushang.apphost.managed import storage_budget
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.trace_buffer import ManagedTraceBuffer
from loushang.apphost.managed.trace_log import ManagedTraceLog
from loushang.foundation.observability.records import DebugEventRecord

from .test_managed_event_log import event
from .test_managed_event_log import log as log
from .test_managed_event_log import namespace as namespace
from .test_managed_event_log import pytestmark as pytestmark
from .test_managed_event_log import registry as registry


def frame():
    buffer = ManagedTraceBuffer("a" * 32, monotonic() + 60)
    buffer.write_debug_event(DebugEventRecord("turn.start.performance", "turn", {"total_ms": 12}))
    result = buffer.take()
    assert result is not None
    return result


def test_prepare_waits_with_original_deadline_for_all_registry_steps(log, monkeypatch):
    lifecycle, directory, service = log
    writer = ManagedTraceLog(directory, lifecycle._budget, service)
    deadline = monotonic() + 5
    calls = []
    for name in ("lookup", "reserve", "bind_file"):
        original = getattr(lifecycle._budget, name)
        def checked(*args, _name=name, _original=original, **kwargs):
            assert kwargs["deadline"] == deadline
            assert kwargs["wait_for_lock"] is True
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(lifecycle._budget, name, checked)
    writer.prepare(deadline=deadline)
    assert calls == ["lookup", "lookup", "reserve", "bind_file", "reserve", "bind_file"]


def test_trace_rotates_reopens_and_coexists_with_lifecycle(log):
    lifecycle, directory, service = log
    for _ in range(25):
        lifecycle.write(event())
    writer = ManagedTraceLog(directory, lifecycle._budget, service, segment_bytes=1024)
    payload = frame()
    identities = {}
    for index in range(30):
        assert writer.write(payload, deadline=monotonic() + 30) == index + 1
        for path in directory._root.glob("trace-*.jsonl"):
            assert path.stat().st_size <= 1024
            if path.name in identities:
                assert path.stat().st_ino == identities[path.name]
            identities[path.name] = path.stat().st_ino
    assert len(identities) == 2
    reopened = ManagedTraceLog(directory, lifecycle._budget, service, segment_bytes=1024)
    assert reopened.write(payload, deadline=monotonic() + 30) == 31
    assert lifecycle.write(event()) == 26
    assert lifecycle.read_tail()[-1].sequence == 26
    assert sum(lifecycle._budget.lookup(writer._allocation(slot)).allocation.capacity for slot in range(2)) == 20 * 1024**2


def test_trace_prepare_admits_both_slots_without_emitting_an_event(log):
    lifecycle, directory, service = log
    writer = ManagedTraceLog(directory, lifecycle._budget, service)
    writer.prepare(deadline=monotonic() + 30)
    identities = {}
    for slot in range(2):
        path = directory._root / f"trace-{slot}.jsonl"
        assert path.read_bytes() == b""
        reservation = lifecycle._budget.lookup(writer._allocation(slot))
        assert reservation.file_identity == (path.stat().st_dev, path.stat().st_ino)
        identities[slot] = reservation.allocation_id
    writer.prepare(deadline=monotonic() + 30)
    assert {slot: lifecycle._budget.lookup(writer._allocation(slot)).allocation_id for slot in range(2)} == identities
    assert writer.write(frame(), deadline=monotonic() + 30) == 1


def test_invalid_or_expired_trace_has_no_io(log):
    lifecycle, directory, service = log
    writer = ManagedTraceLog(directory, lifecycle._budget, service)
    value = json.loads(frame())
    value["prompt"] = "secret"
    with pytest.raises(ManagedStorageError, match="invalid_record"):
        writer.write((json.dumps(value) + "\n").encode(), deadline=monotonic() + 30)
    with pytest.raises(ManagedStorageError, match="busy"):
        writer.write(frame(), deadline=0)
    assert not tuple(directory._root.iterdir())


def test_original_mutex_wait_obeys_deadline_before_io(log):
    lifecycle, directory, service = log
    writer = ManagedTraceLog(directory, lifecycle._budget, service)
    held, release = Event(), Event()
    def hold():
        with directory._mutex:
            held.set()
            release.wait(10)
    holder = Thread(target=hold)
    holder.start()
    try:
        assert held.wait(5)
        with pytest.raises(ManagedStorageError, match="busy"):
            writer.write(frame(), deadline=monotonic() + 0.05)
        assert holder.is_alive() and not release.is_set()
        assert not writer._failed
        assert not tuple(directory._root.iterdir())
    finally:
        release.set()
        holder.join(5)
    assert not holder.is_alive()
    assert writer.write(frame(), deadline=monotonic() + 30) == 1


def test_trace_capacity_failure_seals_without_replay(log, monkeypatch):
    lifecycle, directory, service = log
    monkeypatch.setattr(storage_budget, "LOG_NAMESPACE_BYTES", 10 * 1024**2)
    writer = ManagedTraceLog(directory, lifecycle._budget, service, segment_bytes=1024)
    payload = frame()
    with pytest.raises(ManagedStorageError, match="capacity"):
        for _ in range(30):
            writer.write(payload, deadline=monotonic() + 30)
    before = (directory._root / "trace-0.jsonl").read_bytes()
    with pytest.raises(ManagedStorageError, match="closed"):
        writer.write(payload, deadline=monotonic() + 30)
    assert (directory._root / "trace-0.jsonl").read_bytes() == before


def test_trace_lost_append_receipt_never_replays(log, monkeypatch):
    lifecycle, directory, service = log
    writer = ManagedTraceLog(directory, lifecycle._budget, service)
    payload = frame()
    writer.write(payload, deadline=monotonic() + 30)
    original = directory.append_data
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise ManagedStorageError("unavailable")
    with monkeypatch.context() as patch:
        patch.setattr(directory, "append_data", lost)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            writer.write(payload, deadline=monotonic() + 30)
    before = (directory._root / "trace-0.jsonl").read_bytes()
    with pytest.raises(ManagedStorageError, match="closed"):
        writer.write(payload, deadline=monotonic() + 30)
    assert (directory._root / "trace-0.jsonl").read_bytes() == before


@pytest.mark.parametrize("committed", [False, True])
def test_trace_first_bind_failure_retains_charge_and_never_adopts_unbound(log, monkeypatch, committed):
    lifecycle, directory, service = log
    writer = ManagedTraceLog(directory, lifecycle._budget, service)
    original = lifecycle._budget.bind_file
    def lost(*args, **kwargs):
        if committed:
            original(*args, **kwargs)
        raise ManagedStorageError("unavailable")
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle._budget, "bind_file", lost)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            writer.write(frame(), deadline=monotonic() + 30)
    assert (directory._root / "trace-0.jsonl").read_bytes() == b""
    reservation = lifecycle._budget.lookup(writer._allocation(0))
    assert reservation is not None and reservation.allocation.capacity == 10 * 1024**2
    assert (reservation.file_identity is not None) == committed
    with pytest.raises(ManagedStorageError, match="closed"):
        writer.write(frame(), deadline=monotonic() + 30)
    reopened = ManagedTraceLog(directory, lifecycle._budget, service)
    if committed:
        # A new explicitly admitted write may use a bound empty file. This is
        # not retry of the old writer or adoption of an unbound reservation.
        assert reopened.write(frame(), deadline=monotonic() + 30) == 1
    else:
        with pytest.raises(ManagedStorageError, match="conflict"):
            reopened.write(frame(), deadline=monotonic() + 30)
        assert (directory._root / "trace-0.jsonl").read_bytes() == b""
