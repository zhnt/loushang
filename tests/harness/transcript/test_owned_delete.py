from __future__ import annotations

import asyncio
import sys
import threading
from contextlib import contextmanager
from dataclasses import replace

import pytest

from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.conversation import StoreCommitOutcomeUnknown
from loushang.harness.conversation.stores import file as file_module
from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.transcript import ProductTranscriptSession
from loushang.harness.transcript.session_factory import TranscriptDeletionCleanupPending
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_owned_session_factory import factory, new
from .test_runtime_profile import _runtime
from .test_writer_images import message
from .test_writer_io import wait_until
from .test_writer_lifecycle import assert_available, assert_busy
from .test_writer_root_binding import tree

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux retained deletion")


@pytest.fixture
def tmp_path(tmp_path_factory):
    # Blobs are siblings of Session roots. Isolate the full data root, not just
    # transcripts, so equal logical Session IDs in separate tests do not share a manifest.
    root = tmp_path_factory.mktemp("owned-delete") / "sessions"
    root.mkdir(mode=0o700)
    return root


async def saved(root):
    creator = factory()
    session = await new(creator, root, "conversation-1")
    await ProductTranscriptSession(lifecycle_session=session).append_message(message())
    return creator, session


def retained_image(root):
    store = SessionBlobStore(root.parent, "conversation-1")
    reference, = store.records
    assert store.read_bytes(reference) == b"hello"
    return reference, store.manifest_path.read_bytes()


def test_active_writer_blocks_delete_then_close_allows_delete(tmp_path):
    async def scenario():
        creator, active = await saved(tmp_path)
        owner = factory()
        path = active.context.session_file
        try:
            before = tree(tmp_path)
            with pytest.raises(TranscriptWriterError, match="busy"):
                await owner.delete_transcript(path)
            assert tree(tmp_path) == before and not owner.pending_preparations
            await active.dispose()
            reference = retained_image(tmp_path)
            assert await owner.delete_transcript(path)
            assert retained_image(tmp_path) == reference
            assert not path.exists() and not owner.pending_preparations
            assert not await owner.delete_transcript(path)
            assert_available(tmp_path)
        finally:
            await active.dispose()
            await creator.close()
            await owner.close()

    asyncio.run(scenario())


def test_active_path_guard_and_missing_target_do_not_create_storage(tmp_path):
    async def scenario():
        owner = factory()
        path = tmp_path / "absent" / "session.jsonl"
        before = tree(tmp_path)
        try:
            with pytest.raises(ValueError, match="currently active"):
                await owner.delete_transcript(path, current_session_file=path)
            assert not await owner.delete_transcript(path)
            assert tree(tmp_path) == before and not owner.pending_preparations
        finally:
            await owner.close()

    asyncio.run(scenario())


def test_delete_cleanup_failure_retains_original_writer_after_file_is_gone(tmp_path, monkeypatch):
    async def scenario():
        creator, active = await saved(tmp_path)
        path = active.context.session_file
        await active.dispose()
        await creator.close()
        runtime = _runtime("coding")
        owner = factory(runtime=runtime)

        async def fail(binding):
            raise OSError("runtime cleanup unavailable")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(runtime._binder, "dispose", fail)
                with pytest.raises(TranscriptDeletionCleanupPending) as failure:
                    await owner.delete_transcript(path)
                assert failure.value.receipt.revision == 1
                assert isinstance(failure.value.__cause__, OSError)
                assert not path.exists()
                retained_image(tmp_path)
                retained, = owner.pending_preparations
                assert retained.cleanup_pending
                assert_busy(tmp_path)
                assert not await owner.delete_transcript(path)
                assert owner.pending_preparations == (retained,)
                assert retained.cleanup_pending
                assert_busy(tmp_path)
                with pytest.raises(OSError, match="runtime cleanup unavailable"):
                    await owner.close()
                assert owner.pending_preparations == (retained,)
                assert_busy(tmp_path)
            await owner.close()
            assert not owner.pending_preparations
            assert_available(tmp_path)
        finally:
            await owner.close()

    asyncio.run(scenario())


