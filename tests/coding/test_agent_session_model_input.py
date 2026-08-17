from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from loushang.agent import (
    Agent,
    prepared_request_conformant,
    synthetic_model_transport,
)
from loushang.agent.agent_loop import run_agent_loop
from loushang.agent.types import AgentContext, AgentToolResult
from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.provider.protocol import ProviderRequest
from loushang.ai.types import TextPart, UserMessage
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry


class _CodingPreparedAdapter:
    api = "coding-session-model-input-test"

    def __init__(self, *, tool_first: bool = False) -> None:
        self.transport_calls = 0
        self.tool_first = tool_first

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "system": request.context.system_prompt,
                "messages": [
                    serialize_message(message) for message in request.context.messages
                ],
                "tools": [tool.name for tool in request.context.tools or ()],
                "model": request.model.id,
            },
        )

    async def invoke_prepared_raw(
        self,
        request: ProviderRequest,
        prepared: PreparedModelRequest,
    ) -> AsyncIterator[dict[str, object]]:
        del request
        self.transport_calls += 1
        prepared.payload_for_transport()
        if self.tool_first and self.transport_calls == 1:
            yield {"type": "response_start", "response_id": "coding-tool"}
            yield {"type": "tool_call_start", "id": "tool-1", "name": "echo"}
            yield {"type": "tool_call_args_delta", "delta": '{"value":"hello"}'}
            yield {"type": "tool_call_done"}
            yield {"type": "response_done"}
            return
        yield {"type": "response_start", "response_id": "coding-response"}
        yield {"type": "text_delta", "text": "done"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}

    async def invoke_raw(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[dict[str, object]]:
        prepared = self.prepare_request(request)
        async for part in self.invoke_prepared_raw(request, prepared):
            yield part


def _model(*, api: str) -> Model:
    return Model(
        id="coding-session-model-input",
        provider="coding-test",
        endpoint="coding-test",
        api=api,
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(
            input=("text",),
            output=("text",),
            context_window=8192,
            stream=True,
            tool_use=True,
        ),
    )


def test_coding_session_routes_main_call_through_model_input_capability(
    tmp_path,
) -> None:
    async def scenario() -> None:
        adapter = _CodingPreparedAdapter()
        registry = get_default_api_registry()
        source_id = "coding-session-model-input-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        session = AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "coding durable prompt",
                    "model": _model(api=adapter.api),
                    "thinking_level": "off",
                }
            ),
            session_manager=manager,
        )
        try:
            await session.prompt("hello")
            assert adapter.transport_calls == 1
            snapshots = [
                entry.payload
                for entry in manager.get_entries()
                if entry.kind == "model.input.prepared"
            ]
            assert len(snapshots) == 1
            rebuilt = manager.rebuild_model_input(snapshots[0].snapshot_id)
            assert rebuilt.snapshot.purpose == "main"
            assert rebuilt.logical_input["system_prompt"] == "coding durable prompt"
            assert rebuilt.logical_input["messages"][0]["content"][0]["text"] == (
                "hello"
            )
            assert rebuilt.prepared_payload["model"] == (
                "coding-session-model-input"
            )
        finally:
            registry.unregister_api_adapters(source_id)
            await session.dispose()

    asyncio.run(scenario())


def test_side_question_commits_hidden_model_input_to_parent_transcript(
    tmp_path,
) -> None:
    async def scenario() -> None:
        adapter = _CodingPreparedAdapter()
        registry = get_default_api_registry()
        source_id = "coding-side-question-model-input-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        session = AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "coding durable prompt",
                    "model": _model(api=adapter.api),
                    "thinking_level": "off",
                }
            ),
            session_manager=manager,
        )
        try:
            await session.prompt("hello")
            answer = await session.ask_side_question("what is the status?")
            assert answer.text == "done"
            snapshots = [
                entry.payload
                for entry in manager.get_entries()
                if entry.kind == "model.input.prepared"
            ]
            assert [snapshot.purpose for snapshot in snapshots] == [
                "main",
                "side_question",
            ]
            rebuilt = manager.rebuild_model_input(snapshots[-1].snapshot_id)
            side_prompt = rebuilt.logical_input["messages"][-1]["content"][0]["text"]
            assert "one-shot side question" in side_prompt
            assert "what is the status?" in side_prompt
        finally:
            registry.unregister_api_adapters(source_id)
            await session.dispose()

    asyncio.run(scenario())


