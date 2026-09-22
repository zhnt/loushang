from __future__ import annotations

import asyncio
import sys

import pytest

from loushang.harness.session.output_artifacts import SessionOutputPersistingExecService
from loushang.harness.workspace.exec import ExecRequest, ExecService
from tests.harness.session.test_output_capture import Backend, Factory, Lease
from tests.harness.transcript.test_writer_lease import busy, lease

from .test_owned_session_runtime import runtime

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned writer")


def test_graph_owned_writer_is_retained_until_output_cleanup_succeeds(tmp_path):
    async def run():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        owner = runtime(root)
        capture = Lease(fail_close=True)
        try:
            session = await owner.create_session(cwd=str(tmp_path))
            manager = session.session_manager
            original = manager._lifecycle_session
            assert original.ownership_state == "graph_owned"
            identity = manager.header.conversation_id
            service = SessionOutputPersistingExecService(
                ExecService(backend=Backend()), session_dir=manager.session_dir,
                session_id=identity, file_io=original.blob_file_io,
                operation_scope=original.operation_scope,
                initialization_scope=original.sync_operation_scope,
                capture_factory=Factory(capture),
            )
            # Inject only the fake storage/execution boundary; exercise the real
            # Product shutdown, capability graph and rooted Session writer.
            session._exec_service = service
            session._tool_exec_service = service
            result = await service.execute(ExecRequest(("unused",)))
            assert result.stdout_artifact_ref is not None
            assert result.artifact_cleanup_error == "temporary_cleanup_pending"
            # Automatic Graph rollback reaches this same disposer before the
            # Product's outer except. The guard must reject before inspecting
            # or mutating any bundle/transcript, without awaiting capture.
            with pytest.raises(RuntimeError, match="capture cleanup remains pending"):
                await session._session_capability_binding.dispose(None)
            assert original.ownership_state == "graph_owned"
            busy(root, conversation=identity)
            with pytest.raises(OSError, match="private path"):
                await session.dispose()
            assert original.ownership_state == "graph_owned"
            assert not manager.runtime_disposed
            busy(root, conversation=identity)
            with original.sync_operation_scope():
                assert service._store.read_bytes(result.stdout_artifact_ref) == b"data"
            capture.fail_close = False
            await session.dispose()
            assert manager.runtime_disposed
            reopened = lease(root, conversation=identity)
            try:
                reopened.acquire()
            finally:
                reopened.close()
        finally:
            capture.fail_close = False
            await owner.dispose_session_runtime()
    asyncio.run(run())
