from __future__ import annotations

import asyncio
import sys

import pytest

from loushang.harness.transcript import (
    AgentTranscriptLifecycle,
    AgentTranscriptSessionFactory,
    ProductTranscriptSession,
)
from loushang.harness.transcript import session_factory as module
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_runtime_profile import _runtime
from .test_writer_images import message
from .test_writer_io import wait_until
from .test_writer_lifecycle import assert_available, assert_busy
from .test_writer_root_binding import tree

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned factory")


def factory(*, runtime=None, bind=None, factory_type=AgentTranscriptSessionFactory, **kwargs):
    runtime = runtime or _runtime("coding")
    lifecycle = AgentTranscriptLifecycle(
        bind_runtime=runtime.bind_lifecycle, bind_runtime_owned=bind or runtime.bind_lifecycle_owned,
    )
    return factory_type(
        lifecycle=lifecycle, resolve_binding_input=lambda persist: runtime.resolve(persist=persist),
        header_metadata=lambda _: {}, owned_product_id="coding",
        session_file_factory=lambda root, header: root / f"{header.conversation_id}.jsonl",
        **kwargs,
    )


async def new(selected, root, session_id="conversation-1"):
    return await selected.new(session_dir=root, cwd="/workspace", session_id=session_id)


def test_factory_lazy_store_admission_new_second_session_and_restore(tmp_path):
    async def scenario():
        root, state = tmp_path / "data/sessions", tmp_path / "state/session-stores"
        selected = factory(store_state_root=state)
        assert not root.exists() and not state.exists()
        first = await new(selected, root)
        second = None
        try:
            binding = first._writer_owner._store_admission._binding
            assert first._writer_owner._writer._expected_root_identity == binding.root_identity
            assert first._writer_owner._blob_writer._expected_root_identity == binding.parent_identity
            admission = first._writer_owner._store_admission
            assert not admission._witness.cleanup_pending
            assert not admission._family._lease.cleanup_pending
            assert admission.cleanup_pending  # Only the handed-off directory pins remain.
            # The first Session remains live; the shared initialization lock
            # must not serialize independent Session lifetimes.
            second = await new(selected, root, "conversation-2")
            await ProductTranscriptSession(lifecycle_session=first).append_message(message())
        finally:
            if second is not None:
                await second.dispose()
            await first.dispose()
            await selected.close()
        restored_factory = factory(store_state_root=state)
        restored = await restored_factory.open(first.context.session_file)
        try:
            assert restored.session_blob_health[0].state == "available"
            assert restored.transcript.records == first.transcript.records
        finally:
            await restored.dispose()
            await restored_factory.close()

    asyncio.run(scenario())


def test_factory_public_create_open_and_delivered_session_ownership(tmp_path):
    async def scenario():
        selected = factory()
        session = await new(selected, tmp_path)
        assert not selected.pending_preparations
        await ProductTranscriptSession(lifecycle_session=session).append_message(message())
        await selected.close()
        assert not session._writer_owner.closing
        assert_busy(tmp_path)
        await session.dispose()
        reopened_factory = factory()
        restored = await reopened_factory.open(session.context.session_file)
        try:
            assert restored.session_blob_health[0].state == "available"
            assert restored.transcript.records == session.transcript.records
            assert not reopened_factory.pending_preparations
        finally:
            await restored.dispose()
            await reopened_factory.close()

    asyncio.run(scenario())


def test_busy_public_open_uses_readonly_discovery(tmp_path, monkeypatch):
    async def scenario():
        first_factory = factory()
        first = await new(first_factory, tmp_path)
        await ProductTranscriptSession(lifecycle_session=first).append_message(message())
        second = factory()
        reads = []
        read = module.load_agent_transcript_header

        def readonly(path, **kwargs):
            assert kwargs == {"read_only": True}
            reads.append(path)
            return read(path, **kwargs)

        first.context.session_file.with_name(first.context.session_file.name + ".lock").unlink(missing_ok=True)
        before = tree(tmp_path)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(module, "load_agent_transcript_header", readonly)
                with pytest.raises(TranscriptWriterError, match="busy"):
                    await second.open(first.context.session_file)
            assert reads == [first.context.session_file]
            assert tree(tmp_path) == before
            assert not second.pending_preparations
            assert_busy(tmp_path)
        finally:
            await second.close()
            await first.dispose()
            await first_factory.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["new", "open", "continue_recent"])
