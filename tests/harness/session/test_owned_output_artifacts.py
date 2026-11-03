from __future__ import annotations

import asyncio
import hashlib
import stat
import sys

import pytest

from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.journal import _rooted_io as native
from loushang.harness.session.output_artifacts import persist_session_command_outputs
from loushang.harness.transcript.writer_lease import TranscriptWriterError
from loushang.harness.workspace.exec import ExecRequest

from ..transcript.test_owned_session_factory import factory, new
from ..transcript.test_writer_blobs import blob_busy
from ..transcript.test_writer_lifecycle import assert_busy
from .test_output_artifacts import _CapturedOutputService

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned output IO")


def adapter(session, delegate, scratch):
    return persist_session_command_outputs(
        delegate, session_dir=session.context.session_dir,
        session_id=session.context.header.conversation_id, persist=True, temporary_root=scratch,
        file_io=session.blob_file_io, operation_scope=session.operation_scope,
        initialization_scope=session.sync_operation_scope,
    )


def test_owned_output_initialization_publication_and_legacy_id_reuse(tmp_path):
    async def scenario():
        selected = factory()
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        session = await new(selected, root, "legacy:id")
        try:
            service = adapter(session, _CapturedOutputService(), tmp_path / "scratch")
            assert service._store._file_io is session.blob_file_io
            assert stat.S_IMODE((tmp_path / "session-assets").stat().st_mode) == 0o700
            assert adapter(session, service, tmp_path / "scratch") is service
            result = await service.execute(ExecRequest(command=("unused",), cwd=str(tmp_path)))
            assert result.artifact_retention_error is None
            assert result.stdout_artifact_path is None
            with session.sync_operation_scope():
                assert service._store.read_bytes(result.stdout_artifact_ref) == b"complete stdout\n"
            assert not list((tmp_path / "scratch").iterdir())
        finally:
            await session.dispose()
            await selected.close()
        with pytest.raises(TranscriptWriterError):
            await service.execute(ExecRequest(command=("unused",), cwd=str(tmp_path)))

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_owned_output_execution_and_cancel_cleanup_hold_both_writers(tmp_path, cancel):
    async def scenario():
        selected = factory()
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        session = await new(selected, root)
        entered, release, cleaning = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Delayed(_CapturedOutputService):
            async def execute(self, request, *, signal=None, on_update=None):
                entered.set()
                try:
                    await release.wait()
                    return await super().execute(request, signal=signal, on_update=on_update)
                finally:
                    cleaning.set()
                    await release.wait()

        service = adapter(session, Delayed(), tmp_path / "scratch")
        task = asyncio.create_task(service.execute(ExecRequest(command=("unused",), cwd=str(tmp_path))))
        closer = None
        try:
            await asyncio.wait_for(entered.wait(), 5)
            if cancel:
                task.cancel()
                await asyncio.wait_for(cleaning.wait(), 5)
            closer = asyncio.create_task(session.dispose())
            await asyncio.sleep(0)
            assert not closer.done()
            assert_busy(root)
            blob_busy(root)
            release.set()
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                result = await task
                assert result.artifact_retention_error is None
                assert SessionBlobStore(tmp_path, "conversation-1").read_bytes(result.stdout_artifact_ref) == b"complete stdout\n"
            await closer
        finally:
            release.set()
            await asyncio.gather(task, *([closer] if closer else []), return_exceptions=True)
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_output_retention_error_does_not_discard_native_recovery_debt(tmp_path, monkeypatch):
    async def scenario():
        selected = factory()
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        session = await new(selected, root)
        service = adapter(session, _CapturedOutputService(), tmp_path / "scratch")
        original_stat, original_unlink = service._store._stat, native.os.unlink
        digest = hashlib.sha256(b"complete stdout\n").hexdigest()

        def lost_receipt(path):
            if path == service._store.root:
                raise OSError("publication receipt unavailable")
            return original_stat(path)

        def failed_cleanup(name, *args, **kwargs):
            if name == digest:
                raise OSError("output rollback unavailable")
            return original_unlink(name, *args, **kwargs)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(service._store, "_stat", lost_receipt)
                patch.setattr(native.os, "unlink", failed_cleanup)
                result = await service.execute(ExecRequest(command=("unused",), cwd=str(tmp_path)))
                assert result.artifact_retention_error is not None and result.stdout_artifact_ref is None
                assert session.blob_file_io.cleanup_pending
                with pytest.raises(OSError):
                    await session.dispose()
                assert_busy(root)
                blob_busy(root)
            await session.dispose()
            assert not service._file_io.cleanup_pending
            assert not service._store.root.exists()
        finally:
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())
