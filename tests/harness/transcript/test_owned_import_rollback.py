from __future__ import annotations

import asyncio
import sys
from dataclasses import replace

import pytest

from loushang.harness.conversation import (
    MemoryConversationStore,
    StoreAlreadyExistsError,
    StoreCommitOutcomeUnknown,
    StoreConflictError,
    StoreDataError,
)
from loushang.harness.journal import _rooted_io as native
from loushang.harness.transcript import ProductTranscriptSession
from loushang.harness.transcript.unit_of_work import AgentTranscriptUnitOfWork

from .test_owned_bundle_import import bundle
from .test_owned_session_factory import factory
from .test_runtime_profile import _runtime
from .test_writer_images import message
from .test_writer_lease import TranscriptWriterError
from .test_writer_lifecycle import assert_busy
from .test_writer_root_binding import tree

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned import")


def test_unpublished_import_rejects_non_file_store_before_create(tmp_path, monkeypatch):
    async def scenario():
        source, target = await bundle(tmp_path)
        runtime = _runtime("coding")
        memory = MemoryConversationStore()
        calls = []

        async def forbidden(*args, **kwargs):
            calls.append(1)
            raise AssertionError("unsupported Store reached create")

        async def bind(context, binding_input, retained):
            actual = await runtime.bind_lifecycle_owned(context, binding_input, retained)
            return replace(actual, store=memory)

        monkeypatch.setattr(memory, "create", forbidden)
        selected = factory(runtime=runtime, bind=bind)
        try:
            with pytest.raises(StoreDataError, match="original rooted FileStore"):
                await selected.import_transcript(source, session_dir=target, _unpublished=True)
            assert calls == [] and not tuple(target.glob("*.jsonl"))
            assert not (target.parent / "session-assets/conversation-1").exists()
            assert not selected.pending_preparations
        finally:
            await selected.close()

    asyncio.run(scenario())


