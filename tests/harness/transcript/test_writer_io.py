from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

import pytest

from loushang.harness.conversation import ConversationKey
from loushang.harness.transcript.model_input_v2_types import (
    DeferredModelInputNodeBundle,
)
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_lifecycle import _header, _record
from .test_model_input_v2_index_file import _model_input_records
from .test_runtime_profile import _runtime
from .test_writer_lifecycle import assert_available, assert_busy
from .test_writer_runtime import prepare

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux writer")


async def wait_until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


def invoke(store, key, method):
    if method == "create":
        return store.create(key, _header(), operation_id="test-create")
    if method == "append":
        return store.append(key, _record("one"), expected_revision=0, operation_id="one")
    if method == "append_batch":
        return store.append_batch(key, [_record("one")], expected_revision=0, operation_ids=["one"])
    if method == "delete":
        return store.delete(key, expected_revision=0, operation_id="delete")
    return getattr(store, method)(key.namespace if method.startswith("scan") else key)


@pytest.mark.parametrize("method", ["create", "load", "append", "append_batch", "delete", "scan", "scan_page"])
def test_all_store_entries_hold_writer_until_native_settlement(tmp_path, monkeypatch, method):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(
            tmp_path, runtime, runtime.bind_lifecycle_owned,
            defer_materialization=method == "create",
        )
        session = await owner.create()
        store, key = session.runtime_binding.store, session.runtime_binding.key
        assert session.product_binding.value("conversation.store") is store
        entered, release = threading.Event(), threading.Event()
        events = []
        original = getattr(store, f"_{method}_sync")
        dispose = runtime._binder.dispose

        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            result = original(*args, **kwargs)
            events.append("io")
            return result

        async def cleanup(binding):
            events.append("dispose")
            await dispose(binding)

        monkeypatch.setattr(store, f"_{method}_sync", blocked)
        monkeypatch.setattr(runtime._binder, "dispose", cleanup)
        operation = asyncio.create_task(invoke(store, key, method))
        try:
            await wait_until(entered.is_set)
            closing = asyncio.create_task(owner.dispose())
            await wait_until(lambda: owner.closing)
            operation.cancel()
            operation.cancel()
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert not operation.done() and events == [] and owner.cleanup_pending
            assert_busy(tmp_path)
            with pytest.raises(TranscriptWriterError, match="closed"):
                await invoke(store, key, method)
            rejoin = asyncio.create_task(owner.dispose())
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await operation
            await rejoin
            assert events == ["io", "dispose"]
            assert not owner.cleanup_pending
            assert_available(tmp_path)
            with pytest.raises(TranscriptWriterError, match="closed"):
                await store.load(key)
        finally:
            release.set()
    asyncio.run(scenario())


@pytest.mark.parametrize("target", ["key", "namespace"])
def test_wrong_target_rejected_before_validation_or_native_io(tmp_path, monkeypatch, target):
    async def scenario():
        runtime = _runtime("coding")
        owner, writer = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        store = session.runtime_binding.store

        def forbidden(*_, **__):
            raise AssertionError("wrong target reached validation/native IO")

        with monkeypatch.context() as patch:
            patch.setattr(writer, "check", forbidden)
            patch.setattr(store, "_load_sync", forbidden)
            patch.setattr(store, "_scan_sync", forbidden)
            with pytest.raises(TranscriptWriterError, match="conflict"):
                if target == "key":
                    await store.load(ConversationKey(str(tmp_path), "other"))
                else:
                    await store.scan(str(tmp_path / "other"))
        assert owner._active_io == 0
        await owner.dispose()
    asyncio.run(scenario())


@pytest.mark.parametrize("fail_check", [False, True])
def test_validation_is_admitted_and_drained_before_writer_release(tmp_path, monkeypatch, fail_check):
    async def scenario():
        runtime = _runtime("coding")
        owner, writer = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        entered, release = threading.Event(), threading.Event()
        original = writer.check

        def check(**kwargs):
            entered.set()
            assert release.wait(5)
            if fail_check:
                raise TranscriptWriterError("conflict")
            original(**kwargs)

        monkeypatch.setattr(writer, "check", check)
        operation = asyncio.create_task(session.runtime_binding.store.load(session.runtime_binding.key))
        try:
            await wait_until(entered.is_set)
            closing = asyncio.create_task(owner.dispose())
            await wait_until(lambda: owner.closing)
            assert owner._active_io == 1
            assert_busy(tmp_path)
            operation.cancel()
            release.set()
            with pytest.raises(TranscriptWriterError if fail_check else asyncio.CancelledError):
                await operation
            await closing
            assert owner._active_io == 0 and not owner.cleanup_pending
            assert_available(tmp_path)
        finally:
            release.set()
    asyncio.run(scenario())


