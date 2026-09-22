from __future__ import annotations

import asyncio
import sys
import threading

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.conversation import StoreCommitOutcomeUnknown
from loushang.harness.conversation.stores import file as file_module
from loushang.harness.transcript import ProductTranscriptSession
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_owned_session_factory import factory, new
from .test_runtime_profile import _runtime
from .test_writer_images import message
from .test_writer_io import wait_until
from .test_writer_root_binding import tree

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned fork")


async def source_session(tmp_path, *, images=True):
    root = tmp_path / "sessions"
    root.mkdir(mode=0o700)
    selected = factory()
    source = await new(selected, root)
    await ProductTranscriptSession(lifecycle_session=source).append_message(
        message() if images else UserMessage(role="user", content="hello", timestamp=1.0)
    )
    return selected, source


@pytest.mark.parametrize("images", [False, True])
def test_live_owned_fork_selected_path_and_source_remains_usable(tmp_path, images):
    async def scenario():
        selected, source = await source_session(tmp_path, images=images)
        leaf = source.transcript.leaf_id
        before = source.transcript.records
        await ProductTranscriptSession(lifecycle_session=source).append_message(
            UserMessage(role="user", content="not selected", timestamp=2.0)
        )
        target = await selected.fork(source, leaf_id=leaf, binding_input=selected._resolve_binding_input(True))
        try:
            assert target.transcript.leaf_id == leaf
            assert [r.record_id for r in target.transcript.records] == [r.record_id for r in before]
            assert len(source.transcript.records) == len(before) + 1
            assert source.ownership_state == "root_owned" and not source._writer_owner.closing
            assert target.context.header.parent_conversation_id == source.context.header.conversation_id
            assert not selected.pending_preparations
            if images:
                ref = target.session_blob_health[0].reference
                assert ref.session_id == target.context.header.conversation_id
                assert target.session_blob_health[0].state == "available"
                assert ProductTranscriptSession(lifecycle_session=target).build_session_context().messages[0].content[0].data == "aGVsbG8="
                assert source.transcript.records[0].payload.content[0].blob.session_id == "conversation-1"
        finally:
            await target.dispose()
            await source.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_fork_from_busy_source_has_no_target_effects_then_copies_after_close(tmp_path):
    async def scenario():
        first, source = await source_session(tmp_path)
        selected = factory()
        target_root = tmp_path / "target"
        target_root.mkdir(mode=0o700)
        before = tree(target_root)
        with pytest.raises(TranscriptWriterError, match="busy"):
            await selected.fork_from(source.context.session_file, session_dir=target_root, target_cwd="/other")
        assert tree(target_root) == before and not selected.pending_preparations
        await source.dispose()
        target = await selected.fork_from(source.context.session_file, session_dir=target_root, target_cwd="/other")
        try:
            assert target.context.cwd == "/other"
            assert target.session_blob_health[0].state == "available"
            assert not selected.pending_preparations
            reopened = await first.open(source.context.session_file)
            await reopened.dispose()
        finally:
            await target.dispose()
            await first.close()
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["cleanup", "cancel"])
def test_internal_source_cleanup_debt_prevents_any_target_creation(tmp_path, monkeypatch, failure):
    async def scenario():
        first, source = await source_session(tmp_path)
        await source.dispose()
        await first.close()
        runtime = _runtime("coding")
        selected = factory(runtime=runtime)
        entered, release = asyncio.Event(), asyncio.Event()
        dispose = runtime._binder.dispose
        targets = []

        async def faulty(binding):
            entered.set()
            if failure == "cleanup":
                raise OSError("source cleanup unavailable")
            await release.wait()
            await dispose(binding)

        def forbidden(*args, **kwargs):
            targets.append(True)
            raise AssertionError("target must not start before source cleanup")

        with monkeypatch.context() as patch:
            patch.setattr(runtime._binder, "dispose", faulty)
            patch.setattr(selected, "_create", forbidden)
            caller = asyncio.create_task(selected.fork_from(
                source.context.session_file, session_dir=source.context.session_dir, target_cwd="/other",
            ))
            await asyncio.wait_for(entered.wait(), 5)
            owner, = selected.pending_preparations
            if failure == "cancel":
                caller.cancel()
            with pytest.raises(OSError if failure == "cleanup" else asyncio.CancelledError):
                await caller
            assert selected.pending_preparations == (owner,) and owner.cleanup_pending
            assert not targets
        release.set()
        await selected.close()
        assert not selected.pending_preparations and not targets

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["closed", "unowned", "no_blobs", "missing", "corrupt", "bad_leaf"])
def test_invalid_source_never_acquires_target(tmp_path, monkeypatch, failure):
    async def scenario():
        selected, source = await source_session(tmp_path)
        owner = source._writer_owner
        port = owner._blob_file_io
        leaf = source.transcript.leaf_id
        if failure == "closed":
            await source.dispose()
        elif failure == "unowned":
            source._writer_owner = None
        elif failure == "no_blobs":
            owner._blob_file_io = None
        elif failure == "bad_leaf":
            leaf = "does-not-exist"
        elif failure in {"missing", "corrupt"}:
            ref = source.transcript.records[0].payload.content[0].blob
            path = tmp_path / "session-assets/conversation-1/objects" / ref.blob_id
            if failure == "missing":
                path.unlink()
            else:
                path.write_bytes(b"wrong")

        def forbidden(*args, **kwargs):
            raise AssertionError("invalid source started target construction")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(selected, "_construct_owned", forbidden)
                with pytest.raises((ValueError, OSError, TranscriptWriterError)):
                    await selected.fork(source, leaf_id=leaf, binding_input=selected._resolve_binding_input(True))
            assert not selected.pending_preparations
        finally:
            source._writer_owner = owner
            owner._blob_file_io = port
            await source.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_graph_owned_source_fork_does_not_transfer_or_dispose_source(tmp_path):
    async def scenario():
        selected, source = await source_session(tmp_path)
        source._begin_graph_construction()
        source._commit_graph_ownership()
        target = await selected.fork(
            source, leaf_id=source.transcript.leaf_id, binding_input=selected._resolve_binding_input(True),
        )
        try:
            assert source.ownership_state == "graph_owned"
            await selected.close()
            assert not source._writer_owner.closing and not target._writer_owner.closing
            await ProductTranscriptSession(lifecycle_session=source).append_message(message())
        finally:
            await target.dispose()
            await source._dispose_graph_owned()

    asyncio.run(scenario())