def test_import_witness_unknown_close_holds_both_original_writers(tmp_path, monkeypatch):
    async def scenario():
        source, target = await bundle(tmp_path)
        selected = factory()
        session = await selected.import_transcript(source, session_dir=target, _unpublished=True)
        owner = session._writer_owner
        witness = owner._file_io._publication[1]
        fd, = witness.operation.descriptors
        close = native.os.close
        calls = []

        def lost(value):
            close(value)
            if value == fd:
                calls.append(value)
                raise OSError("test lost publication witness close")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(native.os, "close", lost)
                with pytest.raises(OSError, match="lost publication witness close"):
                    await session.dispose()
                assert not session.context.session_file.exists()
                assert owner._import_delete_receipt is not None
                assert owner.cleanup_pending and owner._file_io.cleanup_pending
                assert_busy(target)
                with pytest.raises(OSError, match="cleanup outcome unknown"):
                    await session.dispose()
                assert calls == [fd]
        finally:
            # This injector alone knows the close syscall actually completed.
            witness.operation.descriptors.clear()
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("cut", ["native_return", "uow_return"])
def test_uow_create_return_cannot_adopt_replacement_inode_for_retraction(tmp_path, monkeypatch, cut):
    async def scenario():
        source, target = await bundle(tmp_path)
        selected = factory()
        path = target / "conversation-1.jsonl"
        saved = target / "original-held"
        create = AgentTranscriptUnitOfWork.create
        atomic_write = native.RootedFile.atomic_write
        original_identity = []

        def change():
            value = path.read_bytes()
            status = path.stat()
            original_identity.append((status.st_dev, status.st_ino))
            path.rename(saved)
            path.write_bytes(value)
            path.chmod(0o600)

        async def replaced(cls, *args, **kwargs):
            result = await create(*args, **kwargs)
            change()
            return result

        def after_native(rooted, *args, **kwargs):
            result = atomic_write(rooted, *args, **kwargs)
            if rooted._name == path.name:
                change()
            return result

        with monkeypatch.context() as patch:
            if cut == "uow_return":
                patch.setattr(AgentTranscriptUnitOfWork, "create", classmethod(replaced))
            else:
                patch.setattr(native.RootedFile, "atomic_write", after_native)
            session = await selected.import_transcript(source, session_dir=target, _unpublished=True)
        owner = session._writer_owner
        replacement = path.stat().st_ino
        try:
            assert owner._import_identity == original_identity[0]
            with pytest.raises(TranscriptWriterError, match="conflict"):
                await session.dispose()
            assert path.stat().st_ino == replacement and saved.exists()
            assert owner.cleanup_pending and owner._preserve_publication
            assert (target.parent / "session-assets/conversation-1").exists()
            assert_busy(target)
        finally:
            # Restore only the known original inode in this adversarial test;
            # production leaves the conflict pending and cannot adopt either.
            if saved.exists():
                path.rename(target / "foreign-kept")
                saved.rename(path)
                owner._import_identity = original_identity[0]
                owner._import_unknown = False
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_retraction_never_widens_frozen_revision_to_later_history(tmp_path, monkeypatch):
    async def scenario():
        source, target = await bundle(tmp_path)
        selected = factory()
        session = await selected.import_transcript(source, session_dir=target, _unpublished=True)
        owner = session._writer_owner
        frozen = owner._import_revision
        await ProductTranscriptSession(lifecycle_session=session).append_message(message())
        assert session.transcript.revision > frozen
        path = session.context.session_file
        changed = path.read_bytes()
        calls = []
        delete = session.runtime_binding.store.delete

        async def observed(*args, **kwargs):
            calls.append((kwargs["expected_revision"], kwargs["operation_id"]))
            return await delete(*args, **kwargs)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(session.runtime_binding.store, "delete", observed)
                with pytest.raises(StoreConflictError):
                    await session.dispose()
                assert calls == [(frozen, owner._import_delete_operation)]
                assert path.read_bytes() == changed and owner.cleanup_pending
                assert (target.parent / "session-assets/conversation-1").is_dir()
                assert_busy(target)
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    await session.dispose()
                assert len(calls) == 1
        finally:
            # This fixture intentionally authored additional history. Preserve
            # that now-persistent authority; only test teardown waives the
            # observed conflict debt, never production reconciliation.
            owner._import_delivered = True
            owner._import_unknown = False
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("delivered", [False, True])
def test_original_import_owner_retracts_only_undelivered_creation(tmp_path, archive, delivered):
    async def scenario():
        zipped, target = await bundle(tmp_path)
        source = zipped if archive else next((tmp_path / "source/sessions").glob("*.jsonl"))
        source_before = tree(tmp_path / "source")
        original_bytes = source.read_bytes()
        selected = factory()
        session = await selected.import_transcript(source, session_dir=target, _unpublished=True)
        path = session.context.session_file
        assert path.exists()
        if delivered:
            session._mark_import_delivered()
        try:
            await session.dispose()
            assert path.exists() is delivered
            assert (target.parent / "session-assets/conversation-1").exists() is delivered
            assert tree(tmp_path / "source") == source_before
            assert source.read_bytes() == original_bytes
        finally:
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["runtime", "before_delete"])
def test_retraction_retries_only_original_cleanup_and_frozen_delete_operation(tmp_path, monkeypatch, fault):
    async def scenario():
        source, target = await bundle(tmp_path)
        runtime = _runtime("coding")
        selected = factory(runtime=runtime)
        session = await selected.import_transcript(source, session_dir=target, _unpublished=True)
        owner = session._writer_owner
        path = session.context.session_file
        operations = []
        delete = session.runtime_binding.store.delete

        async def delete_once(*args, **kwargs):
            operations.append(kwargs["operation_id"])
            if fault == "before_delete" and len(operations) == 1:
                raise StoreDataError("known pre-commit test failure")
            return await delete(*args, **kwargs)

        async def failed_runtime(*args):
            raise OSError("original runtime cleanup failed")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(session.runtime_binding.store, "delete", delete_once)
                with patch.context() as phase:
                    if fault == "runtime":
                        phase.setattr(runtime._binder, "dispose", failed_runtime)
                    with pytest.raises(OSError if fault == "runtime" else StoreDataError):
                        await session.dispose()
                assert path.exists() and owner.cleanup_pending
                assert_busy(target)
                if fault == "runtime":
                    assert operations == []
                await session.dispose()
            assert not path.exists()
            assert len(operations) == (1 if fault == "runtime" else 2)
            assert set(operations) == {owner._import_delete_operation}
            assert owner._import_delete_receipt.operation_id == owner._import_delete_operation
        finally:
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_retraction_cancelled_waiter_joins_original_delete_and_fences_public_io(tmp_path, monkeypatch):
    async def scenario():
        source, target = await bundle(tmp_path)
        selected = factory()
        session = await selected.import_transcript(source, session_dir=target, _unpublished=True)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        delete = session.runtime_binding.store.delete

        async def blocked(*args, **kwargs):
            calls.append(kwargs["operation_id"])
            entered.set()
            await release.wait()
            return await delete(*args, **kwargs)

        monkeypatch.setattr(session.runtime_binding.store, "delete", blocked)
        waiter = asyncio.create_task(session.dispose())
        retry = None
        try:
            await entered.wait()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            with pytest.raises(TranscriptWriterError, match="closed"):
                async with session.operation_scope():
                    raise AssertionError("closed import admitted public IO")
            retry = asyncio.create_task(session.dispose())
            await asyncio.sleep(0)
            assert not retry.done() and len(calls) == 1
            release.set()
            await retry
            assert not session.context.session_file.exists()
            assert len(calls) == 1
        finally:
            release.set()
            await asyncio.gather(waiter, *(() if retry is None else (retry,)), return_exceptions=True)
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["unknown_commit", "wrong_receipt"])
def test_unknown_retraction_keeps_original_debt_and_never_replays_delete(tmp_path, monkeypatch, fault):
    async def scenario():
        source, target = await bundle(tmp_path)
        selected = factory()
        session = await selected.import_transcript(source, session_dir=target, _unpublished=True)
        owner = session._writer_owner
        path = session.context.session_file
        delete = session.runtime_binding.store.delete
        actual_receipts = []

        async def lost(*args, **kwargs):
            receipt = await delete(*args, **kwargs)
            actual_receipts.append(receipt)
            if fault == "unknown_commit":
                raise StoreCommitOutcomeUnknown("actual delete committed; test lost reply")
            return replace(receipt, operation_id="foreign-receipt")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(session.runtime_binding.store, "delete", lost)
                with pytest.raises(StoreCommitOutcomeUnknown):
                    await session.dispose()
                assert not path.exists()
                assert owner._import_delete_receipt is None and owner._preserve_publication
                assert (target.parent / "session-assets/conversation-1").exists()
                assert_busy(target)
                path.write_bytes(b"replacement must remain")
                with pytest.raises(TranscriptWriterError, match="unavailable"):
                    await session.dispose()
                assert len(actual_receipts) == 1
                assert path.read_bytes() == b"replacement must remain"
        finally:
            # Test-only delivery of the exact receipt captured before this
            # injector hid/corrupted it. Production does not infer it from EOF
            # or absence and cannot discard unknown debt this way.
            if actual_receipts:
                owner._import_delete_receipt = actual_receipts[0]
                owner._import_unknown = False
                owner._preserve_publication = False
            await session.dispose()
            assert path.read_bytes() == b"replacement must remain"
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("different_path", [False, True])
def test_equal_preexisting_creation_cannot_become_retractable(tmp_path, different_path):
    async def scenario():
        source, target = await bundle(tmp_path, images=False)
        selected = factory()
        previous = await selected.import_bundle(source, session_dir=target)
        await previous.dispose()
        path = previous.context.session_file
        if different_path:
            path = path.rename(path.with_name("older-authority.jsonl"))
        original = path.read_bytes()
        try:
            with pytest.raises(StoreAlreadyExistsError):
                await selected.import_transcript(source, session_dir=target, _unpublished=True)
            assert path.read_bytes() == original
            assert not selected.pending_preparations
        finally:
            await selected.close()

    asyncio.run(scenario())