def test_closed_factory_rejects_before_discovery_and_callbacks(tmp_path, monkeypatch, method):
    async def scenario():
        selected = factory()
        await selected.close()

        def forbidden(*args, **kwargs):
            raise AssertionError("closed factory performed discovery or callbacks")

        monkeypatch.setattr(module, "load_agent_transcript_header", forbidden)
        monkeypatch.setattr(module, "AgentTranscriptSessionCatalog", forbidden)
        monkeypatch.setattr(selected, "_resolve_binding_input", forbidden)
        with pytest.raises(RuntimeError, match="closed"):
            if method == "new":
                await new(selected, tmp_path)
            elif method == "open":
                await selected.open(tmp_path / "absent.jsonl")
            else:
                await selected.continue_recent(session_dir=tmp_path, cwd="/workspace")
        assert not tuple(tmp_path.iterdir())

    asyncio.run(scenario())


def test_failed_cleanup_keeps_original_typed_preparation(tmp_path, monkeypatch):
    async def scenario():
        runtime = _runtime("coding")

        async def fail_binding(context, profile, owner):
            await runtime.bind_lifecycle_owned(context, profile, owner)
            raise ValueError("test primary construction failure")

        selected = factory(runtime=runtime, bind=fail_binding)
        dispose = runtime._binder.dispose

        async def unavailable(binding):
            raise OSError("test cleanup temporarily unavailable")

        with monkeypatch.context() as patch:
            patch.setattr(runtime._binder, "dispose", unavailable)
            with pytest.raises(ValueError, match="primary construction failure") as failure:
                await new(selected, tmp_path)
            assert "cleanup retained" in failure.value.__notes__[0]
            retained, = selected.pending_preparations
            assert retained.cleanup_pending
            assert_busy(tmp_path)
            with pytest.raises(OSError, match="cleanup temporarily unavailable"):
                await selected.close()
            assert selected.pending_preparations == (retained,)
        assert runtime._binder.dispose == dispose
        await selected.close()
        assert not selected.pending_preparations
        assert_available(tmp_path)

    asyncio.run(scenario())


def test_cancelled_caller_keeps_pending_until_factory_close(tmp_path):
    async def scenario():
        runtime = _runtime("coding")
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(context, profile, owner):
            result = await runtime.bind_lifecycle_owned(context, profile, owner)
            entered.set()
            await release.wait()
            return result

        selected = factory(runtime=runtime, bind=delayed)
        caller = asyncio.create_task(new(selected, tmp_path))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            retained, = selected.pending_preparations
            caller.cancel()
            await wait_until(lambda: retained.closing)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert selected.pending_preparations == (retained,)
            assert_busy(tmp_path)
        finally:
            release.set()
            await asyncio.gather(caller, return_exceptions=True)
            await selected.close()
        assert not selected.pending_preparations
        assert_available(tmp_path)

    asyncio.run(scenario())


def test_close_fences_all_pending_before_waiting(tmp_path):
    async def scenario():
        runtime = _runtime("coding")
        entered, release = [], asyncio.Event()

        async def delayed(context, profile, owner):
            result = await runtime.bind_lifecycle_owned(context, profile, owner)
            entered.append(True)
            await release.wait()
            return result

        selected = factory(runtime=runtime, bind=delayed)
        callers = [asyncio.create_task(new(selected, tmp_path, name)) for name in ("one", "two")]
        closer = None
        try:
            await wait_until(lambda: len(entered) == 2)
            owners = selected.pending_preparations
            closer = asyncio.create_task(selected.close())
            await wait_until(lambda: all(owner.closing for owner in owners))
            assert not closer.done()
            release.set()
            results = await asyncio.gather(*callers, return_exceptions=True)
            assert all(isinstance(result, RuntimeError) for result in results)
            await closer
            assert not selected.pending_preparations
        finally:
            release.set()
            await asyncio.gather(*callers, *([closer] if closer else []), return_exceptions=True)
            await selected.close()

    asyncio.run(scenario())