def test_cancel_during_native_delete_and_factory_close_join_original_owner(tmp_path, monkeypatch):
    async def scenario():
        creator, active = await saved(tmp_path)
        path = active.context.session_file
        await active.dispose()
        await creator.close()
        owner = factory()
        entered, release = threading.Event(), threading.Event()
        delete = file_module.FileConversationStore._delete_sync

        def paused(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            return delete(*args, **kwargs)

        monkeypatch.setattr(file_module.FileConversationStore, "_delete_sync", paused)
        caller = asyncio.create_task(owner.delete_transcript(path))
        closing = None
        try:
            await wait_until(entered.is_set)
            retained, = owner.pending_preparations
            caller.cancel()
            closing = asyncio.create_task(owner.close())
            await wait_until(lambda: owner._closing)
            assert not closing.done() and retained.cleanup_pending
            assert_busy(tmp_path)
            release.set()
            results = await asyncio.wait_for(asyncio.gather(caller, closing, return_exceptions=True), 10)
            assert isinstance(results[0], asyncio.CancelledError) and results[1] is None
            assert not owner.pending_preparations and not retained.cleanup_pending
            assert not path.exists()
            assert_available(tmp_path)
        finally:
            release.set()
            await asyncio.gather(caller, *([closing] if closing else []), return_exceptions=True)
            await owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_point", ["binding_exit", "tombstone_receipt"])
def test_actual_delete_commit_boundary_preserves_unknown(tmp_path, monkeypatch, failure_point):
    async def scenario():
        creator, active = await saved(tmp_path)
        path = active.context.session_file
        await active.dispose()
        await creator.close()
        owner = factory()
        bind = RootedFileIO.bind
        write = file_module._write_tombstone
        failure = OSError("lost deletion receipt")

        @contextmanager
        def fail_exit(io, selected, **kwargs):
            with bind(io, selected, **kwargs) as value:
                yield value
            if selected.name.endswith(".deleted.json") and kwargs.get("create_parent"):
                raise failure

        def fail_tombstone(*args, **kwargs):
            write(*args, **kwargs)
            raise failure

        try:
            with monkeypatch.context() as patch:
                if failure_point == "binding_exit":
                    patch.setattr(RootedFileIO, "bind", fail_exit)
                else:
                    patch.setattr(file_module, "_write_tombstone", fail_tombstone)
                with pytest.raises(StoreCommitOutcomeUnknown) as result:
                    await owner.delete_transcript(path)
                assert result.value.__cause__ is failure
            assert bool(tuple(tmp_path.glob(".conversation-identities/*.deleted.json")))
            assert path.exists() is (failure_point == "tombstone_receipt")
            retained_image(tmp_path)
            assert not owner.pending_preparations
            assert_available(tmp_path)
        finally:
            await owner.close()

    asyncio.run(scenario())


def test_original_unknown_survives_disposal_failure(tmp_path, monkeypatch):
    async def scenario():
        creator, active = await saved(tmp_path)
        path = active.context.session_file
        await active.dispose()
        await creator.close()
        runtime = _runtime("coding")
        owner = factory(runtime=runtime)
        delete = file_module.FileConversationStore._delete_sync
        failure = StoreCommitOutcomeUnknown("test unknown deletion")

        def uncertain(*args, **kwargs):
            delete(*args, **kwargs)
            raise failure

        async def dispose(binding):
            raise OSError("cleanup pending")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(file_module.FileConversationStore, "_delete_sync", uncertain)
                patch.setattr(runtime._binder, "dispose", dispose)
                with pytest.raises(StoreCommitOutcomeUnknown) as result:
                    await owner.delete_transcript(path)
                assert result.value is failure
                assert "cleanup retained" in failure.__notes__[0]
                assert not path.exists() and owner.pending_preparations
                retained_image(tmp_path)
                assert_busy(tmp_path)
            await owner.close()
            assert_available(tmp_path)
        finally:
            await owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["none", "revision", "operation"])
def test_actual_delete_with_mismatched_receipt_is_not_claimed_committed(tmp_path, monkeypatch, invalid):
    async def scenario():
        creator, active = await saved(tmp_path)
        path = active.context.session_file
        await active.dispose()
        await creator.close()
        owner = factory()
        delete = file_module.FileConversationStore._delete_sync

        def corrupt_receipt(*args, **kwargs):
            receipt = delete(*args, **kwargs)
            return {
                "none": None,
                "revision": replace(receipt, revision=receipt.revision + 1),
                "operation": replace(receipt, operation_id="another-operation"),
            }[invalid]

        try:
            monkeypatch.setattr(file_module.FileConversationStore, "_delete_sync", corrupt_receipt)
            with pytest.raises(StoreCommitOutcomeUnknown, match="receipt does not match"):
                await owner.delete_transcript(path)
            assert not path.exists() and not owner.pending_preparations
            retained_image(tmp_path)
            assert_available(tmp_path)
        finally:
            await owner.close()

    asyncio.run(scenario())
