from __future__ import annotations

import asyncio
import sys
import threading

import pytest

from loushang.harness.artifacts import SessionBlobPublication, SessionBlobStore
from loushang.harness.conversation import StoreCommitOutcomeUnknown
from loushang.harness.conversation.stores import file as file_module
from loushang.harness.journal import _rooted_io as native
from loushang.harness.transcript import (
    ProductTranscriptSession,
    unit_of_work,
    writer_lifecycle,
)
from loushang.harness.transcript.export import (
    export_agent_transcript_bundle,
    read_agent_transcript_bundle,
)
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_owned_session_factory import factory, new
from .test_runtime_profile import _runtime
from .test_writer_blobs import blob_busy
from .test_writer_images import message
from .test_writer_io import wait_until
from .test_writer_lifecycle import assert_available, assert_busy
from .test_writer_root_binding import tree

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned import")


async def bundle(tmp_path, *, images=True):
    source = tmp_path / "source" / "sessions"
    source.parent.mkdir(mode=0o700)
    source.mkdir(mode=0o700)
    selected = factory()
    session = await new(selected, source)
    try:
        if images:
            await ProductTranscriptSession(lifecycle_session=session).append_message(message())
    finally:
        await session.dispose()
        await selected.close()
    archive = tmp_path / "session.zip"
    export_agent_transcript_bundle(
        session.context.header, session.transcript.records,
        session_dir=source, output_path=archive, allow_private=True,
    )
    target = tmp_path / "target" / "sessions"
    target.parent.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    return archive, target


@pytest.mark.parametrize("images", [False, True])
def test_real_owned_bundle_import_roundtrip(tmp_path, monkeypatch, images):
    async def scenario():
        archive, target = await bundle(tmp_path, images=images)
        selected = factory()
        actual = writer_lifecycle.SessionBlobStore
        ports = []

        def rooted(*args, **kwargs):
            retained, = selected.pending_preparations
            assert kwargs["file_io"] is retained.blob_file_io
            assert retained._writer.claimed_owner is retained
            assert retained._blob_writer.claimed_owner is retained
            ports.append(kwargs["file_io"])
            return actual(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(writer_lifecycle, "SessionBlobStore", rooted)
            session = await selected.import_bundle(archive, session_dir=target)
        try:
            assert session.context.session_file.exists()
            assert len(ports) == int(images)
            assert not selected.pending_preparations
            if images:
                assert session.session_blob_health[0].state == "available"
                context = ProductTranscriptSession(lifecycle_session=session).build_session_context()
                assert context.messages[0].content[0].data == "aGVsbG8="
        finally:
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_busy_import_does_not_publish_attachments(tmp_path, monkeypatch):
    async def scenario():
        archive, target = await bundle(tmp_path)
        first, selected = factory(), factory()
        held = await new(first, target)
        before = tree(target.parent)

        def forbidden(*args, **kwargs):
            raise AssertionError("busy import attempted publication")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(writer_lifecycle, "SessionBlobStore", forbidden)
                with pytest.raises(TranscriptWriterError, match="busy"):
                    await selected.import_bundle(archive, session_dir=target)
            assert tree(target.parent) == before
            assert not selected.pending_preparations
        finally:
            await held.dispose()
            await first.close()
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["binder", "post_write", "snapshot", "projection", "health"])
def test_import_distinguishes_precommit_and_committed_failures(tmp_path, monkeypatch, failure):
    async def scenario():
        archive, target = await bundle(tmp_path)
        runtime = _runtime("coding")

        async def fail_binding(context, profile, owner):
            await runtime.bind_lifecycle_owned(context, profile, owner)
            raise ValueError("test before transcript creation")

        selected = factory(runtime=runtime, bind=fail_binding if failure == "binder" else None)
        write = file_module._write_unlocked

        def after_write(*args, **kwargs):
            write(*args, **kwargs)
            raise OSError("test write completed but reply failed")

        def projection(*args, **kwargs):
            raise ValueError("test local projection failed")

        with monkeypatch.context() as patch:
            if failure == "post_write":
                patch.setattr(file_module, "_write_unlocked", after_write)
            elif failure == "projection":
                patch.setattr(unit_of_work.ConversationRepository, "from_snapshot", projection)
            elif failure == "snapshot":
                patch.setattr(file_module, "ConversationSnapshot", projection)
            elif failure == "health":
                patch.setattr(writer_lifecycle, "_lifecycle_session", projection)
            with pytest.raises(StoreCommitOutcomeUnknown if failure in {"post_write", "snapshot", "projection"} else ValueError):
                await selected.import_bundle(archive, session_dir=target)
        assert not selected.pending_preparations
        await selected.close()
        if failure == "binder":
            assert not (target.parent / "session-assets/conversation-1").exists()
            assert not (target / "conversation-1.jsonl").exists()
        else:
            reader = factory()
            restored = await reader.open(target / "conversation-1.jsonl")
            try:
                assert restored.session_blob_health[0].state == "available"
            finally:
                await restored.dispose()
                await reader.close()

    asyncio.run(scenario())