def test_unwired_owned_paths_reject_before_effects(tmp_path, monkeypatch):
    async def scenario():
        selected = factory()

        def forbidden(*args, **kwargs):
            raise AssertionError("unwired operation accessed inputs")

        monkeypatch.setattr(module, "read_agent_transcript_bundle", forbidden)
        monkeypatch.setattr(selected, "load", forbidden)
        with pytest.raises(ValueError, match="transient"):
            await selected.import_bundle(tmp_path / "absent", session_dir=tmp_path, persist=False)
        with pytest.raises(ValueError, match="transient"):
            await selected.fork_from(tmp_path / "absent", target_cwd="/workspace", session_dir=tmp_path, persist=False)
        with pytest.raises(ValueError, match="transient"):
            await selected.in_memory()
        assert not tuple(tmp_path.iterdir())
        await selected.close()

    asyncio.run(scenario())


def test_wrong_loop_rejects_before_effects_and_original_loop_can_close(tmp_path, monkeypatch):
    selected = factory()
    original = asyncio.new_event_loop()

    async def establish():
        session = await new(selected, tmp_path)
        await session.dispose()

    original.run_until_complete(establish())

    def forbidden(*args, **kwargs):
        raise AssertionError("wrong-loop factory accessed inputs")

    async def wrong_loop():
        for operation in (
            lambda: new(selected, tmp_path),
            lambda: selected.open(tmp_path / "absent.jsonl"),
            lambda: selected.continue_recent(session_dir=tmp_path, cwd="/workspace"),
            selected.close,
        ):
            with pytest.raises(RuntimeError, match="another event loop"):
                await operation()

    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "load_agent_transcript_header", forbidden)
            patch.setattr(module, "AgentTranscriptSessionCatalog", forbidden)
            patch.setattr(selected, "_resolve_binding_input", forbidden)
            asyncio.run(wrong_loop())
        original.run_until_complete(selected.close())
        assert not selected.pending_preparations
    finally:
        original.close()


def test_close_continues_after_first_cleanup_failure(tmp_path, monkeypatch):
    async def scenario():
        runtime = _runtime("coding")

        async def fail_binding(context, profile, owner):
            await runtime.bind_lifecycle_owned(context, profile, owner)
            raise ValueError("test failed construction")

        selected = factory(runtime=runtime, bind=fail_binding)
        dispose = runtime._binder.dispose
        bindings, closed = [], []
        fail_all = True
        fail_first = True

        async def sometimes(binding):
            if binding not in bindings:
                bindings.append(binding)
            if fail_all or (fail_first and binding is bindings[0]):
                raise OSError("test selected cleanup failure")
            await dispose(binding)
            closed.append(binding)

        with monkeypatch.context() as patch:
            patch.setattr(runtime._binder, "dispose", sometimes)
            for name in ("one", "two"):
                with pytest.raises(ValueError, match="failed construction"):
                    await new(selected, tmp_path, name)
            first, second = selected.pending_preparations
            fail_all = False
            with pytest.raises(OSError, match="selected cleanup failure"):
                await selected.close()
            assert selected.pending_preparations == (first,)
            assert first.cleanup_pending and not second.cleanup_pending
            assert closed == [bindings[1]]
            fail_first = False
            await selected.close()
            assert closed == [bindings[1], bindings[0]]
            assert not selected.pending_preparations

    asyncio.run(scenario())


@pytest.mark.parametrize("cache", ["missing", "corrupt"])
def test_recent_discovery_does_not_rebuild_cache_before_busy_admission(tmp_path, cache):
    async def scenario():
        first_factory, second = factory(), factory()
        first = await new(first_factory, tmp_path)
        await ProductTranscriptSession(lifecycle_session=first).append_message(message())
        index = tmp_path / ".session-index.json"
        if cache == "missing":
            index.unlink(missing_ok=True)
        else:
            index.write_bytes(b"broken index")
        before = tree(tmp_path)
        try:
            with pytest.raises(TranscriptWriterError, match="busy"):
                await second.continue_recent(session_dir=tmp_path, cwd="/workspace")
            assert tree(tmp_path) == before
            assert not second.pending_preparations
        finally:
            await first.dispose()
            await first_factory.close()
            await second.close()

    asyncio.run(scenario())
