from __future__ import annotations

import asyncio
import sys
import threading

import pytest

from loushang.harness.transcript import AgentTranscriptLifecycle
from loushang.harness.transcript.writer_lease import (
    TranscriptWriterError,
    TranscriptWriterLease,
)

from .test_lifecycle import _header, _record
from .test_runtime_profile import _runtime
from .test_writer_io import wait_until
from .test_writer_lifecycle import assert_available, assert_busy

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned acquisition")


def preparation(root, *, bind=None, create_root=False, **kwargs):
    runtime = _runtime("coding")
    lifecycle = AgentTranscriptLifecycle(
        bind_runtime=runtime.bind_lifecycle, bind_runtime_owned=bind or runtime.bind_lifecycle_owned,
    )
    context = lifecycle.new_context(
        session_dir=root, cwd="/workspace", persist=True,
        header=_header(), session_file=root / "session.jsonl",
    )
    return lifecycle.prepare_owned_writer(
        context, runtime.resolve(persist=True), product_id="coding", manage_blobs=True,
        create_root=create_root,
        **kwargs,
    )


def test_preparation_pins_session_and_attachment_roots_before_runtime_construction(tmp_path):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        info, parent = root.stat(), tmp_path.stat()
        owner = preparation(root, expected_root_identity=(info.st_dev, info.st_ino),
                            expected_parent_identity=(parent.st_dev, parent.st_ino))
        assert owner._blob_writer._expected_root_identity == (parent.st_dev, parent.st_ino)
        moved = tmp_path / "original"
        root.rename(moved)
        root.mkdir(mode=0o700)
        try:
            with pytest.raises(TranscriptWriterError, match="conflict"):
                await owner.create()
        finally:
            await owner.dispose()
        assert not tuple(root.iterdir()) and not tuple(moved.iterdir())
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_admitted_root_identity_constructs_original_owned_session(tmp_path):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        info, parent = root.stat(), tmp_path.stat()
        owner = preparation(root, expected_root_identity=(info.st_dev, info.st_ino),
                            expected_parent_identity=(parent.st_dev, parent.st_ino))
        try:
            session = await owner.create()
            assert session._writer_owner is owner and owner._writer._held
            assert owner._blob_writer._held
        finally:
            await owner.dispose()
        assert not owner.cleanup_pending

    asyncio.run(scenario())


def test_store_admission_primary_failure_survives_cleanup_failure(tmp_path, monkeypatch):
    async def scenario():
        root = tmp_path / "data/sessions"
        owner = preparation(root, store_state_root=tmp_path / "state/session-stores", initialize_store=True)
        admission = owner._store_admission
        original_close = admission.close
        failure = TranscriptWriterError("incomplete")
        calls = []

        def fail_open():
            calls.append("open")
            raise failure

        def fail_close():
            calls.append("close")
            raise OSError("cleanup incomplete")

        monkeypatch.setattr(admission, "open", fail_open)
        monkeypatch.setattr(admission, "close", fail_close)
        try:
            with pytest.raises(TranscriptWriterError) as caught:
                await owner.create()
            assert caught.value is failure
            assert "store admission cleanup retained" in failure.__notes__[0]
            assert calls == ["open", "close"]
            assert not owner._writer._attempted and not owner._binding_started
            assert owner._store_admission is admission
        finally:
            monkeypatch.setattr(admission, "close", original_close)
            await owner.dispose()
        assert not owner.cleanup_pending and not root.exists()

    asyncio.run(scenario())


