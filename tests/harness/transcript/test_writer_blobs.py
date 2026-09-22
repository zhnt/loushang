from __future__ import annotations

import asyncio
import os
import sys
import threading

import pytest

from loushang.harness.artifacts._writer_lease import (
    SessionBlobWriterError,
    SessionBlobWriterLease,
)
from loushang.harness.journal import _directory_lease as lease_module
from loushang.harness.transcript import AgentTranscriptLifecycle
from loushang.harness.transcript.writer_lease import TranscriptWriterLease

from .test_lifecycle import _header
from .test_runtime_profile import _runtime
from .test_writer_io import wait_until
from .test_writer_lifecycle import assert_available, assert_busy

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux joint writer")


def prepare(root, bind=None):
    runtime = _runtime("coding")
    lifecycle = AgentTranscriptLifecycle(
        bind_runtime=runtime.bind_lifecycle,
        bind_runtime_owned=bind or runtime.bind_lifecycle_owned,
    )
    context = lifecycle.new_context(
        session_dir=root, cwd="/workspace", persist=True,
        header=_header(), session_file=root / "session.jsonl",
    )
    writer = TranscriptWriterLease(root, "coding", context.header.conversation_id)
    writer.acquire()
    owner = lifecycle.prepare_writer(
        context, runtime.resolve(persist=True), writer=writer, product_id="coding",
        defer_materialization=False, manage_blobs=True,
    )
    return owner, writer


def blob_busy(root):
    other = SessionBlobWriterLease(root.parent, "work", _header().conversation_id)
    try:
        with pytest.raises(SessionBlobWriterError, match="busy"):
            other.acquire()
    finally:
        other.close()


@pytest.fixture
def root(tmp_path):
    value = tmp_path / "sessions"
    value.mkdir(mode=0o700)
    return value


def test_sibling_transcripts_contend_before_second_runtime_binding(root):
    async def scenario():
        first, _ = prepare(root)
        assert first._blob_writer is not None and not first._blob_writer.cleanup_pending
        assert not (root.parent / ".session-blob-writers").exists()
        await first.create()
        sibling = root.parent / "other-sessions"
        sibling.mkdir(mode=0o700)
        calls = []

        async def forbidden(*args):
            calls.append(args)
            raise AssertionError("busy blob authority reached runtime binding")

        second, _ = prepare(sibling, forbidden)
        try:
            with pytest.raises(SessionBlobWriterError, match="busy"):
                await second.create()
            driver = second._driver
            with pytest.raises(SessionBlobWriterError, match="busy"):
                await second.create()
            assert second._driver is driver and not calls
            assert not (sibling / "session.jsonl").exists()
            assert_busy(root)
            assert_busy(sibling)
            blob_busy(root)
            await second.dispose()
            assert_available(sibling)
            blob_busy(root)
        finally:
            await first.dispose()
        assert_available(root)
        third, _ = prepare(sibling)
        await third.create()
        await third.dispose()

    asyncio.run(scenario())


def test_cancel_during_second_native_acquire_retains_original_driver(root, monkeypatch):
    async def scenario():
        owner, _ = prepare(root)
        entered, release = threading.Event(), threading.Event()
        acquire = owner._blob_writer.acquire

        def blocked():
            entered.set()
            assert release.wait(5)
            acquire()

        monkeypatch.setattr(owner._blob_writer, "acquire", blocked)
        creating = asyncio.create_task(owner.create())
        try:
            await wait_until(entered.is_set)
            driver = owner._driver
            creating.cancel()
            with pytest.raises(asyncio.CancelledError):
                await creating
            closing = asyncio.create_task(owner.dispose())
            await wait_until(lambda: owner.closing)
            assert not driver.done() and owner.cleanup_pending
            assert_busy(root)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            rejoin = asyncio.create_task(owner.dispose())
            release.set()
            await rejoin
            assert owner._driver is driver and not owner.cleanup_pending
            assert_available(root)
            other = SessionBlobWriterLease(root.parent, "work", _header().conversation_id)
            try:
                other.acquire()
            finally:
                other.close()
        finally:
            release.set()

    asyncio.run(scenario())


def test_scope_checks_blob_binding_before_actual_store_io(root, monkeypatch):
    async def scenario():
        owner, _ = prepare(root)
        session = await owner.create()
        directory = root.parent / ".session-blob-writers"
        directory.rename(directory.with_name(directory.name + ".saved"))
        directory.mkdir(mode=0o700)

        def forbidden(*args, **kwargs):
            raise AssertionError("invalid blob binding reached Store IO")

        monkeypatch.setattr(session.runtime_binding.store, "_load_sync", forbidden)
        with pytest.raises(SessionBlobWriterError, match="conflict"):
            await session.runtime_binding.store.load(session.runtime_binding.key)
        assert owner._active_io == 0
        await owner.dispose()
        assert_available(root)

    asyncio.run(scenario())


def test_successful_blob_close_is_not_repeated_when_transcript_close_retries(root, monkeypatch):
    async def scenario():
        owner, writer = prepare(root)
        await owner.create()
        events = []
        blob_close = owner._close_blob_writer
        transcript_close = writer._close_claimed

        def close_blob():
            events.append("blob")
            blob_close()

        def close_transcript(value):
            events.append("transcript")
            if events.count("transcript") == 1:
                raise RuntimeError("test before native close")
            transcript_close(value)

        monkeypatch.setattr(owner, "_close_blob_writer", close_blob)
        monkeypatch.setattr(writer, "_close_claimed", close_transcript)
        with pytest.raises(RuntimeError, match="before native"):
            await owner.dispose()
        assert_busy(root)
        await owner.dispose()
        await owner.dispose()
        assert events == ["blob", "transcript", "transcript"]
        assert not owner.cleanup_pending
        assert_available(root)

    asyncio.run(scenario())


