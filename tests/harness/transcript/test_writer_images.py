from __future__ import annotations

import asyncio
import sys
import threading
from dataclasses import replace

import pytest

from loushang.ai.types import ImagePart, UserMessage
from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.conversation import StoreCommitOutcomeUnknown
from loushang.harness.transcript import ApplicationMessage, ProductTranscriptSession
from loushang.harness.transcript import product_session as product_module
from loushang.harness.transcript.jsonl_file import load_agent_transcript_file
from loushang.harness.transcript.session_artifacts import (
    collect_agent_transcript_session_blobs,
)
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_lifecycle import _record
from .test_runtime_profile import _runtime
from .test_writer_io import wait_until
from .test_writer_lifecycle import assert_available, assert_busy
from .test_writer_runtime import prepare as prepare_runtime

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux writer")


def prepare(*args, **kwargs):
    return prepare_runtime(*args, manage_blobs=True, **kwargs)


@pytest.fixture
def session_root(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir(mode=0o700)
    return root


def message(application=False):
    content = [ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")]
    if application:
        return ApplicationMessage(
            application_message_id="image-one", custom_type="test", content=content,
            timestamp=1.0,
        )
    return UserMessage(role="user", content=content, timestamp=1.0)


def submit(session, entry):
    if entry == "application":
        return session.commit_application_message(message(True))
    return session.append_message(message(entry == "forwarded"))


@pytest.mark.parametrize("entry", ["user", "application", "forwarded"])
def test_closed_session_rejects_before_blob_store_construction(session_root, monkeypatch, entry):
    tmp_path = session_root
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        session = ProductTranscriptSession(lifecycle_session=await owner.create())
        await owner.dispose()

        def forbidden(*args, **kwargs):
            raise AssertionError("closed session reached blob storage")

        monkeypatch.setattr(product_module, "SessionBlobStore", forbidden)
        with pytest.raises(TranscriptWriterError, match="closed"):
            await submit(session, entry)
        assert_available(tmp_path)

    asyncio.run(scenario())


@pytest.mark.parametrize("entry", ["user", "application"])
def test_unknown_commit_then_close_preserves_published_images(session_root, monkeypatch, entry):
    tmp_path = session_root
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(tmp_path, runtime, runtime.bind_lifecycle_owned)
        lifecycle = await owner.create()
        session = ProductTranscriptSession(lifecycle_session=lifecycle)
        store = lifecycle.runtime_binding.store
        append = store.append
        committed, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def uncertain(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = await append(*args, **kwargs)
            if calls == 1:
                committed.set()
                await release.wait()
                raise StoreCommitOutcomeUnknown("test reply lost after durable append")
            return result

        monkeypatch.setattr(store, "append", uncertain)
        operation = asyncio.create_task(submit(session, entry))
        await wait_until(committed.is_set)
        closing = asyncio.create_task(owner.dispose())
        await wait_until(lambda: owner.closing)
        assert_busy(tmp_path)
        release.set()
        with pytest.raises(StoreCommitOutcomeUnknown):
            await operation
        await closing
        header, records = load_agent_transcript_file(tmp_path / "session.jsonl")
        references = collect_agent_transcript_session_blobs(
            records, expected_session_id=header.conversation_id,
        )
        assert len(references) == 1 and calls == 2
        blobs = SessionBlobStore(tmp_path.parent, header.conversation_id)
        assert blobs.read_bytes(references[0]) == b"hello"
        assert_available(tmp_path)

    asyncio.run(scenario())


@pytest.mark.parametrize("entry", ["user", "application"])
@pytest.mark.parametrize("cancel", [False, True])
def test_image_publication_waiting_for_commit_drains_rollback(session_root, monkeypatch, entry, cancel):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(session_root, runtime, runtime.bind_lifecycle_owned)
        lifecycle = await owner.create()
        session = ProductTranscriptSession(lifecycle_session=lifecycle)
        lock = lifecycle.transcript._commit_lock
        await lock.acquire()
        published = asyncio.Event()
        externalize = product_module.externalize_session_message_images
        rollback = product_module.rollback_externalized_session_images
        publications = []
        rolled_back = []

        def publish(*args, **kwargs):
            result = externalize(*args, **kwargs)
            publications.append(result.publication)
            published.set()
            return result

        def undo(*args, **kwargs):
            assert owner._active_io == 1
            assert_busy(session_root)
            rollback(*args, **kwargs)
            rolled_back.append(True)

        monkeypatch.setattr(product_module, "externalize_session_message_images", publish)
        monkeypatch.setattr(product_module, "rollback_externalized_session_images", undo)
        operation = asyncio.create_task(submit(session, entry))
        try:
            await wait_until(published.is_set)
            closing = asyncio.create_task(owner.dispose())
            await wait_until(lambda: owner.closing)
            assert_busy(session_root)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            rejoin = asyncio.create_task(owner.dispose())
            if cancel:
                operation.cancel()
                operation.cancel()
            else:
                lock.release()
            with pytest.raises(asyncio.CancelledError if cancel else TranscriptWriterError):
                await operation
            await rejoin
            assert len(publications) == 1 and publications[0] is not None
            assert rolled_back == [True]
            _, records = load_agent_transcript_file(session_root / "session.jsonl")
            assert records == []
            assert not (session_root.parent / "session-assets" / "conversation-1").exists()
            assert_available(session_root)
        finally:
            if lock.locked():
                lock.release()

    asyncio.run(scenario())


@pytest.mark.parametrize("entry", ["user", "application"])
def test_native_commit_wins_cancellation_without_deleting_images(session_root, monkeypatch, entry):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(session_root, runtime, runtime.bind_lifecycle_owned)
        lifecycle = await owner.create()
        session = ProductTranscriptSession(lifecycle_session=lifecycle)
        store = lifecycle.runtime_binding.store
        entered, release = threading.Event(), threading.Event()
        append = store._append_sync

        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return append(*args, **kwargs)

        monkeypatch.setattr(store, "_append_sync", blocked)
        operation = asyncio.create_task(submit(session, entry))
        try:
            await wait_until(entered.is_set)
            closing = asyncio.create_task(owner.dispose())
            await wait_until(lambda: owner.closing)
            operation.cancel()
            operation.cancel()
            assert_busy(session_root)
            release.set()
            assert await operation
            await closing
            assert_durable_image(session_root)
            assert_available(session_root)
        finally:
            release.set()

    asyncio.run(scenario())


def assert_durable_image(root):
    header, records = load_agent_transcript_file(root / "session.jsonl")
    references = collect_agent_transcript_session_blobs(
        records, expected_session_id=header.conversation_id,
    )
    assert len(records) == len(references) == 1
    assert SessionBlobStore(root.parent, header.conversation_id).read_bytes(references[0]) == b"hello"


@pytest.mark.parametrize("entry", ["user", "application"])
def test_observer_failure_does_not_rollback_committed_images(session_root, entry):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(session_root, runtime, runtime.bind_lifecycle_owned)
        session = ProductTranscriptSession(lifecycle_session=await owner.create())

        def failed_observer(result):
            raise ValueError("test observer failed after commit")

        session.set_commit_observer(failed_observer)
        with pytest.raises(ValueError, match="test observer") as caught:
            await submit(session, entry)
        assert any("images retained" in note for note in caught.value.__notes__)
        assert_durable_image(session_root)
        await owner.dispose()
        assert_available(session_root)

    asyncio.run(scenario())


def test_graph_owner_allows_image_commit_and_application_replay(session_root):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(session_root, runtime, runtime.bind_lifecycle_owned)
        lifecycle = await owner.create()
        session = ProductTranscriptSession(lifecycle_session=lifecycle)
        lifecycle._begin_graph_construction()
        lifecycle._commit_graph_ownership()
        await owner.dispose()
        assert not owner.closing
        first = await submit(session, "application")
        repeated = await submit(session, "application")
        assert first.record_id == repeated.record_id
        assert repeated.disposition == "already_committed"
        assert_durable_image(session_root)
        assert_busy(session_root)
        await lifecycle._dispose_graph_owned()
        assert_available(session_root)
        with pytest.raises(TranscriptWriterError, match="closed"):
            await submit(session, "application")

    asyncio.run(scenario())


@pytest.mark.parametrize("entry", ["user", "application"])
@pytest.mark.parametrize("recovery", ["revision", "record_id", "materialize"])
def test_unknown_remains_until_recovery_receipt_is_valid(session_root, monkeypatch, entry, recovery):
    async def scenario():
        runtime = _runtime("coding")
        materialize = recovery == "materialize"
        owner, _ = prepare(
            session_root, runtime, runtime.bind_lifecycle_owned,
            defer_materialization=materialize,
        )
        lifecycle = await owner.create()
        session = ProductTranscriptSession(lifecycle_session=lifecycle)
        store = lifecycle.runtime_binding.store
        original = store.create if materialize else store.append
        unknown = StoreCommitOutcomeUnknown("test durable result lost")
        calls = 0

        async def uncertain(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = await original(*args, **kwargs)
            if calls == 1:
                raise unknown
            receipt = replace(
                result.receipt,
                **({"revision": 99} if recovery == "revision" else {"record_id": "wrong"}),
            )
            return replace(result, receipt=receipt)

        if materialize:
            load = store.load

            async def invalid_snapshot(*args, **kwargs):
                result = await load(*args, **kwargs)
                return replace(result, snapshot=replace(result.snapshot, revision=99))

            monkeypatch.setattr(store, "create", uncertain)
            monkeypatch.setattr(store, "load", invalid_snapshot)
        else:
            monkeypatch.setattr(store, "append", uncertain)
        with pytest.raises(StoreCommitOutcomeUnknown) as caught:
            await submit(session, entry)
        assert caught.value is unknown
        assert_durable_image(session_root)
        await owner.dispose()
        assert_available(session_root)

    asyncio.run(scenario())


@pytest.mark.parametrize("recovery", ["size", "revision", "record_id", "rejected"])
def test_batch_uncertainty_survives_invalid_recovery(session_root, monkeypatch, recovery):
    async def scenario():
        runtime = _runtime("coding")
        owner, _ = prepare(session_root, runtime, runtime.bind_lifecycle_owned)
        lifecycle = await owner.create()
        store = lifecycle.runtime_binding.store
        append = store.append_batch
        unknown = StoreCommitOutcomeUnknown("test batch result lost")
        calls = 0

        async def uncertain(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2 and recovery == "rejected":
                raise TranscriptWriterError("closed")
            result = await append(*args, **kwargs)
            if calls == 1:
                raise unknown
            receipts = result.receipts
            if recovery == "size":
                receipts = ()
            else:
                change = {"revision": 99} if recovery == "revision" else {"record_id": "wrong"}
                receipts = (replace(receipts[0], **change), *receipts[1:])
            return replace(result, receipts=receipts)

        monkeypatch.setattr(store, "append_batch", uncertain)
        records = [_record("one"), _record("two", parent_id="one")]
        with pytest.raises(StoreCommitOutcomeUnknown) as caught:
            await lifecycle.transcript.commit_batch(records)
        assert caught.value is unknown and calls == 2
        _, durable = load_agent_transcript_file(session_root / "session.jsonl")
        assert durable == records
        await owner.dispose()
        assert_available(session_root)

    asyncio.run(scenario())