def test_cancel_during_store_intent_retains_original_driver_and_cleanup(tmp_path, monkeypatch):
    async def scenario():
        root = tmp_path / "data/sessions"
        owner = preparation(root, store_state_root=tmp_path / "state/session-stores", initialize_store=True)
        entered, release = threading.Event(), threading.Event()
        admission = owner._store_admission
        write = admission._write
        publications = []

        def pause(record):
            write(record)
            publications.append(record["phase"])
            if record["phase"] == "initializing":
                entered.set()
                assert release.wait(10)

        monkeypatch.setattr(admission, "_write", pause)
        caller = asyncio.create_task(owner.create())
        closing = None
        try:
            await wait_until(entered.is_set)
            assert owner.cleanup_pending and admission.cleanup_pending
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            closing = asyncio.create_task(owner.dispose())
            await wait_until(lambda: owner.closing)
            assert not closing.done() and not root.exists()
            release.set()
            await asyncio.wait_for(closing, 10)
            assert publications == ["initializing", "initialized"]
            assert owner._store_admission is admission and not owner.cleanup_pending
            assert root.is_dir() and not tuple(root.glob("*.jsonl"))
        finally:
            release.set()
            await asyncio.gather(caller, *([closing] if closing is not None else []), return_exceptions=True)
            await owner.dispose()

    asyncio.run(scenario())


def test_root_creation_grant_cannot_be_used_for_restore(tmp_path):
    async def scenario():
        root = tmp_path / "new" / "sessions"
        owner = preparation(root, create_root=True)
        try:
            with pytest.raises(TranscriptWriterError, match="invalid"):
                await owner.restore()
            assert not owner.cleanup_pending and owner._driver is None
            assert not root.parent.exists()
        finally:
            await owner.dispose()

    asyncio.run(scenario())


def test_cancel_during_mkdir_keeps_original_native_preparation(tmp_path, monkeypatch):
    from loushang.harness.journal import _directory_lease as directory_module

    async def scenario():
        root = tmp_path / "new" / "sessions"
        owner = preparation(root, create_root=True)
        entered, release = threading.Event(), threading.Event()
        mkdir = directory_module.os.mkdir
        calls = []

        def paused_mkdir(path, *args, **kwargs):
            result = mkdir(path, *args, **kwargs)
            if path == "new":
                calls.append(path)
                entered.set()
                assert release.wait(10)
            return result

        monkeypatch.setattr(directory_module.os, "mkdir", paused_mkdir)
        caller = asyncio.create_task(owner.create())
        closing = None
        try:
            await wait_until(entered.is_set)
            assert owner.cleanup_pending and owner._writer._sync_pending
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            closing = asyncio.create_task(owner.dispose())
            await wait_until(lambda: owner.closing)
            assert not closing.done() and not root.exists()
            release.set()
            await asyncio.wait_for(closing, 10)
            assert calls == ["new"] and not owner.cleanup_pending
            assert owner._driver.done() and owner._runtime_done
            assert root.is_dir() and not tuple(root.glob("*.jsonl"))
        finally:
            release.set()
            await asyncio.gather(caller, *([closing] if closing is not None else []), return_exceptions=True)
            await owner.dispose()

    asyncio.run(scenario())


def test_pure_preparation_can_be_disposed_without_acquiring(tmp_path, monkeypatch):
    async def scenario():
        def forbidden(*args, **kwargs):
            raise AssertionError("pure preparation acquired a writer")

        monkeypatch.setattr(TranscriptWriterLease, "acquire", forbidden)
        owner = preparation(tmp_path)
        assert not owner.cleanup_pending
        assert owner._writer.claimed_owner is None
        assert owner._file_io is None and owner.blob_file_io is None
        assert not tuple(tmp_path.iterdir())
        await owner.dispose()
        with pytest.raises(TranscriptWriterError, match="closed"):
            await owner.create()
        assert not tuple(tmp_path.iterdir())

    asyncio.run(scenario())


