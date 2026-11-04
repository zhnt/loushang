"""Failed current-Session Goal attachment preserves original execution owners."""
import asyncio
from pathlib import Path

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.coding import create_agent_session_runtime
from loushang.coding.adapters._goal_store import goal_journal_path
from loushang.coding.adapters.goal import CodingGoal
from loushang.coding.adapters.harnesswork import create_coding_work_runtime
from loushang.harness.session.execution_admission import SessionExecutionUnavailable
from loushang.harnesswork import InMemoryEventLogBackend
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.types import WorkRecordingPolicy

from .test_current_session_goal import _model, _PreparedAdapter
from .test_work_shell import _goal_project


@pytest.mark.parametrize("conflict", ["ordinary_call", "memory_backend"])
def test_failed_attach_keeps_original_session_execution_and_backend(tmp_path, monkeypatch, conflict):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        if conflict != "ordinary_call":
            release.set()

        class Adapter(_PreparedAdapter):
            async def invoke_prepared_raw(self, request, prepared):
                entered.set()
                await release.wait()
                async for event in super().invoke_prepared_raw(request, prepared):
                    yield event

        adapter = Adapter()
        registry = get_default_api_registry()
        registry.register_api_adapter(adapter, source_id=adapter.api)
        sdk = create_agent_session_runtime(
            session_dir=tmp_path / "data/sessions", model=_model(), enable_multiagent=False,
            active_tool_names=["read", "edit", "write"],
        )
        prompt = None
        try:
            session = await sdk.create_session(cwd=str(_goal_project(tmp_path)))
            backend = None
            if conflict == "ordinary_call":
                prompt = asyncio.create_task(session.prompt("ordinary in flight"))
                await asyncio.wait_for(entered.wait(), 10)
                with pytest.raises(SessionExecutionUnavailable):
                    await CodingGoal.attach(session=session)
                assert not prompt.done() and session.is_streaming
            else:
                backend = create_coding_work_runtime(
                    session=session, event_log=InMemoryEventLogBackend(),
                    recording_policy=WorkRecordingPolicy(),
                )
                with pytest.raises(GoalError, match="incompatible"):
                    await CodingGoal.attach(session=session)
            assert session.work_execution_backend is backend
            assert session.runtime.execution_scope is None
            assert not session.runtime.execution_admission.closed
            assert not goal_journal_path(Path(session.session_manager.get_session_dir()), session.session_id).exists()
            release.set()
            if prompt is not None:
                await asyncio.wait_for(prompt, 10)
            await session.prompt("ordinary still works")
            assert len(adapter.tools) == (2 if prompt is not None else 1)
        finally:
            release.set()
            if prompt is not None:
                await asyncio.gather(prompt, return_exceptions=True)
            await sdk.dispose_session_runtime()
            registry.unregister_api_adapters(adapter.api)

    asyncio.run(scenario())
