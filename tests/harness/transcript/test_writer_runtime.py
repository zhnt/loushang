from __future__ import annotations

import asyncio
import sys
from dataclasses import replace

import pytest

from loushang.harness.runtime import RuntimeCapabilityBindingError
from loushang.harness.transcript import AgentTranscriptLifecycle
from loushang.harness.transcript.writer_lease import (
    TranscriptWriterError,
    TranscriptWriterLease,
)

from .test_lifecycle import _header
from .test_runtime_profile import _runtime
from .test_writer_lifecycle import assert_available, assert_busy

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux writer")


def test_raw_runtime_is_retained_before_projection_and_cleanup_can_retry(tmp_path, monkeypatch):
    async def scenario():
        runtime = _runtime("coding")
        lifecycle = AgentTranscriptLifecycle(
            bind_runtime=runtime.bind_lifecycle,
            bind_runtime_owned=runtime.bind_lifecycle_owned,
        )
        context = lifecycle.new_context(
            session_dir=tmp_path, cwd="/workspace", persist=True,
            header=_header(), session_file=tmp_path / "session.jsonl",
        )
        writer = TranscriptWriterLease(tmp_path, "coding", context.header.conversation_id)
        writer.acquire()
        owner = lifecycle.prepare_writer(
            context, runtime.resolve(persist=True), writer=writer, product_id="coding",
        )
        raw = []
        calls = []
        original = runtime._binder.dispose

        def fail_projection(binding):
            raw.append(binding)
            raise ValueError("test projection")

        async def dispose(binding):
            calls.append(binding)
            if len(calls) == 1:
                raise RuntimeError("test retry cleanup")
            await original(binding)

        monkeypatch.setattr(runtime, "selected_store", fail_projection)
        monkeypatch.setattr(runtime._binder, "dispose", dispose)
        with pytest.raises(ValueError, match="test projection"):
            await owner.create()
        assert not (tmp_path / "session.jsonl").exists()
        assert len(raw) == 1 and not raw[0].is_closed
        assert_busy(tmp_path)
        with pytest.raises(RuntimeError, match="test retry cleanup"):
            await owner.dispose()
        assert owner.cleanup_pending
        assert_busy(tmp_path)
        await owner.dispose()
        assert calls == [raw[0], raw[0]] and raw[0].is_closed
        assert not owner.cleanup_pending
        assert_available(tmp_path)
    asyncio.run(scenario())


def prepare(root, runtime, bind_owned, *, defer_materialization=False, manage_blobs=False):
    lifecycle = AgentTranscriptLifecycle(
        bind_runtime=runtime.bind_lifecycle, bind_runtime_owned=bind_owned,
    )
    context = lifecycle.new_context(
        session_dir=root, cwd="/workspace", persist=True,
        header=_header(), session_file=root / "session.jsonl",
    )
    writer = TranscriptWriterLease(root, "coding", context.header.conversation_id)
    writer.acquire()
    owner = lifecycle.prepare_writer(
        context, runtime.resolve(persist=True), writer=writer, product_id="coding",
        defer_materialization=defer_materialization,
        manage_blobs=manage_blobs,
    )
    return owner, writer


def test_owned_success_rejects_duplicate_and_late_retention(tmp_path):
    async def scenario():
        runtime = _runtime("coding")
        callbacks = []
        raw = []

        async def bind(context, profile, retain):
            result = await runtime.bind_lifecycle_owned(context, profile, retain)
            callbacks.append(retain)
            raw.append(result)
            with pytest.raises(TranscriptWriterError, match="closed"):
                retain(result.dispose)
            return result

        owner, writer = prepare(tmp_path, runtime, bind)
        session = await owner.create()
        assert (tmp_path / "session.jsonl").is_file()
        assert session.runtime_binding is raw[0]
        with pytest.raises(TranscriptWriterError, match="closed"):
            callbacks[0](raw[0].dispose)
        assert_busy(tmp_path)
        await owner.dispose()
        assert not owner.cleanup_pending and not writer.cleanup_pending
        assert raw[0].product_binding.is_closed
    asyncio.run(scenario())


def test_cancelled_waiter_rejoins_same_raw_binding(tmp_path):
    async def scenario():
        runtime = _runtime("coding")
        entered, release = asyncio.Event(), asyncio.Event()
        raw = []

        async def bind(context, profile, retain):
            result = await runtime.bind_lifecycle_owned(context, profile, retain)
            raw.append(result)
            entered.set()
            await release.wait()
            return result

        owner, _ = prepare(tmp_path, runtime, bind)
        waiter = asyncio.create_task(owner.create())
        await asyncio.wait_for(entered.wait(), 5)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert len(raw) == 1
        assert_busy(tmp_path)
        release.set()
        session = await owner.create()
        assert session.runtime_binding is raw[0] and len(raw) == 1
        await owner.dispose()
        assert_available(tmp_path)
    asyncio.run(scenario())