def test_graph_retains_admission_and_runtime_disposer_cannot_start_io(tmp_path, monkeypatch):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        store, key = session.runtime_binding.store, session.runtime_binding.key
        session._begin_graph_construction()
        session._commit_graph_ownership()
        await owner.dispose()
        assert not owner.closing
        await store.append(key, _record("one"), expected_revision=0, operation_id="one")
        original = runtime._binder.dispose

        async def dispose(binding):
            with pytest.raises(TranscriptWriterError, match="closed"):
                await store.load(key)
            await original(binding)

        monkeypatch.setattr(runtime._binder, "dispose", dispose)
        await asyncio.wait_for(session._dispose_graph_owned(), 5)
        assert_available(tmp_path)
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["delete", "symlink"])
def test_owned_deferred_snapshot_never_reopens_path_after_disposal(tmp_path, monkeypatch, change):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = await owner.create()
        store, key = session.runtime_binding.store, session.runtime_binding.key
        records = _model_input_records()
        await store.append_batch(key, records, expected_revision=0, operation_ids=[r.record_id for r in records])
        await store.load(key)  # Build the writable index.
        snapshot = (await store.load(key)).snapshot
        assert isinstance(snapshot.records[0].payload, DeferredModelInputNodeBundle)
        await owner.dispose()
        path = tmp_path / "session.jsonl"
        path.unlink()
        if change == "symlink":
            path.symlink_to(tmp_path / "missing")

        def forbidden(*_, **__):
            raise AssertionError("owned deferred payload reopened source")

        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", forbidden)
            assert snapshot.records[0].payload.nodes == records[0].payload.nodes
            assert snapshot.records[1].payload.nodes == records[1].payload.nodes
    asyncio.run(scenario())


def test_closing_during_binding_rejects_late_materialization_and_cleans_raw_binding(tmp_path):
    async def scenario():
        runtime = _runtime("coding")
        entered, release = asyncio.Event(), asyncio.Event()
        raw = []

        async def bind(context, profile, owner):
            result = await runtime.bind_lifecycle_owned(context, profile, owner)
            raw.append(result)
            entered.set()
            await release.wait()
            return result

        owner, _ = prepare(tmp_path, runtime, bind)
        creating = asyncio.create_task(owner.create())
        await asyncio.wait_for(entered.wait(), 5)
        closing = asyncio.create_task(owner.dispose())
        await wait_until(lambda: owner.closing)
        assert_busy(tmp_path)
        release.set()
        with pytest.raises(TranscriptWriterError, match="closed"):
            await creating
        await closing
        assert raw[0].product_binding.is_closed
        assert not (tmp_path / "session.jsonl").exists()
        assert not owner.cleanup_pending
        assert_available(tmp_path)
    asyncio.run(scenario())


def test_first_materialization_settles_after_create_and_dispose_waiters_cancel(tmp_path, monkeypatch):
    async def scenario():
        runtime = _runtime("coding")
        entered, release = threading.Event(), threading.Event()
        events = []
        original_dispose = runtime._binder.dispose

        async def bind(context, profile, owner):
            binding = await runtime.bind_lifecycle_owned(context, profile, owner)
            original_create = binding.store._create_sync

            def create(*args, **kwargs):
                entered.set()
                assert release.wait(5)
                result = original_create(*args, **kwargs)
                events.append("created")
                return result

            monkeypatch.setattr(binding.store, "_create_sync", create)
            return binding

        async def dispose(binding):
            events.append("disposed")
            await original_dispose(binding)

        monkeypatch.setattr(runtime._binder, "dispose", dispose)
        owner, _ = prepare(tmp_path, runtime, bind)
        creating = asyncio.create_task(owner.create())
        try:
            await wait_until(entered.is_set)
            creating.cancel()
            with pytest.raises(asyncio.CancelledError):
                await creating
            closing = asyncio.create_task(owner.dispose())
            await wait_until(lambda: owner.closing)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert_busy(tmp_path)
            assert events == [] and not (tmp_path / "session.jsonl").exists()
            rejoin = asyncio.create_task(owner.dispose())
            release.set()
            await asyncio.wait_for(rejoin, 5)
            assert events == ["created", "disposed"]
            assert (tmp_path / "session.jsonl").is_file()
            assert not owner.cleanup_pending
            assert_available(tmp_path)
        finally:
            release.set()
    asyncio.run(scenario())
