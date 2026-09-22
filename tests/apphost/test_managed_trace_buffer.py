from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from loushang.apphost.managed.trace_buffer import ManagedTraceBuffer
from loushang.foundation.observability.records import DebugEventRecord, ProblemRecord


def event(**data):
    return DebugEventRecord("turn.start.performance", "turn", {"total_ms": 12.5, **data})


def test_projection_never_copies_sensitive_or_nested_fields():
    class Forbidden:
        def __deepcopy__(self, memo):
            pytest.fail("must not copy arbitrary trace data")

    buffer = ManagedTraceBuffer("a" * 32, 10, clock=lambda: 0)
    record = event(prompt="secret", milestones=Forbidden(), model_id="private", startup_ms=3)
    buffer.write_debug_event(record)
    record.data["total_ms"] = 900
    assert json.loads(buffer.take()) == {
        "v": 1, "instanceId": "a" * 32, "event": "turn", "total_ms": 12.5, "startup_ms": 3,
    }
    buffer.write_problem(ProblemRecord("application_failed", message="secret", exception_message="token"))
    assert json.loads(buffer.take()) == {
        "v": 1, "instanceId": "a" * 32, "event": "problem", "code": "application_failed",
    }
    buffer.write_problem(ProblemRecord("arbitrary secret code"))
    assert buffer.take() is None


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf"), -1, 86400001, "secret", {}])
def test_invalid_numeric_fields_are_not_serialized(invalid):
    buffer = ManagedTraceBuffer("a" * 32, 10, clock=lambda: 0)
    buffer.write_debug_event(event(total_ms=invalid))
    assert buffer.take() is None


def test_count_byte_limits_fence_and_expiry():
    now = [0]
    buffer = ManagedTraceBuffer("a" * 32, 10, clock=lambda: now[0], max_records=2)
    for _ in range(4):
        buffer.write_debug_event(event())
    assert buffer.snapshot()[::2] == (2, 2)
    buffer.fence()
    buffer.write_debug_event(event())
    assert buffer.take() is not None
    now[0] = 10
    assert buffer.take() is None
    assert buffer.snapshot() == (0, 0, 4)
    limited = ManagedTraceBuffer("b" * 32, 10, clock=lambda: 0, max_bytes=512)
    for _ in range(128):
        limited.write_debug_event(event())
    count, size, dropped = limited.snapshot()
    assert 0 < count < 128 and size <= 512 and count + dropped == 128


def test_multithreaded_producers_are_bounded_and_contention_never_waits():
    buffer = ManagedTraceBuffer("a" * 32, 10, clock=lambda: 0)
    with buffer._lock:
        # A blocking producer lock would deadlock this same-thread call.
        buffer.write_debug_event(event())
    assert buffer.snapshot() == (0, 0, 0)
    def produce():
        for _ in range(500):
            buffer.write_debug_event(event())
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: produce(), range(4)))
    count, size, dropped = buffer.snapshot()
    assert count <= 128 and size <= 65536 and dropped <= 2000
    buffer.fence()
    frames = []
    while (frame := buffer.take()) is not None:
        frames.append(frame)
    assert len(frames) == count and sum(map(len, frames)) == size
