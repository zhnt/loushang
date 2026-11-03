from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from loushang.coding import hosted_catalog as module
from loushang.coding.hosted_catalog import (
    CodingHostedCatalogError,
    CodingHostedSessionCatalogV1,
)
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_hosted_catalog import _intent, _scope

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned hosted transcripts")


def catalog(tmp_path):
    scope = _scope(tmp_path)
    scope.session_dir.mkdir(mode=0o700, exist_ok=True)
    return CodingHostedSessionCatalogV1((scope,), owned_transcripts=True), scope


def test_owned_catalog_real_create_busy_resume_and_close_preserves_delivered_candidate(tmp_path):
    async def scenario():
        first, scope = catalog(tmp_path)
        second, _ = catalog(tmp_path)
        candidate = await first.create_candidate(_intent(scope))
        manager = candidate._binding.manager_for_construction()
        assert manager._lifecycle_session._writer_owner is not None
        await first.close()
        assert not manager._lifecycle_session._writer_owner.closing
        with pytest.raises(TranscriptWriterError, match="busy"):
            await second.find_created_candidate(_intent(scope).request)
        assert not second._owned_factory.pending_preparations
        with pytest.raises(CodingHostedCatalogError):
            await manager.fork("unused")
        await candidate.close()
        resumed = await second.find_created_candidate(_intent(scope).request)
        assert resumed is not None and resumed.projection.envelope == candidate.projection.envelope
        await resumed.close()
        await second.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["manager", "candidate"])
def test_owned_catalog_retains_raw_session_when_wrapper_and_cleanup_fail(tmp_path, monkeypatch, stage):
    async def scenario():
        owner, scope = catalog(tmp_path)
        runtime = module.CODING_TRANSCRIPT_RUNTIME

        def fail(*args, **kwargs):
            raise ValueError("test wrapper failed")

        async def failed_cleanup(binding):
            raise OSError("test cleanup unavailable")

        with monkeypatch.context() as patch:
            patch.setattr(module, "_OwnedHostedTranscript" if stage == "manager" else "_Candidate", fail)
            patch.setattr(runtime._binder, "dispose", failed_cleanup)
            with pytest.raises(ValueError, match="wrapper failed") as failure:
                await owner.create_candidate(_intent(scope))
            retained, = owner.pending_sessions
            assert "cleanup retained" in failure.value.__notes__[0]
            assert not owner._owned_factory.pending_preparations
            with pytest.raises(OSError, match="cleanup unavailable"):
                await owner.close()
            assert owner.pending_sessions == (retained,)
            assert owner._owned_factory._closing
        await owner.close()
        assert not owner.pending_sessions
        fresh, _ = catalog(tmp_path)
        candidate = await fresh.find_created_candidate(_intent(scope).request)
        await candidate.close()
        await fresh.close()

    asyncio.run(scenario())


def test_owned_catalog_close_fences_inflight_factory_before_waiting_lock(tmp_path, monkeypatch):
    async def scenario():
        owner, scope = catalog(tmp_path)
        lifecycle = owner._owned_factory._lifecycle
        bind = lifecycle._bind_runtime_owned
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(*args):
            result = await bind(*args)
            entered.set()
            await release.wait()
            return result

        monkeypatch.setattr(lifecycle, "_bind_runtime_owned", delayed)
        caller = asyncio.create_task(owner.create_candidate(_intent(scope)))
        closing = None
        try:
            await asyncio.wait_for(entered.wait(), 5)
            preparation, = owner._owned_factory.pending_preparations
            closing = asyncio.create_task(owner.close())
            await asyncio.sleep(0)
            assert owner._closing and preparation.closing
            assert not closing.done()
            release.set()
            with pytest.raises((RuntimeError, TranscriptWriterError)):
                await caller
            await closing
            assert not owner.pending_sessions and not owner._owned_factory.pending_preparations
        finally:
            release.set()
            await asyncio.gather(caller, *([closing] if closing else []), return_exceptions=True)
            await owner.close()

    asyncio.run(scenario())


def test_owned_catalog_does_not_publish_pathname_index_on_disposal(tmp_path, monkeypatch):
    async def scenario():
        owner, scope = catalog(tmp_path)
        candidate = await owner.create_candidate(_intent(scope))

        def forbidden(*args, **kwargs):
            raise AssertionError("owned wrapper used pathname aggregate index")

        from loushang.harness.transcript import product_session
        monkeypatch.setattr(product_session, "AgentTranscriptSessionCatalog", forbidden)
        manager = candidate._binding.manager_for_construction()
        await manager.publish_index_summary()
        await candidate.close()
        await owner.close()

    asyncio.run(scenario())


def test_owned_catalog_requires_prepared_safe_session_root(tmp_path):
    async def scenario():
        scope = _scope(tmp_path)
        owner = CodingHostedSessionCatalogV1((scope,), owned_transcripts=True)
        with pytest.raises(TranscriptWriterError):
            await owner.create_candidate(_intent(scope))
        assert not scope.session_dir.exists()
        await owner.close()

    asyncio.run(scenario())


def test_owned_catalog_real_process_busy_then_reopen(tmp_path):
    script = """
import asyncio, sys
from pathlib import Path
from loushang.apphost import SessionCreateRequestV1
from loushang.appserver.protocol import SessionScopeV1
from loushang.coding.hosted_catalog import CodingHostedScopeV1, CodingHostedSessionCatalogV1
from loushang.harness.transcript.writer_lease import TranscriptWriterError
async def main():
    root = Path(sys.argv[1])
    scope = CodingHostedScopeV1(SessionScopeV1.CWD, root / 'cwd', root)
    owner = CodingHostedSessionCatalogV1((scope,), owned_transcripts=True)
    try:
        try:
            candidate = await owner.find_created_candidate(SessionCreateRequestV1(
                'coding', scope.fingerprint, 'a' * 32,
                requested_continuity_id='continuity-1', requested_scope=scope.discovery_scope))
        except TranscriptWriterError as error:
            assert 'busy' in str(error)
            print('busy')
        else:
            assert candidate is not None
            await candidate.close()
            print('opened')
    finally:
        await owner.close()
asyncio.run(main())
"""

    async def scenario():
        owner, scope = catalog(tmp_path)
        candidate = await owner.create_candidate(_intent(scope))

        def child():
            result = subprocess.run(
                [sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, timeout=20,
            )
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

        try:
            assert await asyncio.to_thread(child) == "busy"
            assert not candidate._binding.manager_for_construction()._lifecycle_session._writer_owner.closing
        finally:
            await candidate.close()
            await owner.close()
        assert await asyncio.to_thread(child) == "opened"

    asyncio.run(scenario())
