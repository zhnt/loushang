from __future__ import annotations

import asyncio
import sys

import pytest

from loushang.harness.session import (
    ForkProfile,
    ForkSelection,
    ProductSessionRuntime,
    ProductSessionRuntimePorts,
    ProductTranscriptSessionBinding,
    SessionLifecycleHooks,
)
from tests.harness.transcript.test_owned_product_delivery import product
from tests.harness.transcript.test_owned_session_factory import factory
from tests.harness.transcript.test_runtime_profile import _runtime
from tests.harness.transcript.test_writer_lease import busy, lease

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned construction")


@pytest.mark.parametrize("graph", [False, True])
def test_actual_runtime_shutdown_retains_failed_product_construction(tmp_path, monkeypatch, graph):
    async def scenario():
        profile = _runtime("coding")
        selected, calls = factory(runtime=profile), []
        Bound = product(selected, calls)
        binding = ProductTranscriptSessionBinding(
            session_type=Bound, session_dir=tmp_path, persist=True, resolve_cwd_override=str,
        )
        failure = ValueError("Product construction failed")

        def build(transcript, current, transition):
            if graph:
                transcript._lifecycle_session._begin_graph_construction()
                transcript._lifecycle_session._commit_graph_ownership()
            raise failure

        runtime = ProductSessionRuntime(
            session_dir=tmp_path,
            ports=ProductSessionRuntimePorts(
                session_factory=lambda manager: manager, persist=True,
                create_transcript=lambda cwd, parent: Bound.new(tmp_path, cwd, session_id="conversation-1"),
                restore_transcript=binding.restore, fork_transcript=binding.fork,
                dispose_transcript=binding.dispose, transcript_for_session=lambda value: value,
                transcript_cwd=lambda value: value.cwd, transcript_session_ref=lambda value: str(value.session_file),
                transcript_leaf_entry_id=lambda value: value.leaf_id, build_session=build,
                validate_restored_transcript=None,
                fork_profile=ForkProfile(default_position="at", supported_positions=frozenset({"at"})),
                fork_target_resolver=lambda session, entry, position: ForkSelection(target_entry_id=entry),
                hooks=SessionLifecycleHooks(dispose_session=binding.dispose),
            ),
        )

        async def unavailable(value):
            raise OSError("runtime disposal unavailable")

        try:
            with monkeypatch.context() as patch:
                if not graph:
                    patch.setattr(profile._binder, "dispose", unavailable)
                with pytest.raises(ValueError) as result:
                    await runtime.create_session(cwd=str(tmp_path))
                assert result.value is failure and "cleanup retained" in failure.__notes__[0]
                retained, = runtime._transcript_construction_store.pending_transcripts
                assert retained._lifecycle_session is calls[0]
                assert not retained.runtime_disposed and not selected.pending_preparations
                busy(tmp_path, conversation="conversation-1")
                with pytest.raises((OSError, RuntimeError)):
                    await runtime.dispose_session_runtime()
                assert runtime._transcript_construction_store.pending_transcripts == (retained,)
                busy(tmp_path, conversation="conversation-1")
            if graph:
                await calls[0]._dispose_graph_owned()
            await runtime.dispose_session_runtime()
            assert retained.runtime_disposed
            assert not runtime._transcript_construction_store.pending_transcripts
            reopened = lease(tmp_path, conversation="conversation-1")
            try:
                reopened.acquire()
            finally:
                reopened.close()
        finally:
            if graph and calls and calls[0].ownership_state == "graph_owned":
                await calls[0]._dispose_graph_owned()
            await runtime.dispose_session_runtime()
            await selected.close()

    asyncio.run(scenario())


def test_actual_runtime_close_waits_for_started_builder_and_disposes_late_session(tmp_path):
    async def scenario():
        selected, calls = factory(runtime=_runtime("coding")), []
        Bound = product(selected, calls)
        binding = ProductTranscriptSessionBinding(
            session_type=Bound, session_dir=tmp_path, persist=True, resolve_cwd_override=str,
        )
        entered, release, closing = asyncio.Event(), asyncio.Event(), asyncio.Event()
        disposed = []

        async def build(transcript, current, transition):
            transcript._lifecycle_session._begin_graph_construction()
            transcript._lifecycle_session._commit_graph_ownership()
            entered.set()
            await release.wait()
            return transcript

        async def dispose(transcript):
            await transcript._lifecycle_session._dispose_graph_owned()
            disposed.append(transcript)

        runtime = ProductSessionRuntime(
            session_dir=tmp_path,
            ports=ProductSessionRuntimePorts(
                session_factory=lambda manager: manager, persist=True,
                create_transcript=lambda cwd, parent: Bound.new(tmp_path, cwd, session_id="conversation-1"),
                restore_transcript=binding.restore, fork_transcript=binding.fork,
                dispose_transcript=binding.dispose, transcript_for_session=lambda value: value,
                transcript_cwd=lambda value: value.cwd, transcript_session_ref=lambda value: str(value.session_file),
                transcript_leaf_entry_id=lambda value: value.leaf_id, build_session=build,
                validate_restored_transcript=None,
                fork_profile=ForkProfile(default_position="at", supported_positions=frozenset({"at"})),
                fork_target_resolver=lambda session, entry, position: ForkSelection(target_entry_id=entry),
                hooks=SessionLifecycleHooks(dispose_session=dispose),
            ),
        )

        async def close():
            closing.set()
            await runtime.dispose_session_runtime()

        creation = asyncio.create_task(runtime.create_session(cwd=str(tmp_path)))
        shutdown = None
        try:
            await asyncio.wait_for(entered.wait(), 5)
            shutdown = asyncio.create_task(close())
            await asyncio.wait_for(closing.wait(), 5)
            assert not shutdown.done()
            assert runtime._transcript_construction_store.pending_transcripts
            busy(tmp_path, conversation="conversation-1")
            release.set()
            result = await asyncio.wait_for(creation, 5)
            await asyncio.wait_for(shutdown, 5)
            assert disposed == [result] and result.runtime_disposed
            assert runtime.current_session is None
            assert not runtime._transcript_construction_store.pending_transcripts
            assert not selected.pending_preparations
            reopened = lease(tmp_path, conversation="conversation-1")
            try:
                reopened.acquire()
            finally:
                reopened.close()
        finally:
            release.set()
            await asyncio.gather(creation, *([shutdown] if shutdown else []), return_exceptions=True)
            await runtime.dispose_session_runtime()
            await selected.close()

    asyncio.run(scenario())