def test_late_callback_after_failed_projection_cannot_replace_cleanup(tmp_path):
    async def scenario():
        runtime = _runtime("coding")
        raw, callbacks = [], []

        async def bind(context, profile, retain):
            result = await runtime.bind_lifecycle_owned(context, profile, retain)
            raw.append(result)
            callbacks.append(retain)
            raise ValueError("after retain")

        owner, _ = prepare(tmp_path, runtime, bind)
        with pytest.raises(ValueError, match="after retain"):
            await owner.create()
        with pytest.raises(TranscriptWriterError, match="closed"):
            callbacks[0](raw[0].dispose)
        await owner.dispose()
        assert raw[0].product_binding.is_closed
        assert not owner.cleanup_pending
        assert_available(tmp_path)
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["conflict", "missing"])
def test_conflicting_returned_disposer_does_not_release_writer(tmp_path, mode):
    async def scenario():
        runtime = _runtime("coding")
        raw = []

        async def noop():
            pass

        async def bind(context, profile, retain):
            if mode == "missing":
                result = await runtime.bind_lifecycle(context, profile)
            else:
                result = await runtime.bind_lifecycle_owned(context, profile, retain)
            raw.append(result)
            return replace(result, dispose=noop) if mode == "conflict" else result

        owner, writer = prepare(tmp_path, runtime, bind)
        with pytest.raises(TranscriptWriterError, match="conflict"):
            await owner.create()
        with pytest.raises(TranscriptWriterError, match="unavailable"):
            await owner.dispose()
        assert owner.cleanup_pending and not raw[0].product_binding.is_closed
        assert_busy(tmp_path)
        # The test owns both injected authorities and knows noop is effect-free.
        await raw[0].dispose()
        writer._close_claimed(owner)
    asyncio.run(scenario())


def test_standard_partial_factory_failure_keeps_cleanup_ledger_and_writer(tmp_path, monkeypatch):
    async def scenario():
        runtime = _runtime("coding")
        disposed, raw = [], []
        implementations = runtime._binder._registry._implementations
        for key, implementation in tuple(implementations.items()):
            if implementation.slot == "context.compaction":
                def fail_factory(*_):
                    raise ValueError("test later factory")
                implementations[key] = replace(implementation, create=fail_factory)
            else:
                def dispose(_value, _context, slot=implementation.slot):
                    disposed.append(slot)
                    if slot == "conversation.store" and disposed.count(slot) == 1:
                        raise RuntimeError("test store cleanup retry")
                implementations[key] = replace(implementation, dispose=dispose)
        original = runtime._binder.prepare_binding

        def capture(*args, **kwargs):
            binding = original(*args, **kwargs)
            raw.append(binding)
            return binding

        monkeypatch.setattr(runtime._binder, "prepare_binding", capture)
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        with pytest.raises(RuntimeCapabilityBindingError) as failure:
            await owner.create()
        assert failure.value.slot == "context.compaction"
        assert isinstance(failure.value.__cause__, ValueError)
        assert not (tmp_path / "session.jsonl").exists()
        assert len(raw) == 1 and disposed == []
        assert_busy(tmp_path)
        with pytest.raises(RuntimeCapabilityBindingError):
            await owner.dispose()
        assert disposed == ["agent.transcript_profile", "conversation.store"]
        assert_busy(tmp_path)
        await owner.dispose()
        assert disposed == ["agent.transcript_profile", "conversation.store", "conversation.store"]
        assert raw[0].is_closed and not owner.cleanup_pending
        assert_available(tmp_path)
    asyncio.run(scenario())


def test_runtime_disposal_publication_failure_does_not_release_writer(tmp_path):
    async def scenario():
        runtime = _runtime("coding")
        disposed = []
        implementations = runtime._binder._registry._implementations
        for key, implementation in tuple(implementations.items()):
            def dispose(_value, _context, slot=implementation.slot):
                disposed.append(slot)
            implementations[key] = replace(implementation, dispose=dispose)
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        await owner.create()
        loop = asyncio.get_running_loop()

        def task_factory(loop, coro, **kwargs):
            if coro.cr_code.co_name == "dispose_entries":
                raise RuntimeError("test disposal publication")
            return asyncio.Task(coro, loop=loop, **kwargs)

        loop.set_task_factory(task_factory)
        try:
            with pytest.raises(RuntimeError, match="test disposal publication"):
                await owner.dispose()
        finally:
            loop.set_task_factory(None)
        assert disposed == [] and owner.cleanup_pending
        assert_busy(tmp_path)
        await owner.dispose()
        assert disposed == ["context.compaction", "agent.transcript_profile", "conversation.store"]
        assert not owner.cleanup_pending
        assert_available(tmp_path)
    asyncio.run(scenario())
