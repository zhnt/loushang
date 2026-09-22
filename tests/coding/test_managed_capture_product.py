from __future__ import annotations

import asyncio
import sys

import pytest

from loushang.apphost.managed import storage_budget
from loushang.apphost.managed.output_capture import ManagedOutputCaptureFactory
from loushang.coding import bootstrap
from loushang.coding.bootstrap import create_agent_session
from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime
from loushang.harness.session import output_artifacts
from loushang.harness.workspace.exec import ExecRequest
from tests.apphost.test_managed_files import directory as directory
from tests.apphost.test_managed_storage_budget import namespace as namespace
from tests.apphost.test_managed_storage_budget import pytestmark as pytestmark
from tests.apphost.test_managed_storage_budget import registry as registry
from tests.apphost.test_native_output_capture import capture

from .test_agent_session_runtime import _model


@pytest.mark.parametrize("scenario", ["text", "binary", "capacity_refused", "overflow"])
def test_real_coding_session_uses_managed_capture_and_keeps_session_blob(registry, directory, tmp_path, monkeypatch, scenario):
    def reject_unmanaged_scratch(*args, **kwargs):
        pytest.fail("persistent managed execution must not allocate legacy temporary directories")

    # Capacity refusal/overflow must degrade retention, not fall back to an
    # unbudgeted spool. Persistent Product construction needs no ephemeral
    # plugin state either. Patch the consumers, not tempfile globally.
    monkeypatch.setattr(output_artifacts, "TemporaryDirectory", reject_unmanaged_scratch)
    monkeypatch.setattr(bootstrap, "_ExplicitTemporaryDirectory", reject_unmanaged_scratch)
    native = capture(registry, directory)
    request = native.allocations[0]
    factory = ManagedOutputCaptureFactory(native.owner, native.budget, service_id=request.service_id,
                                          instance_id=request.instance_id, capacity=4096)
    root = tmp_path / "sessions"
    root.mkdir(mode=0o700)

    def build(manager, *, session_start_event):
        return create_agent_session(session_manager=manager, model=_model(), no_tools=True,
                                    session_start_event=session_start_event, output_capture_factory=factory)

    runtime = AgentSessionRuntime(session_dir=root, session_factory=build, owned_transcripts=True)
    script = "print('captured')"
    stdout, stderr, exit_code = b"captured\n", b"", 0
    if scenario == "binary":
        script = "import os; os.write(1,b'\\xe4'); os.write(1,b'\\xbd\\xa0\\xff'); os.write(2,b'\\x80tail')"
        stdout, stderr, exit_code = "你".encode() + b"\xff", b"\x80tail", 7
    if scenario == "overflow":
        script = "import os; os.write(1,b'x'*5000); os.write(2,b'finished')"
        stdout, stderr, exit_code = b"x" * 5000, b"finished", 9
    marker = tmp_path / "command-finished"
    script += f"; from pathlib import Path; Path({str(marker)!r}).write_text('done'); raise SystemExit({exit_code})"
    if scenario == "capacity_refused":
        monkeypatch.setattr(storage_budget, "TEMPORARY_INSTANCE_BYTES", 8192)

    async def run():
        held = None
        try:
            if scenario == "capacity_refused":
                held = factory.new_capture()
                await held.prepare()
            session = await runtime.create_session(cwd=str(tmp_path))
            assert session.session_manager.persist
            service = session._exec_service
            result = await service.execute(ExecRequest((sys.executable, "-c", script)))
            assert result.exit_code == exit_code
            assert marker.read_text() == "done"
            assert result.stdout.encode("utf-8", errors="surrogateescape") == stdout
            assert result.stderr.encode("utf-8", errors="surrogateescape") == stderr
            assert result.artifact_cleanup_error is None
            manager = session.session_manager
            if scenario in {"capacity_refused", "overflow"}:
                assert result.stdout_artifact_ref is None and result.stderr_artifact_ref is None
                assert result.artifact_retention_error is not None
            else:
                assert result.stdout_artifact_ref is not None and result.stderr_artifact_ref is not None
                with manager._lifecycle_session.sync_operation_scope():
                    assert service._store.read_bytes(result.stdout_artifact_ref) == stdout
                    assert service._store.read_bytes(result.stderr_artifact_ref) == stderr
            assert factory._leases and all(lease._closed for lease in factory._leases.values() if lease is not held)
        finally:
            await runtime.dispose_session_runtime()
            await factory.close()
        assert not factory.cleanup_pending

    asyncio.run(run())
    assert all(native.budget.lookup(allocation) is None for allocation in native.allocations)