def test_create_native_close_loss_does_not_rollback_referenced_attachments(tmp_path, monkeypatch):
    async def scenario():
        archive, target = await bundle(tmp_path)
        selected = factory()
        write, close = file_module._write_unlocked, native.os.close
        written, lost = [], []

        def published(*args, **kwargs):
            result = write(*args, **kwargs)
            written.append(True)
            return result

        def lost_close(fd):
            if written and not lost:
                name = native.os.readlink(f"/proc/self/fd/{fd}")
                if name == str(target / "conversation-1.jsonl.lock"):
                    close(fd)
                    lost.append(fd)
                    raise OSError("test native close reply lost")
            return close(fd)

        with monkeypatch.context() as patch:
            patch.setattr(file_module, "_write_unlocked", published)
            patch.setattr(native.os, "close", lost_close)
            with pytest.raises(StoreCommitOutcomeUnknown):
                await selected.import_bundle(archive, session_dir=target)
        retained, = selected.pending_preparations
        assert len(lost) == 1 and retained._preserve_publication
        assert_busy(target)
        store = SessionBlobStore(target.parent, "conversation-1")
        assert store.read_bytes(store.records[0]) == b"hello"
        with pytest.raises(OSError, match="unknown"):
            await selected.close()
        # Test-only reconciliation: this injector knows close() returned before
        # it fabricated a lost reply. Remove only that known receipt; never
        # retry its numeric fd. Production remains fail-closed without proof.
        removed = []
        for operation in retained._file_io._operations:
            for fd in lost:
                if fd in operation.descriptors:
                    assert operation.descriptors.pop(fd) is True
                    removed.append(fd)
        assert removed == lost
        await selected.close()
        assert not selected.pending_preparations

    asyncio.run(scenario())


