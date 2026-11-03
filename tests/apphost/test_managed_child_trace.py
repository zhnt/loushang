from __future__ import annotations

import asyncio
import threading
from time import monotonic

import pytest

from loushang.apphost.managed.child import ManagedChildApplicationV1, ManagedChildError
from loushang.apphost.managed.trace_buffer import ManagedTraceBuffer
from loushang.foundation.observability.records import DebugEventRecord

from . import test_managed_child as fixtures

binding = fixtures.binding
pytestmark = fixtures.pytestmark


def trace(buffer):
    buffer.write_debug_event(DebugEventRecord("turn.start.performance", "turn", {"total_ms": 1}))


@pytest.mark.parametrize("fail", [False, True])
def test_trace_uses_original_diagnostic_slot_and_failure_keeps_lifecycle(binding, fail):
    _, _, _, _, control = binding
    buffer = ManagedTraceBuffer("a" * 32, monotonic() + 60)
    calls, events = [], []
    def write(frame, deadline):
        calls.append((frame, deadline, threading.current_thread().name))
        if fail:
            raise OSError("private failure")
    async def run():
        app = fixtures.Application()
        owner = ManagedChildApplicationV1(app, control, trace_buffer=buffer, trace_write=write,
                                          diagnostic=lambda event, code: events.append(event))
        waiter = asyncio.create_task(owner.run())
        try:
            await fixtures.until(lambda: owner.accepting)
            trace(buffer)
            await fixtures.until(lambda: bool(calls))
        finally:
            await owner.close()
            await asyncio.gather(waiter, return_exceptions=True)
        assert not owner.cleanup_pending
        assert len(calls) == 1 and calls[0][1] == buffer.deadline
        assert calls[0][2].startswith("lmux-control")
        assert events == ["starting", "ready", "stopping", "stopped"]
        trace(buffer)
        assert buffer.take() is None
    asyncio.run(asyncio.wait_for(run(), 10))


def test_blocked_trace_does_not_block_application_stop_but_retains_native_work(binding):
    _, _, _, _, control = binding
    buffer = ManagedTraceBuffer("a" * 32, monotonic() + 60)
    entered, release = threading.Event(), threading.Event()
    def write(frame, deadline):
        entered.set()
        assert release.wait(5)
    async def run():
        app = fixtures.Application()
        owner = ManagedChildApplicationV1(app, control, trace_buffer=buffer, trace_write=write,
                                          settlement_timeout=0.1)
        waiter = asyncio.create_task(owner.run())
        try:
            await fixtures.until(lambda: owner.accepting)
            trace(buffer)
            await fixtures.until(entered.is_set)
            with pytest.raises(ManagedChildError, match="cleanup_incomplete"):
                await owner.close()
            assert app.closed.is_set() and owner.cleanup_pending
        finally:
            release.set()
            await asyncio.gather(owner._close_task, return_exceptions=True)
            await owner.close(retry_timeout=2)
            await asyncio.gather(waiter, return_exceptions=True)
        assert not owner.cleanup_pending
    asyncio.run(asyncio.wait_for(run(), 10))


@pytest.mark.parametrize("scheduled", [False, True])
def test_final_trace_drain_publication_failure_has_no_native_effect(binding, scheduled):
    _, _, _, _, control = binding
    buffer = ManagedTraceBuffer("a" * 32, monotonic() + 60)
    calls = []
    async def run():
        owner = ManagedChildApplicationV1(fixtures.Application(), control,
            trace_buffer=buffer, trace_write=lambda *args: calls.append(args))
        trace(buffer)
        buffer.fence()
        loop = asyncio.get_running_loop()
        original = loop.get_task_factory()
        tasks = []
        def fail(loop, coroutine, **kwargs):
            if scheduled:
                tasks.append(asyncio.Task(coroutine, loop=loop, **kwargs))
            raise RuntimeError("lost task publication")
        loop.set_task_factory(fail)
        try:
            await owner._settle_diagnostics(monotonic() + 2)
        finally:
            loop.set_task_factory(original)
            await asyncio.gather(*tasks, return_exceptions=True)
        assert owner._trace_disabled and owner._pending_log is None
        assert calls == [] and buffer.snapshot() == (0, 0, 1)
    asyncio.run(asyncio.wait_for(run(), 10))


def test_trace_only_close_drains_tail_without_another_poll(binding):
    _, _, _, _, control = binding
    buffer = ManagedTraceBuffer("a" * 32, monotonic() + 60)
    calls = []
    async def run():
        owner = ManagedChildApplicationV1(fixtures.Application(), control,
            trace_buffer=buffer, trace_write=lambda *args: calls.append(args))
        waiter = asyncio.create_task(owner.run())
        await fixtures.until(lambda: owner.accepting and owner._diagnostic_task.done())
        trace(buffer)
        await owner.close()
        await waiter
        assert len(calls) == 1 and not owner.cleanup_pending
        assert buffer.snapshot() == (0, 0, 0)
    asyncio.run(asyncio.wait_for(run(), 10))