def test_tool_result_commit_precedes_tool_continuation_model_input(tmp_path) -> None:
    async def execute_echo(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, signal, on_update
        return AgentToolResult(
            content=[TextPart(type="text", text=str(params["value"]))]
        )

    async def scenario() -> None:
        adapter = _CodingPreparedAdapter(tool_first=True)
        registry = get_default_api_registry()
        source_id = "coding-tool-continuation-model-input-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        tool_registry = WorkspaceToolRegistry()
        tool_registry.register_tool(
            ToolDefinition(
                name="echo",
                description="Echo one value",
                parameters={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
                label="Echo",
                execution=direct_execution(execute_echo),
                execution_mode="sequential",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        session = AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "coding durable prompt",
                    "model": _model(api=adapter.api),
                    "thinking_level": "off",
                },
                tool_execution="sequential",
            ),
            session_manager=manager,
            tool_registry=tool_registry,
            active_tool_names=["echo"],
        )
        try:
            await session.prompt("use echo")
            entries = manager.get_entries()
            snapshots = [
                entry.payload
                for entry in entries
                if entry.kind == "model.input.prepared"
            ]
            assert adapter.transport_calls == 2, session.agent.state.messages[-1]
            assert [snapshot.purpose for snapshot in snapshots] == [
                "main",
                "tool_continuation",
            ]
            tool_result_position = next(
                index
                for index, entry in enumerate(entries, start=1)
                if getattr(entry.payload, "role", None) == "toolResult"
            )
            assert tool_result_position <= snapshots[1].source_revision
            rebuilt = manager.rebuild_model_input(snapshots[1].snapshot_id)
            assert rebuilt.logical_input["messages"][-1]["role"] == "toolResult"
        finally:
            registry.unregister_api_adapters(source_id)
            await session.dispose()

    asyncio.run(scenario())


def test_queued_continuation_uses_fresh_model_input_invocation(tmp_path) -> None:
    async def scenario() -> None:
        adapter = _CodingPreparedAdapter()
        registry = get_default_api_registry()
        source_id = "coding-queued-continuation-model-input-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        session = AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "coding durable prompt",
                    "model": _model(api=adapter.api),
                    "thinking_level": "off",
                }
            ),
            session_manager=manager,
        )
        try:
            await session.prompt("first")
            session.follow_up("second")
            await session.continue_run()
            snapshots = [
                entry.payload
                for entry in manager.get_entries()
                if entry.kind == "model.input.prepared"
            ]
            assert [snapshot.purpose for snapshot in snapshots] == [
                "main",
                "continuation",
            ]
            assert len({snapshot.invocation_id for snapshot in snapshots}) == 2
            assert snapshots[1].source_revision > snapshots[0].source_revision
            rebuilt = manager.rebuild_model_input(snapshots[1].snapshot_id)
            assert rebuilt.logical_input["messages"][-1]["content"][0]["text"] == (
                "second"
            )
        finally:
            registry.unregister_api_adapters(source_id)
            await session.dispose()

    asyncio.run(scenario())


def test_product_retry_scheduler_uses_fresh_model_input_invocation(tmp_path) -> None:
    async def scenario() -> None:
        adapter = _CodingPreparedAdapter()
        registry = get_default_api_registry()
        source_id = "coding-product-retry-model-input-test"
        registry.register_api_adapter(adapter, source_id=source_id)
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        session = AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "coding durable prompt",
                    "model": _model(api=adapter.api),
                    "thinking_level": "off",
                }
            ),
            session_manager=manager,
        )
        try:
            await session.prompt("first")
            retry_input = UserMessage(
                role="user",
                content=[TextPart(type="text", text="retry input")],
                timestamp=2.0,
            )
            await manager.append_message(retry_input)
            session.agent.state.set_messages(
                list(manager.build_session_context().messages)
            )
            await session._composition.session_runtime.schedule_continue_run(
                model_call_purpose="retry"
            )
            snapshots = [
                entry.payload
                for entry in manager.get_entries()
                if entry.kind == "model.input.prepared"
            ]
            assert [snapshot.purpose for snapshot in snapshots] == ["main", "retry"]
            assert len({snapshot.invocation_id for snapshot in snapshots}) == 2
            assert snapshots[1].source_revision > snapshots[0].source_revision
            rebuilt = manager.rebuild_model_input(snapshots[1].snapshot_id)
            assert rebuilt.logical_input["messages"][-1]["content"][0]["text"] == (
                "retry input"
            )
        finally:
            registry.unregister_api_adapters(source_id)
            await session.dispose()

    asyncio.run(scenario())