def test_foreign_loop_source_rejected_before_target(tmp_path, monkeypatch):
    async def scenario():
        selected, source = await source_session(tmp_path)

        def other_loop():
            async def attempt():
                other = factory()

                def forbidden(*args, **kwargs):
                    raise AssertionError("wrong-loop source started target")

                monkeypatch.setattr(other, "_construct_owned", forbidden)
                try:
                    with pytest.raises(TranscriptWriterError):
                        await other.fork(source, leaf_id=source.transcript.leaf_id, binding_input=None)
                finally:
                    await other.close()
            asyncio.run(attempt())

        try:
            await asyncio.to_thread(other_loop)
            assert not source._writer_owner.closing
        finally:
            await source.dispose()
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["before_create", "unknown_commit"])
def test_target_failure_preserves_source_and_uses_existing_publication_rules(tmp_path, monkeypatch, failure):
    async def scenario():
        first, source = await source_session(tmp_path)
        runtime = _runtime("coding")

        async def binding(context, profile, owner):
            result = await runtime.bind_lifecycle_owned(context, profile, owner)
            if failure == "before_create":
                raise ValueError("target binding failed")
            return result

        selected = factory(runtime=runtime, bind=binding)
        selected._conversation_id_factory = lambda: "fork-target"
        write = file_module._write_unlocked

        def committed_then_failed(*args, **kwargs):
            write(*args, **kwargs)
            raise OSError("target commit receipt lost")

        try:
            with monkeypatch.context() as patch:
                if failure == "unknown_commit":
                    patch.setattr(file_module, "_write_unlocked", committed_then_failed)
                with pytest.raises(StoreCommitOutcomeUnknown if failure == "unknown_commit" else ValueError):
                    await selected.fork(source, leaf_id=source.transcript.leaf_id, binding_input=runtime.resolve(persist=True))
            assert not source._writer_owner.closing and not selected.pending_preparations
            assert (tmp_path / "session-assets/fork-target").exists() == (failure == "unknown_commit")
            if failure == "unknown_commit":
                restored = await selected.open(source.context.session_dir / "fork-target.jsonl")
                assert restored.session_blob_health[0].state == "available"
                await restored.dispose()
            await ProductTranscriptSession(lifecycle_session=source).append_message(message())
        finally:
            await source.dispose()
            await first.close()
            await selected.close()

    asyncio.run(scenario())