def test_import_rollback_debt_resumes_original_settlement_without_replaying(tmp_path, monkeypatch):
    async def scenario():
        archive, target = await bundle(tmp_path)
        runtime = _runtime("coding")

        async def fail_binding(context, profile, owner):
            await runtime.bind_lifecycle_owned(context, profile, owner)
            raise ValueError("test binder rejects after attachment publication")

        selected = factory(runtime=runtime, bind=fail_binding)
        rmdir = native.os.rmdir

        def unavailable(name, *args, **kwargs):
            if name == "objects":
                raise OSError("test retained deletion failure")
            return rmdir(name, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(native.os, "rmdir", unavailable)
            with pytest.raises(ValueError, match="binder rejects"):
                await selected.import_bundle(archive, session_dir=target)
            retained, = selected.pending_preparations
            receipt = retained._publication
            assert receipt.rollback_delegated and not receipt.rollback_complete
            assert_busy(target)
            with pytest.raises(OSError, match="retained deletion failure"):
                await selected.close()
            assert selected.pending_preparations == (retained,)
        await selected.close()
        assert receipt.rollback_complete and not selected.pending_preparations
        assert not (target.parent / "session-assets/conversation-1").exists()
        assert_available(target)

    asyncio.run(scenario())


def test_initial_attachment_intent_is_frozen_before_acquire(tmp_path):
    async def scenario():
        archive, target = await bundle(tmp_path)
        contents = read_agent_transcript_bundle(archive)
        selected, runtime = factory(), _runtime("coding")
        context = selected._new_context(session_dir=target, cwd="/workspace", persist=True, header=contents.header)
        payload = bytearray(contents.blobs[0][1])
        items, records = [(contents.blobs[0][0], payload)], list(contents.records)
        owner = selected._lifecycle.prepare_owned_writer(
            context, runtime.resolve(persist=True), product_id="coding", manage_blobs=True,
            initial_blobs=items, records=records,
        )
        items.clear()
        records.clear()
        payload[:] = b"changed after preparation"
        try:
            session = await owner.create()
            assert session.session_blob_health[0].state == "available"
            assert session.transcript.records == contents.records
            assert session.context.session_file.exists()
        finally:
            await owner.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_cancel_after_publication_keeps_original_cleanup_owner(tmp_path):
    async def scenario():
        archive, target = await bundle(tmp_path)
        runtime = _runtime("coding")
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(context, profile, owner):
            result = await runtime.bind_lifecycle_owned(context, profile, owner)
            entered.set()
            await release.wait()
            return result

        selected = factory(runtime=runtime, bind=delayed)
        caller = asyncio.create_task(selected.import_bundle(archive, session_dir=target))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            retained, = selected.pending_preparations
            assert retained._publication is not None
            caller.cancel()
            await wait_until(lambda: retained.closing)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert selected.pending_preparations == (retained,)
            assert_busy(target)
        finally:
            release.set()
            await asyncio.gather(caller, return_exceptions=True)
            await selected.close()
        assert not selected.pending_preparations
        assert not (target.parent / "session-assets/conversation-1").exists()
        assert_available(target)

    asyncio.run(scenario())


def test_rollback_refusal_does_not_report_cleanup_success(tmp_path, monkeypatch):
    async def scenario():
        archive, target = await bundle(tmp_path)
        runtime = _runtime("coding")

        async def fail_binding(context, profile, owner):
            await runtime.bind_lifecycle_owned(context, profile, owner)
            raise ValueError("test import rejected")

        selected = factory(runtime=runtime, bind=fail_binding)
        with monkeypatch.context() as patch:
            patch.setattr(SessionBlobPublication, "rollback", lambda self: False)
            with pytest.raises(ValueError, match="import rejected"):
                await selected.import_bundle(archive, session_dir=target)
            retained, = selected.pending_preparations
            assert retained._publication is not None and retained.cleanup_pending
            with pytest.raises(TranscriptWriterError, match="conflict"):
                await selected.close()
            assert_busy(target)
        await selected.close()
        assert not selected.pending_preparations

    asyncio.run(scenario())


def test_completed_native_rollback_still_waits_for_original_task_receipt(tmp_path):
    async def scenario():
        archive, target = await bundle(tmp_path)
        runtime = _runtime("coding")
        completed, release = threading.Event(), threading.Event()
        calls = []

        async def fail_binding(context, profile, binding_owner):
            await runtime.bind_lifecycle_owned(context, profile, binding_owner)
            retained, = selected.pending_preparations
            rollback = retained._rollback_import

            def delayed_receipt():
                rollback()
                calls.append(True)
                completed.set()
                assert release.wait(5)

            retained._rollback_import = delayed_receipt
            raise ValueError("test failure before create")

        selected = factory(runtime=runtime, bind=fail_binding)
        caller = asyncio.create_task(selected.import_bundle(archive, session_dir=target))
        closing = None
        try:
            await wait_until(completed.is_set)
            retained, = selected.pending_preparations
            original_task = retained._publication_rollback_task
            assert retained._publication.rollback_complete and not original_task.done()
            caller.cancel()
            with pytest.raises(ValueError, match="failure before create"):
                await caller
            closing = asyncio.create_task(selected.close())
            await asyncio.sleep(0)
            assert not closing.done() and retained.cleanup_pending
            assert retained._publication_rollback_task is original_task
            assert_busy(target)
            release.set()
            await asyncio.wait_for(closing, 5)
            assert calls == [True] and not selected.pending_preparations
        finally:
            release.set()
            await asyncio.gather(caller, *([closing] if closing else []), return_exceptions=True)
            await selected.close()

    asyncio.run(scenario())


def test_real_rollback_identity_conflict_preserves_replacement_and_both_leases(tmp_path):
    async def scenario():
        archive, target = await bundle(tmp_path)
        runtime = _runtime("coding")
        authority = target.parent / "session-assets/conversation-1"
        original = authority.with_name("original-import")

        async def swap_before_failure(context, profile, binding_owner):
            await runtime.bind_lifecycle_owned(context, profile, binding_owner)
            authority.rename(original)
            authority.mkdir(mode=0o700)
            manifest = authority / "manifest.json"
            manifest.write_bytes((original / "manifest.json").read_bytes())
            manifest.chmod(0o600)
            (authority / "sentinel").write_bytes(b"replacement")
            raise ValueError("test replacement before failed create")

        selected = factory(runtime=runtime, bind=swap_before_failure)
        with pytest.raises(ValueError, match="replacement before failed create"):
            await selected.import_bundle(archive, session_dir=target)
        retained, = selected.pending_preparations
        before = tree(authority)
        with pytest.raises(TranscriptWriterError, match="conflict"):
            await selected.close()
        assert selected.pending_preparations == (retained,)
        assert tree(authority) == before
        assert_busy(target)
        blob_busy(target)
        # Restore only the test's exact original authority, leaving the
        # replacement separately intact; production must not do this itself.
        replacement = authority.with_name("replacement-saved")
        authority.rename(replacement)
        original.rename(authority)
        await selected.close()
        assert tree(replacement) == before
        assert not authority.exists() and not selected.pending_preparations

    asyncio.run(scenario())