def test_durable_session_rejects_unconstrained_custom_stream(tmp_path) -> None:
    async def custom_stream(model, context, options=None):
        del model, context, options
        raise AssertionError("transport must not start")

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=True,
        )
        try:
            with pytest.raises(ValueError, match="prepared_request_conformant"):
                AgentSession(
                    agent=Agent(stream_fn=custom_stream),
                    session_manager=manager,
                )
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_durable_session_rechecks_replaced_transport_before_sampling(tmp_path) -> None:
    transport_calls = 0

    async def custom_stream(model, context, options=None):
        nonlocal transport_calls
        del model, context, options
        transport_calls += 1
        raise AssertionError("transport must not start")

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=True,
        )
        agent = Agent()
        session = AgentSession(agent=agent, session_manager=manager)
        agent.stream_fn = custom_stream
        try:
            async def emit(event):
                del event

            with pytest.raises(ValueError, match="prepared_request_conformant"):
                await run_agent_loop(
                    [
                        UserMessage(
                            role="user",
                            content="must remain durable",
                            timestamp=1.0,
                        )
                    ],
                    AgentContext(system_prompt="", messages=[]),
                    agent._create_loop_config(),
                    emit,
                    stream_fn=agent.stream_fn,
                )
            assert transport_calls == 0
            assert all(
                entry.kind != "model.input.prepared" for entry in manager.get_entries()
            )
        finally:
            await session.dispose()

    asyncio.run(scenario())


def test_session_dispose_restores_exact_agent_model_call_boundary(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        agent = Agent()
        session = AgentSession(agent=agent, session_manager=manager)
        assert callable(agent.prepare_model_call)

        await session.dispose()
        assert agent.prepare_model_call is None
        assert agent.model_transport_requires_prepared_request_conformance is False

        def replacement(preparation):
            return preparation.options

        manager = await SessionManager.new(
            session_dir=tmp_path / "replacement",
            cwd=str(tmp_path),
            persist=False,
        )
        session = AgentSession(agent=agent, session_manager=manager)
        agent.prepare_model_call = replacement
        await session.dispose()
        assert agent.prepare_model_call is replacement

    asyncio.run(scenario())


def test_cancelled_session_dispose_finishes_model_call_cleanup(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        agent = Agent()
        session = AgentSession(agent=agent, session_manager=manager)
        original_dispose = session._capability_graph_binder.dispose
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_dispose(runtime) -> None:
            started.set()
            await release.wait()
            await original_dispose(runtime)

        session._capability_graph_binder.dispose = slow_dispose  # type: ignore[method-assign]
        task = asyncio.create_task(session.dispose())
        await started.wait()
        task.cancel()
        release.set()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert agent.prepare_model_call is None
        assert agent.model_transport_requires_prepared_request_conformance is False
        with pytest.raises(RuntimeError, match="has been disposed"):
            _ = session.capability_profile

    asyncio.run(scenario())


def test_side_question_cancel_failure_does_not_skip_model_call_cleanup(tmp_path) -> None:
    class _FailingCoordinator:
        async def cancel_and_wait(self) -> bool:
            raise RuntimeError("side-question cancel failed")

        def cancel(self) -> bool:
            return False

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        agent = Agent()
        session = AgentSession(agent=agent, session_manager=manager)
        session._side_question = _FailingCoordinator()  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="side-question cancel failed"):
            await session.dispose()
        assert agent.prepare_model_call is None
        with pytest.raises(RuntimeError, match="has been disposed"):
            _ = session.capability_profile

    asyncio.run(scenario())


def test_durable_session_accepts_declared_conformant_custom_stream(tmp_path) -> None:
    @prepared_request_conformant
    async def custom_stream(model, context, options=None):
        del model, context, options
        raise AssertionError("unused")

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=True,
        )
        session = AgentSession(
            agent=Agent(stream_fn=custom_stream),
            session_manager=manager,
        )
        await session.dispose()

    asyncio.run(scenario())


def test_durable_session_accepts_explicit_standard_ai_stream(tmp_path) -> None:
    from loushang.ai import stream

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=True,
        )
        session = AgentSession(
            agent=Agent(stream_fn=stream),
            session_manager=manager,
        )
        await session.dispose()

    asyncio.run(scenario())


def test_durable_session_accepts_explicit_synthetic_transport_opt_out(tmp_path) -> None:
    @synthetic_model_transport
    async def custom_stream(model, context, options=None):
        del model, context, options
        raise AssertionError("unused")

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=True,
        )
        session = AgentSession(
            agent=Agent(stream_fn=custom_stream),
            session_manager=manager,
        )
        assert session.agent.model_transport_is_explicitly_synthetic is True
        await session.dispose()

    asyncio.run(scenario())
