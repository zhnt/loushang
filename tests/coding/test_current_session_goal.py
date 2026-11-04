"""Current Session Goal uses original history, transport and lifecycle."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.coding import create_agent_session_runtime
from loushang.coding.adapters.goal import CodingGoal, inspect_session_goal
from loushang.harnesswork.goal import GoalError

from .test_work_shell import _goal_project, _planning_proposal


class _PreparedAdapter:
    api = "current-session-goal-offline-contract"

    def __init__(self):
        self.tools = []

    def prepare_request(self, request):
        return PreparedModelRequest.from_provider_request(request, payload={
            "system": request.context.system_prompt,
            "messages": [serialize_message(m) for m in request.context.messages],
            "tools": [t.name for t in request.context.tools or ()],
            "model": request.model.id,
        })

    async def invoke_prepared_raw(self, request, prepared):
        prepared.payload_for_transport()
        self.tools.append(tuple(t.name for t in request.context.tools or ()))
        raw = json.dumps(_planning_proposal(
            next_action="inspect", expected_evidence=["goal_inspection_report"],
            remaining_route=[{"action": "inspect", "targets": ["subtraction"]}],
        ))
        yield {"type": "response_start", "response_id": f"reply-{len(self.tools)}"}
        yield {"type": "text_delta", "text": raw}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}

    async def invoke_raw(self, request):
        async for event in self.invoke_prepared_raw(request, self.prepare_request(request)):
            yield event


def _model():
    return Model(id="current-goal", provider="offline", endpoint="offline", api=_PreparedAdapter.api,
                 base_url="https://unused.invalid", auth=Auth(kind="none"),
                 capabilities=Capabilities(input=("text",), output=("text",), context_window=128000,
                                           stream=True, tool_use=True))


@pytest.mark.parametrize("stream_kind", ["default", "standard", "declared"])
@pytest.mark.parametrize("existing_backend", [False, True])
def test_current_session_goal_preserves_history_configuration_and_original_transport(tmp_path, monkeypatch, stream_kind, existing_backend):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    adapter = _PreparedAdapter()
    registry = get_default_api_registry()
    registry.register_api_adapter(adapter, source_id=adapter.api)

    async def scenario():
        from loushang.agent import prepared_request_conformant
        from loushang.ai.api import stream

        @prepared_request_conformant
        async def declared(model, context, options=None):
            return await stream(model, context, options)

        sdk = create_agent_session_runtime(
            session_dir=tmp_path / "data/custom-history", model=_model(),
            stream_fn={"default": None, "standard": stream, "declared": declared}[stream_kind],
            active_tool_names=["read", "edit", "write", "bash"],
            allowed_tool_names=["read", "edit", "write", "bash"],
            enable_multiagent=False, system_prompt="Original ordinary chat instructions.",
        )
        owner = None
        try:
            session = await sdk.create_session(cwd=str(_goal_project(tmp_path)))
            await session.prompt("ordinary input before Goal")
            assert len(adapter.tools) == 1
            manager, agent = session.session_manager, session.runtime.agent
            old_ids = tuple(r.record_id for r in manager.get_branch())
            baseline = (agent.stream_fn, session.model, session.system_prompt,
                        tuple(session.get_active_tool_names()), session.auto_retry_enabled,
                        session.auto_compaction_enabled)
            original_id, original_file = session.session_id, manager.get_session_file()
            prior_backend = None
            if existing_backend:
                from loushang.coding.adapters._goal_store import goal_journal_path
                from loushang.coding.adapters.harnesswork import (
                    create_coding_work_runtime,
                )
                from loushang.harnesswork import JsonlEventLogBackend
                from loushang.harnesswork.types import WorkRecordingPolicy

                prior_backend = create_coding_work_runtime(
                    session=session,
                    event_log=JsonlEventLogBackend(goal_journal_path(
                        Path(manager.get_session_dir()), session.session_id,
                    ).with_suffix(".work.jsonl")),
                    recording_policy=WorkRecordingPolicy(),
                )
            owner = await CodingGoal.attach(session=session)
            assert owner._session is session and owner._sdk is None
            assert owner._journal_directory == Path(manager.get_session_dir()).resolve()
            owner.create("g", command_id="create")
            scope = session.runtime.execution_scope
            with pytest.raises(RuntimeError, match="execution scope"):
                await CodingGoal.attach(session=session)
            assert session.runtime.execution_scope is scope and not scope.closing
            receipt = await owner.advance("g", command_id="plan", revision=1, epoch=1)
            assert receipt.outcome == "work_finished", owner.controller.last_error
            assert owner._allowance.total_calls == 1 and len(adapter.tools) == 2
            assert not adapter.tools[-1]
            trace = owner.planning_trace("g")
            assert trace["status"] == "known" and trace["consecutive_invalid"] == 0, trace
            assert len(trace["routes"]) == 1, trace
            assert tuple(r.record_id for r in manager.get_branch())[:len(old_ids)] == old_ids
            backend = session.work_execution_backend
            assert backend is owner._session_work and owner._work is backend.work_runtime
            if prior_backend is not None:
                assert backend is prior_backend
            await owner.close()
            cold = inspect_session_goal(session=session, goal_id="g")
            assert cold.planning == trace
            assert not session.runtime.execution_admission.closed
            assert session.session_id == original_id and manager.get_session_file() == original_file
            assert (agent.stream_fn, session.model, session.system_prompt,
                    tuple(session.get_active_tool_names()), session.auto_retry_enabled,
                    session.auto_compaction_enabled) == baseline
            await session.prompt("ordinary input after Goal")
            assert len(adapter.tools) == 3 and adapter.tools[-1] == adapter.tools[0]
            assert owner._allowance.total_calls == 1
            with pytest.raises(GoalError, match="original execution owner"):
                await CodingGoal.attach(session=session)
            await session.prompt("still usable after rejected reattach")
            assert len(adapter.tools) == 4
        finally:
            if owner is not None:
                await owner.close()
            await sdk.dispose_session_runtime()

    try:
        asyncio.run(scenario())
    finally:
        registry.unregister_api_adapters(adapter.api)


def test_current_goal_refuses_changed_transport_without_restoring_old_baseline(tmp_path, monkeypatch):
    from loushang.agent import prepared_request_conformant
    from loushang.ai.api import stream

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    adapter = _PreparedAdapter()
    registry = get_default_api_registry()
    registry.register_api_adapter(adapter, source_id=adapter.api)

    async def scenario():
        sdk = create_agent_session_runtime(
            session_dir=tmp_path / "data/sessions", model=_model(), enable_multiagent=False,
            active_tool_names=["read", "edit", "write"],
        )
        owner = None
        changed_calls = []

        @prepared_request_conformant
        async def changed(model, context, options=None):
            changed_calls.append(context)
            return await stream(model, context, options)

        try:
            session = await sdk.create_session(cwd=str(_goal_project(tmp_path)))
            owner = await CodingGoal.attach(session=session)
            owner.create("g", command_id="create")
            session.runtime.agent.stream_fn = changed
            receipt = await owner.advance("g", command_id="plan", revision=1, epoch=1)
            assert receipt.outcome == "paused"
            batch = owner.controller.history.batches[-1]
            assert owner._work.get_run_for_operation(batch.operation_id).status == "failed"
            assert owner._allowance.total_calls == 0 and not changed_calls and not adapter.tools
            await owner.close()
            assert session.runtime.agent.stream_fn is changed
            await session.prompt("ordinary input uses new transport")
            assert len(changed_calls) == 1 and len(adapter.tools) == 1
            assert owner._allowance.total_calls == 0
        finally:
            if owner is not None:
                await owner.close()
            await sdk.dispose_session_runtime()

    try:
        asyncio.run(scenario())
    finally:
        registry.unregister_api_adapters(adapter.api)


def test_public_direct_application_message_cannot_enter_committed_planning_input(tmp_path, monkeypatch):
    from loushang.harness.session.execution_admission import SessionExecutionUnavailable

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    adapter = _PreparedAdapter()
    registry = get_default_api_registry()
    registry.register_api_adapter(adapter, source_id=adapter.api)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        sdk = create_agent_session_runtime(
            session_dir=tmp_path / "data/sessions", model=_model(), enable_multiagent=False,
            active_tool_names=["read", "edit", "write"],
        )
        owner = advancing = None
        try:
            session = await sdk.create_session(cwd=str(_goal_project(tmp_path)))
            await session.prompt("ordinary context")
            owner = await CodingGoal.attach(session=session)
            owner.create("g", command_id="create")
            original_prepare = session.prepare_model_call_runtime

            async def prepare():
                entered.set()
                await release.wait()
                await original_prepare()

            monkeypatch.setattr(session, "prepare_model_call_runtime", prepare)
            advancing = asyncio.create_task(owner.advance("g", command_id="plan", revision=1, epoch=1))
            await asyncio.wait_for(entered.wait(), 10)
            assert session.runtime.execution_admission.execution_reserved and not session.is_streaming
            transcript = Path(session.session_manager.get_session_file())
            before = transcript.read_bytes()
            message = {"customType": "external_direct", "content": "ordinary application notice"}
            with pytest.raises(SessionExecutionUnavailable):
                await session.send_message(message)
            assert transcript.read_bytes() == before and owner._allowance.total_calls == 0
            release.set()
            assert (await advancing).outcome == "work_finished"
            trace = owner.planning_trace("g")
            assert trace["status"] == "known" and trace["consecutive_invalid"] == 0
            assert len(trace["routes"]) == 1 and owner._allowance.total_calls == 1
            await owner.close()
            await session.send_message(message)
            assert sum(getattr(record.payload, "custom_type", None) == "external_direct"
                       for record in session.session_manager.get_branch()) == 1
            assert inspect_session_goal(session=session, goal_id="g").planning == trace
            assert len(adapter.tools) == 2 and owner._allowance.total_calls == 1
        finally:
            release.set()
            if advancing is not None:
                await asyncio.gather(advancing, return_exceptions=True)
            if owner is not None:
                await owner.close()
            await sdk.dispose_session_runtime()

    try:
        asyncio.run(scenario())
    finally:
        registry.unregister_api_adapters(adapter.api)
