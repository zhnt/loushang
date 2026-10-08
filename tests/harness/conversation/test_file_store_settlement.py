from __future__ import annotations

import asyncio
import contextvars
import threading
from time import monotonic

import pytest

from loushang.harness.conversation import ConversationKey
from loushang.harness.journal import _owned_io as module

from .test_store_conformance import _file_factory, _Header, _Record


async def entered(event):
    deadline = monotonic() + 5
    while not event.is_set():
        assert monotonic() < deadline, "native operation did not start"
        await asyncio.sleep(0.001)


def operation(store, name):
    key = ConversationKey("sessions", "one")
    calls = {
        "create": lambda: store.create(key, _Header("one"), operation_id="create"),
        "load": lambda: store.load(key),
        "append": lambda: store.append(key, _Record("r1", "text"), expected_revision=0, operation_id="r1"),
        "append_batch": lambda: store.append_batch(key, [_Record("r1", "text")], expected_revision=0, operation_ids=["r1"]),
        "delete": lambda: store.delete(key, expected_revision=0, operation_id="delete"),
        "scan": lambda: store.scan("sessions"),
        "scan_page": lambda: store.scan_page("sessions"),
    }
    return calls[name]()


@pytest.mark.parametrize("name", ["create", "load", "append", "append_batch", "delete", "scan", "scan_page"])
def test_repeated_waiter_cancellation_waits_for_exact_native_operation(tmp_path, monkeypatch, name):
    store = _file_factory(tmp_path)()
    ready, release, completed = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def native(*args, **kwargs):
        calls.append(1)
        ready.set()
        assert release.wait(5)
        completed.set()
        return object()

    monkeypatch.setattr(store, "_" + name + "_sync", native)

    async def scenario():
        task = asyncio.create_task(operation(store, name))
        try:
            await entered(ready)
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                assert not task.done(), "caller returned before native IO settled"
            assert calls == [1] and not completed.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert completed.is_set() and calls == [1]
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_native_failure_has_priority_over_waiter_cancellation(tmp_path, monkeypatch, cancel):
    store = _file_factory(tmp_path)()
    ready, release = threading.Event(), threading.Event()
    failure = ValueError("actual native failure")

    def native(*args):
        ready.set()
        assert release.wait(5)
        raise failure

    monkeypatch.setattr(store, "_load_sync", native)

    async def scenario():
        task = asyncio.create_task(operation(store, "load"))
        try:
            await entered(ready)
            if cancel:
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
            release.set()
            with pytest.raises(ValueError) as caught:
                await task
            assert caught.value is failure
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_private_offload_cancellation_still_waits_for_independent_native_receipt(tmp_path, monkeypatch):
    store = _file_factory(tmp_path)()
    ready, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls, offloads = [], []
    original = asyncio.to_thread

    def native(*args):
        calls.append(1)
        ready.set()
        assert release.wait(5)
        finished.set()
        return "result"

    async def observe(*args, **kwargs):
        offloads.append(asyncio.current_task())
        return await original(*args, **kwargs)

    monkeypatch.setattr(store, "_load_sync", native)
    monkeypatch.setattr(module.asyncio, "to_thread", observe)

    async def scenario():
        task = asyncio.create_task(operation(store, "load"))
        try:
            await entered(ready)
            offloads[0].cancel()
            for _ in range(5):
                await asyncio.sleep(0)
            assert offloads[0].cancelled() and not task.done()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and calls == [1]
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert finished.is_set() and calls == [1]
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_publication_failure_has_no_native_effect(tmp_path, monkeypatch):
    store = _file_factory(tmp_path)()
    native_calls = []
    monkeypatch.setattr(store, "_load_sync", lambda *args: native_calls.append(1))

    async def scenario():
        def reject(work, **kwargs):
            raise RuntimeError("task publication failed")

        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "create_task", reject)
            with pytest.raises(RuntimeError, match="publication"):
                await operation(store, "load")
        await asyncio.sleep(0)
        assert native_calls == []

    asyncio.run(scenario())


def test_success_preserves_result_identity_and_contextvars(tmp_path, monkeypatch):
    store = _file_factory(tmp_path)()
    context = contextvars.ContextVar("file-store-test-context", default="missing")
    result = object()

    def native(*args):
        assert context.get() == "caller"
        return result

    monkeypatch.setattr(store, "_load_sync", native)

    async def scenario():
        context.set("caller")
        assert await operation(store, "load") is result

    asyncio.run(scenario())


@pytest.mark.parametrize("name", ["create", "append"])
def test_real_jsonl_write_settles_before_cancelled_lifecycle_disposes(tmp_path, monkeypatch, name):
    from loushang.harness.conversation import ConversationHeader
    from loushang.harness.transcript import (
        AgentTranscriptFileLayout,
        AgentTranscriptLifecycle,
        AgentTranscriptProfile,
        AgentTranscriptRuntimeBinding,
        create_agent_transcript_file_store,
        load_agent_transcript_file,
        load_agent_transcript_header,
    )

    from ..transcript.test_lifecycle import _record

    header = ConversationHeader("actual-one", 1, "2026-09-13T00:00:00Z")
    path = tmp_path / "actual.jsonl"
    ready, release = threading.Event(), threading.Event()
    events = []

    async def bind(context, unused):
        layout = AgentTranscriptFileLayout(context.session_dir)
        key = layout.key(header.conversation_id)
        layout.bind_create_path(key, path)
        store = create_agent_transcript_file_store(layout)
        target = "_create_sync" if name == "create" else "_append_sync"
        original = getattr(store, target)

        def native(*args, **kwargs):
            value = original(*args, **kwargs)  # Actual JSONL committed before cancel.
            events.append("write_complete")
            ready.set()
            assert release.wait(5)  # The native call has not delivered its receipt.
            events.append("native_return")
            return value

        monkeypatch.setattr(store, target, native)

        async def dispose():
            events.append("dispose")

        return AgentTranscriptRuntimeBinding(store, key, AgentTranscriptProfile.default(), None, dispose)

    lifecycle = AgentTranscriptLifecycle(bind_runtime=bind)
    context = lifecycle.new_context(session_dir=tmp_path, cwd=tmp_path, persist=True,
                                    header=header, session_file=path)

    async def scenario():
        if name == "create":
            work = lifecycle.create(context, None, defer_materialization=False)
        else:
            session = await lifecycle.create(context, None, defer_materialization=False)

            async def append():
                try:
                    return await session.runtime_binding.store.append(
                        session.runtime_binding.key, _record("r1"), expected_revision=0, operation_id="r1",
                    )
                finally:
                    await session.dispose()

            work = append()
        task = asyncio.create_task(work)
        try:
            await entered(ready)
            assert load_agent_transcript_header(path) == header
            task.cancel()
            for _ in range(3):
                await asyncio.sleep(0)
            assert events == ["write_complete"] and not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert events == ["write_complete", "native_return", "dispose"]
            assert load_agent_transcript_header(path) == header  # Cancellation is not rollback.
            assert len(load_agent_transcript_file(path)[1]) == (0 if name == "create" else 1)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