def test_internal_admission_create_then_restore_uses_same_owner(tmp_path):
    async def scenario():
        first = preparation(tmp_path)
        try:
            session = await first.create()
            assert session._writer_owner is first
            assert first._writer.claimed_owner is first
            assert first._binding_owner.file_io is first._file_io
            assert first.blob_file_io is not None
            assert not (tmp_path / "session.jsonl").exists()
            await session.transcript.append_agent_message(_record("one").payload)
            records = session.transcript.records
            assert_busy(tmp_path)
        finally:
            await first.dispose()
        second = preparation(tmp_path)
        try:
            restored = await second.restore()
            assert restored.transcript.records == records
            assert restored._writer_owner is second
        finally:
            await second.dispose()
        assert_available(tmp_path)

    asyncio.run(scenario())


@pytest.mark.parametrize("step", ["acquire", "_borrow_file_io", "_claim"])
@pytest.mark.parametrize("after", [False, True])
def test_partial_admission_is_retained_and_never_reacquired(tmp_path, monkeypatch, step, after):
    async def scenario():
        calls = []

        async def forbidden(*args):
            raise AssertionError("partial writer admission reached binder")

        owner = preparation(tmp_path, bind=forbidden)
        original = getattr(owner._writer, step)

        def fail(*args, **kwargs):
            calls.append(True)
            if after:
                original(*args, **kwargs)
            raise OSError("test native admission failure")

        monkeypatch.setattr(owner._writer, step, fail)
        try:
            for _ in range(2):
                with pytest.raises(OSError, match="native admission failure"):
                    await owner.create()
            assert len(calls) == 1 and not owner._binding_started
            assert not (tmp_path / "session.jsonl").exists()
            if step != "acquire" or after:
                assert owner.cleanup_pending
                assert_busy(tmp_path)
        finally:
            await owner.dispose()
        assert not owner.cleanup_pending
        assert_available(tmp_path)

    asyncio.run(scenario())


def test_cancelled_waiter_does_not_abandon_inflight_acquire(tmp_path, monkeypatch):
    async def scenario():
        owner = preparation(tmp_path)
        entered, release = threading.Event(), threading.Event()
        original = owner._writer.acquire
        calls = []

        def acquire():
            calls.append(True)
            original()
            entered.set()
            assert release.wait(5)

        monkeypatch.setattr(owner._writer, "acquire", acquire)
        caller = asyncio.create_task(owner.create())
        closing = None
        try:
            await wait_until(entered.is_set)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert_busy(tmp_path)
            closing = asyncio.create_task(owner.dispose())
            await wait_until(lambda: owner.closing)
            assert not closing.done()
            release.set()
            await asyncio.wait_for(closing, 5)
            assert len(calls) == 1 and not owner.cleanup_pending
            assert_available(tmp_path)
        finally:
            release.set()
            await asyncio.gather(caller, *([closing] if closing is not None else []), return_exceptions=True)
            await owner.dispose()

    asyncio.run(scenario())


def test_admission_samples_claim_transition_once(tmp_path, monkeypatch):
    async def scenario():
        owner = preparation(tmp_path)
        reads = []

        def claim_transition(writer):
            reads.append(writer)
            return None if len(reads) == 1 else owner

        with monkeypatch.context() as patch:
            patch.setattr(TranscriptWriterLease, "claimed_owner", property(claim_transition))
            owner._on_loop()
            assert reads == [owner._writer]
        await owner.dispose()

    asyncio.run(scenario())


def test_busy_internal_admission_cleanup_does_not_release_other_owner(tmp_path):
    async def scenario():
        first = preparation(tmp_path)
        await first.create()
        calls = []

        async def forbidden(*args):
            calls.append(True)
            raise AssertionError("busy writer reached binding")

        second = preparation(tmp_path, bind=forbidden)
        try:
            with pytest.raises(TranscriptWriterError, match="busy"):
                await second.create()
            assert not calls and second.cleanup_pending
            await second.dispose()
            assert not second.cleanup_pending
            assert_busy(tmp_path)
        finally:
            await second.dispose()
            await first.dispose()
        third = preparation(tmp_path)
        try:
            await third.create()
        finally:
            await third.dispose()
        assert_available(tmp_path)

    asyncio.run(scenario())