def test_unknown_blob_close_keeps_transcript_lock_and_never_closes_reused_fd(root, monkeypatch):
    async def scenario():
        owner, writer = prepare(root)
        await owner.create()
        fd = owner._blob_writer._fds["lock"]
        native_close = os.close
        replacements, calls = [], []

        def failed_close(descriptor):
            calls.append(descriptor)
            native_close(descriptor)
            if descriptor == fd:
                replacement = os.open("/dev/null", os.O_RDONLY)
                assert replacement == fd
                replacements.append(replacement)
                raise OSError("test close receipt lost")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(lease_module.os, "close", failed_close)
                for _ in range(2):
                    with pytest.raises(SessionBlobWriterError, match="unavailable"):
                        await owner.dispose()
                assert calls.count(fd) == 1
            assert owner.cleanup_pending and owner._close_task is None
            assert_busy(root)
            assert os.fstat(replacements[0])
        finally:
            # The test knows which injected replacement it owns. Production
            # must retain the uncertainty and cannot perform this test cleanup.
            for replacement in replacements:
                native_close(replacement)
            writer._close_claimed(owner)

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["borrow_file_io", "_claim_binding"])
def test_partial_second_admission_retained_until_explicit_dispose(root, monkeypatch, stage):
    async def scenario():
        calls = []

        async def forbidden(*args):
            calls.append(args)
            raise AssertionError("failed blob admission reached binder")

        owner, _ = prepare(root, forbidden)

        def failure(*args, **kwargs):
            raise RuntimeError("test after blob acquire")

        monkeypatch.setattr(owner._blob_writer, stage, failure)
        with pytest.raises(RuntimeError, match="after blob acquire"):
            await owner.create()
        driver = owner._driver
        with pytest.raises(RuntimeError, match="after blob acquire"):
            await owner.create()
        assert owner._driver is driver and not calls
        assert owner._blob_writer.claimed_owner is None
        assert_busy(root)
        blob_busy(root)
        assert not (root / "session.jsonl").exists()
        await owner.dispose()
        assert not owner.cleanup_pending
        assert_available(root)
        other = SessionBlobWriterLease(root.parent, "work", _header().conversation_id)
        try:
            other.acquire()
        finally:
            other.close()

    asyncio.run(scenario())


def test_blob_io_cleanup_failure_retains_both_writers_until_retry(root, monkeypatch):
    async def scenario():
        owner, _ = prepare(root)
        await owner.create()
        cleanup = owner._blob_file_io.cleanup
        calls = 0

        def retryable():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("test blob cleanup unavailable")
            cleanup()

        monkeypatch.setattr(owner._blob_file_io, "cleanup", retryable)
        with pytest.raises(OSError, match="blob cleanup"):
            await owner.dispose()
        assert_busy(root)
        blob_busy(root)
        assert owner.cleanup_pending and owner._blob_close_task is None
        await owner.dispose()
        assert calls == 2 and not owner.cleanup_pending
        assert_available(root)

    asyncio.run(scenario())


def test_actual_product_blob_recovery_keeps_both_leases_until_settlement(root, monkeypatch):
    from loushang.ai.types import ImagePart, UserMessage
    from loushang.harness.journal import _rooted_io as native
    from loushang.harness.transcript import ProductTranscriptSession
    from loushang.harness.transcript import product_session as product_module

    async def scenario():
        owner, _ = prepare(root)
        lifecycle = await owner.create()
        session = ProductTranscriptSession(lifecycle_session=lifecycle)
        construct = product_module.SessionBlobStore
        seen = []

        def selected(*args, **kwargs):
            assert kwargs["file_io"] is owner.blob_file_io
            seen.append(True)
            return construct(*args, **kwargs)

        monkeypatch.setattr(product_module, "SessionBlobStore", selected)
        first = UserMessage(role="user", content=[ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")], timestamp=1.0)
        second = UserMessage(role="user", content=[ImagePart(type="image", data="c2Vjb25k", mime_type="image/png")], timestamp=2.0)
        await session.append_message(first)
        replace = native.os.replace

        def unavailable(*args, **kwargs):
            if args[1] == "manifest.json":
                raise OSError("test both manifests unavailable")
            return replace(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(native.os, "replace", unavailable)
            with pytest.raises(OSError, match="manifests unavailable"):
                await session.append_message(second)
            assert len(seen) == 2 and owner.cleanup_pending
            assert_busy(root)
            blob_busy(root)
            with pytest.raises(OSError, match="manifests unavailable"):
                await owner.dispose()
            assert_busy(root)
            blob_busy(root)
        await owner.dispose()
        assert not owner.cleanup_pending
        assert_available(root)
        store = construct(root.parent, _header().conversation_id)
        assert len(store.records) == 1
        assert store.read_bytes(store.records[0]) == b"hello"
        assert {path.name for path in store.objects_root.iterdir()} == {store.records[0].blob_id}

    asyncio.run(scenario())