def test_factory_close_during_source_settlement_never_starts_target(tmp_path, monkeypatch):
    async def scenario():
        first, source = await source_session(tmp_path)
        await source.dispose()
        await first.close()
        runtime = _runtime("coding")
        selected = factory(runtime=runtime)
        entered, release = asyncio.Event(), asyncio.Event()
        dispose = runtime._binder.dispose

        async def delayed(binding):
            entered.set()
            await release.wait()
            await dispose(binding)

        monkeypatch.setattr(runtime._binder, "dispose", delayed)
        caller = asyncio.create_task(selected.fork_from(
            source.context.session_file, session_dir=tmp_path / "must-not-exist", target_cwd="/other",
        ))
        closer = None
        try:
            await asyncio.wait_for(entered.wait(), 5)
            closer = asyncio.create_task(selected.close())
            await asyncio.sleep(0)
            assert selected._closing
            release.set()
            with pytest.raises(RuntimeError, match="closed"):
                await caller
            await closer
            assert not (tmp_path / "must-not-exist").exists() and not selected.pending_preparations
        finally:
            release.set()
            await asyncio.gather(caller, *([closer] if closer else []), return_exceptions=True)
            await selected.close()

    asyncio.run(scenario())


def test_frozen_source_not_reread_after_target_admission(tmp_path, monkeypatch):
    async def scenario():
        selected, source = await source_session(tmp_path)
        runtime = _runtime("coding")
        entered, release = threading.Event(), threading.Event()
        target_factory = factory(runtime=runtime)
        prepare = target_factory._prepare_owned

        def paused_prepare(*args, **kwargs):
            owner = prepare(*args, **kwargs)
            acquire = owner._acquire_blob_writer

            def delayed_acquisition_receipt():
                acquire()
                entered.set()
                assert release.wait(5)

            owner._acquire_blob_writer = delayed_acquisition_receipt
            return owner

        monkeypatch.setattr(target_factory, "_prepare_owned", paused_prepare)
        task = asyncio.create_task(target_factory.fork(
            source, leaf_id=source.transcript.leaf_id, binding_input=runtime.resolve(persist=True),
        ))
        target = None
        try:
            await wait_until(entered.is_set)
            owner, = target_factory.pending_preparations
            assert owner._publication is None
            assert not (tmp_path / "session-assets" / owner._context.header.conversation_id).exists()
            await source.dispose()
            authority = tmp_path / "session-assets/conversation-1"
            authority.rename(authority.with_name("source-moved"))
            release.set()
            target = await task
            assert target.session_blob_health[0].state == "available"
            assert ProductTranscriptSession(lifecycle_session=target).build_session_context().messages[0].content[0].data == "aGVsbG8="
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            if target is not None:
                await target.dispose()
            await source.dispose()
            await target_factory.close()
            await selected.close()

    asyncio.run(scenario())
