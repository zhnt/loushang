from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import replace
from datetime import date

from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import (
    Capabilities,
    Endpoint,
    Model,
    Provider,
)
from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage, UserMessage
from loushang.harness.tools.workspace import direct_tool


def _ai_model_registry(
    *models: Model,
    endpoints: tuple[Endpoint, ...] = (),
) -> AiModelRegistry:
    providers: dict[str, Provider] = {}
    for endpoint in endpoints:
        provider = providers.get(
            endpoint.provider_id, Provider(id=endpoint.provider_id)
        )
        provider_endpoints = dict(provider.endpoints)
        provider_endpoints[endpoint.id] = endpoint
        providers[provider.id] = replace(provider, endpoints=provider_endpoints)
    for model in models:
        provider = providers.get(model.provider_id, Provider(id=model.provider_id))
        endpoint = provider.endpoints.get(model.endpoint_id) or Endpoint(
            id=model.endpoint_id,
            provider=model.provider_id,
            api=model.api or model.endpoint_id,
        )
        endpoint_models = dict(endpoint.models)
        endpoint_models[model.id] = model
        provider_endpoints = dict(provider.endpoints)
        provider_endpoints[endpoint.id] = replace(endpoint, models=endpoint_models)
        providers[provider.id] = replace(provider, endpoints=provider_endpoints)
    return AiModelRegistry.from_providers(providers)


def _runtime_footer_lines(cwd: str) -> list[str]:
    return [
        f"Current date: {date.today().isoformat()}",
        f"Current working directory: {cwd}",
    ]


def _user_message(text: str) -> UserMessage:
    return UserMessage(
        role="user",
        content=[TextPart(type="text", text=text)],
        timestamp=0.0,
    )


def test_agent_session_restores_persisted_context_on_init(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding import AgentSession as PublicAgentSession
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="hi")],
                timestamp=0.0,
            )
        )
    )

    agent = Agent()
    session = AgentSession(agent=agent, session_manager=manager)

    assert PublicAgentSession is AgentSession
    assert [getattr(message, "role", None) for message in agent.state.messages] == [
        "user"
    ]
    assert [
        getattr(message, "role", None)
        for message in session.get_session_context().messages
    ] == ["user"]


def _usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost={},
    )


def _assistant_text_message(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def test_agent_session_composes_existing_transform_with_extension_context_without_mutating_state(
    tmp_path,
) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ContextResult,
        ExtensionRunner,
        LoadedExtension,
    )

    seen: list[str] = []

    async def _existing_transform(messages, signal):
        return messages + [_user_message("from-existing-transform")]

    def _extension_context(event, ctx):
        seen.append(event.messages[-1].content[0].text)
        return ContextResult(
            messages=event.messages + [_user_message("from-extension-context")]
        )

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd=str(project_dir), persist=False)
    )
    asyncio.run(manager.append_message(_user_message("persisted")))
    agent = Agent(transform_context=_existing_transform)
    session = AgentSession(
        agent=agent,
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="context",
                    source_path=tmp_path / "context.py",
                    hooks={"context": [_extension_context]},
                )
            ]
        ),
    )

    transformed = asyncio.run(
        session.agent.transform_context(session.agent.state.messages, None)
    )

    assert [message.content[0].text for message in transformed] == [
        "persisted",
        "from-existing-transform",
        "from-extension-context",
    ]
    assert [message.content[0].text for message in session.agent.state.messages] == [
        "persisted"
    ]
    assert [
        message.content[0].text for message in session.get_session_context().messages
    ] == ["persisted"]
    assert seen == ["from-existing-transform"]


def test_agent_session_binds_extension_runtime_state_context_methods(tmp_path) -> None:
    from pathlib import Path

    import pytest

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    runner = ExtensionRunner(
        [LoadedExtension(name="demo", source_path=Path("/tmp/extensions/demo.py"))]
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "system prompt",
                "model": Model(
                    id="tiny",
                    provider="faux",
                    endpoint="test",
                    capabilities=Capabilities(
                        input=("text",), context_window=10_000, max_tokens=1024
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=runner,
    )

    context = runner.create_command_context(fallback_cwd="/tmp/project")
    assert context.is_idle() is True
    assert context.has_pending_messages() is False
    assert context.get_system_prompt() == "system prompt"
    assert context.get_context_usage()["messageCount"] == 0

    with pytest.raises(ValueError, match="visible message entry"):
        asyncio.run(context.compact({"customInstructions": "no running loop"}))
    context.abort()
    session.steer("queued")
    assert context.has_pending_messages() is True


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _stream_with_final_message(
    message: AssistantMessage,
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def _feed() -> None:
        stream.push({"type": "start", "partial": message})
        stream.push({"type": "text_start", "content_index": 0, "partial": message})
        stream.push(
            {
                "type": "text_delta",
                "content_index": 0,
                "delta": message.content[0].text,
                "partial": message,
            }
        )
        stream.push(
            {
                "type": "text_end",
                "content_index": 0,
                "content": message.content[0].text,
                "partial": message,
            }
        )
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})  # type: ignore[typeddict-item]

    asyncio.create_task(_feed())
    return stream


def _stream_with_assistant_message(
    message: AssistantMessage,
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def _feed() -> None:
        stream.push({"type": "start", "partial": message})
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})  # type: ignore[typeddict-item]

    asyncio.create_task(_feed())
    return stream


def test_agent_session_prompt_persists_messages_and_forwards_events(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    event_types: list[str] = []

    async def stream_fn(model, context, options=None):
        return _stream_with_final_message(_assistant_text_message("hello"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        session = AgentSession(agent=agent, session_manager=manager)

        def listener(event) -> None:
            event_types.append(event["type"])

        session.subscribe(listener)
        await session.prompt("hi")

        assert [
            getattr(message, "role", None)
            for message in session.get_session_context().messages
        ] == ["user", "assistant"]
        assert [entry.kind for entry in manager.get_entries()] == [
            "agent.message",
            "agent.message",
        ]
        assert event_types[0] == "agent_start"
        assert event_types[-1] == "agent_end"

    asyncio.run(scenario())


def test_agent_session_abort_mid_stream_cleans_run_state_and_keeps_queued_messages(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    event_types: list[str] = []
    stream_started = asyncio.Event()

    async def stream_fn(model, context, options=None):
        del model, context
        stream = AssistantMessageEventStream()
        signal = getattr(options, "cancellation", None)
        partial = _assistant_text_message("partial")

        async def _feed() -> None:
            stream.push({"type": "start", "partial": partial})
            stream_started.set()
            while not getattr(signal, "aborted", False):
                await asyncio.sleep(0)
            stream.push(
                {
                    "type": "error",
                    "error": AssistantMessage(
                        endpoint="test-endpoint",
                        role="assistant",
                        content=[TextPart(type="text", text="")],
                        api="anthropic-messages",
                        provider="faux",
                        model="faux-model",
                        response_id=None,
                        usage=_usage(),
                        stop_reason="aborted",
                        error_message="aborted",
                        timestamp=0.0,
                    ),
                }
            )  # type: ignore[typeddict-item]

        asyncio.create_task(_feed())
        return stream

    async def scenario() -> AgentSession:
        session = AgentSession(
            agent=Agent(stream_fn=stream_fn),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
        )
        session.subscribe(lambda event: event_types.append(event["type"]))

        prompt_task = asyncio.create_task(session.prompt("hi"))
        await stream_started.wait()
        session.steer("queued after abort")
        session.abort()
        await prompt_task
        await asyncio.sleep(0)
        return session

    session = asyncio.run(scenario())

    assert session.agent.is_streaming is False
    assert session.get_state().run.status == "idle"
    assert session.get_state().steering == ["queued after abort"]
    assert session.agent.has_queued_messages() is True
    assert "agent_end" in event_types
    assert event_types[-1] == "agent_end"


def test_persisted_session_abort_tool_then_prompt_and_resume_keeps_revision_chain(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import ToolResultMessage
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.tools.core import ToolDefinition
    from loushang.harness.tools.execution import direct_execution
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

    tool_started = asyncio.Event()
    release_tool = asyncio.Event()

    async def execute_blocking(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        tool_started.set()
        await release_tool.wait()
        return AgentToolResult(content=[TextPart(type="text", text="unreachable")])

    registry = WorkspaceToolRegistry()
    registry.register_tool(
        ToolDefinition(
            name="blocking",
            description="Block until the run is aborted",
            parameters={"type": "object", "properties": {}},
            label="Blocking",
            execution=direct_execution(execute_blocking),
            execution_mode="sequential",
        )
    )

    async def stream_fn(model, context, options=None):
        del model, options
        last = context.messages[-1]
        text = last.content[0].text if isinstance(last, UserMessage) else ""
        if text == "use tool":
            return _stream_with_assistant_message(
                AssistantMessage(
                    endpoint="test-endpoint",
                    role="assistant",
                    content=[
                        ToolCall(
                            type="toolCall",
                            id="tool-1",
                            name="blocking",
                            arguments={},
                        )
                    ],
                    api="anthropic-messages",
                    provider="faux",
                    model="faux-model",
                    response_id=None,
                    usage=_usage(),
                    stop_reason="toolUse",
                    error_message=None,
                    timestamp=0.0,
                )
            )
        return _stream_with_final_message(_assistant_text_message(f"ok:{text}"))

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=True,
        )
        session = AgentSession(
            agent=Agent(
                stream_fn=stream_fn,
                initial_state={"model": _model()},
                tool_execution="sequential",
            ),
            session_manager=manager,
            tool_registry=registry,
            active_tool_names=["blocking"],
        )

        prompt_task = asyncio.create_task(session.prompt("use tool"))
        await asyncio.wait_for(tool_started.wait(), timeout=2)
        session.abort()
        _done, pending = await asyncio.wait({prompt_task}, timeout=2)
        if pending:
            stacks = [frame.f_code.co_name for frame in prompt_task.get_stack()]
            release_tool.set()
            await prompt_task
            raise AssertionError(f"abort did not settle prompt; stack={stacks}")
        await prompt_task
        await asyncio.wait_for(session.prompt("next"), timeout=2)

        first_messages = session.get_session_context().messages
        tool_results = [
            message
            for message in first_messages
            if isinstance(message, ToolResultMessage)
        ]
        assert len(tool_results) == 1
        assert tool_results[0].tool_call_id == "tool-1"
        assert tool_results[0].details == {"code": "tool_call_aborted"}
        assert (
            sum(
                isinstance(message, AssistantMessage)
                and message.stop_reason == "aborted"
                for message in first_messages
            )
            == 1
        )
        first_revision = len(manager.get_entries())
        assert first_revision == len(first_messages)
        assert manager.session_file is not None

        resumed_manager = await asyncio.wait_for(
            SessionManager.load(manager.session_file, persist=True),
            timeout=2,
        )
        resumed = AgentSession(
            agent=Agent(
                stream_fn=stream_fn,
                initial_state={"model": _model()},
            ),
            session_manager=resumed_manager,
        )
        await asyncio.wait_for(resumed.prompt("after resume"), timeout=2)

        assert len(resumed_manager.get_entries()) == first_revision + 2
        assert resumed.get_session_context().messages[-1].content[0].text == (
            "ok:after resume"
        )

    asyncio.run(scenario())


def test_agent_session_prompt_reports_preflight_before_stream_finishes(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    events: list[str] = []
    release = asyncio.Event()

    async def stream_fn(model, context, options=None):
        del model, context, options
        events.append("stream-start")
        await release.wait()
        return _stream_with_final_message(_assistant_text_message("hello"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        session = AgentSession(
            agent=agent,
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
        )

        def _preflight(success: bool) -> None:
            events.append(f"preflight:{success}")

        task = asyncio.create_task(session.prompt("hi", preflight_result=_preflight))
        while events != ["preflight:True", "stream-start"]:
            await asyncio.sleep(0)
        assert [
            getattr(message, "role", None) for message in session.agent.state.messages
        ] == ["user"]
        release.set()
        await task

    asyncio.run(scenario())

    assert events == ["preflight:True", "stream-start"]


def test_agent_session_prompt_expands_preflight_references_and_records_unresolved_diagnostics(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
        SkillDescriptor,
    )

    prompted_texts: list[str] = []

    async def stream_fn(model, context, options=None):
        del model, options
        last = context.messages[-1]
        assert isinstance(last, UserMessage)
        prompted_texts.append(last.content[0].text)
        return _stream_with_final_message(_assistant_text_message("hello"))

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        diagnostics = DiagnosticsService()
        session = AgentSession(
            agent=Agent(stream_fn=stream_fn),
            session_manager=manager,
            diagnostics_service=diagnostics,
            resource_bundle=ResourceBundle(
                cwd=Path("/tmp/project"),
                prompts=[
                    PromptFragmentDescriptor(
                        name="plan",
                        source_path=Path("/tmp/project/prompts/plan.md"),
                        text="Use a planning workflow before editing.",
                    )
                ],
                skills=[
                    SkillDescriptor(
                        name="debugging",
                        source_path=Path("/tmp/project/skills/debugging/SKILL.md"),
                        content="Check the failing path first.",
                    )
                ],
            ),
        )

        await session.prompt("/plan focus on retries")
        await session.prompt("/skill:debugging inspect the failing branch")
        await session.prompt("/missing-template keep original")

        unresolved = diagnostics.get_diagnostics(
            phase="runtime", source="session", type="warning"
        )
        assert [record.code for record in unresolved] == ["unresolved_prompt_reference"]

    asyncio.run(scenario())

    assert prompted_texts == [
        "Use a planning workflow before editing.\n\nfocus on retries",
        '<skill name="debugging" location="/tmp/project/skills/debugging/SKILL.md">\n'
        "References are relative to /tmp/project/skills/debugging.\n\n"
        "Check the failing path first.\n"
        "</skill>\n\n"
        "inspect the failing branch",
        "/missing-template keep original",
    ]


def test_agent_session_slash_prefix_deploy_consumes_extension_command_without_prompting_model(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    called: list[tuple[str, str]] = []
    model_prompted = False

    async def _handler(args: str, ctx):
        called.append((args, ctx.cwd))

    async def stream_fn(model, context, options=None):
        nonlocal model_prompted
        model_prompted = True
        del model, context, options
        raise AssertionError("slash command should not reach the model")

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(stream_fn=stream_fn),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="deploy-ext",
                        source_path=Path("/tmp/project/extensions/deploy-ext.py"),
                        commands={
                            "deploy": RegisteredCommand(
                                name="deploy",
                                handler=_handler,
                                description="Deploy the project",
                            )
                        },
                    )
                ]
            ),
        )

        await session.prompt("/deploy prod")

    asyncio.run(scenario())

    assert called == [("prod", "/tmp/project")]
    assert model_prompted is False


def test_agent_session_input_hook_transforms_before_prompt_preflight(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        InputEventResult,
        LoadedExtension,
    )
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
    )

    prompted_texts: list[str] = []
    seen: list[tuple[str, str]] = []

    async def stream_fn(model, context, options=None):
        del model, options
        prompted_texts.append(context.messages[-1].content[0].text)
        return _stream_with_final_message(_assistant_text_message("done"))

    def _input(event, ctx):
        del ctx
        seen.append((event.text, event.source))
        return InputEventResult(action="transform", text="/plan transformed")

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(stream_fn=stream_fn),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            resource_bundle=ResourceBundle(
                cwd=Path("/tmp/project"),
                prompts=[
                    PromptFragmentDescriptor(
                        name="plan",
                        canonical_name="plan.md",
                        source_path=Path("/tmp/project/prompts/plan.md"),
                        text="Planning prompt",
                        source_root=Path("/tmp/project/prompts"),
                    )
                ],
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="input-ext",
                        source_path=Path("/tmp/project/extensions/input.py"),
                        hooks={"input": [_input]},
                    )
                ]
            ),
        )

        await session.prompt("hello", source="rpc")

    asyncio.run(scenario())

    assert seen == [("hello", "rpc")]
    assert prompted_texts == ["Planning prompt\n\ntransformed"]


def test_agent_session_input_hook_can_handle_prompt_without_model_call(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        InputEventResult,
        LoadedExtension,
    )

    model_prompted = False

    async def stream_fn(model, context, options=None):
        nonlocal model_prompted
        model_prompted = True
        del model, context, options
        raise AssertionError("handled input should not reach the model")

    def _input(event, ctx):
        del event, ctx
        return InputEventResult(action="handled")

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(stream_fn=stream_fn),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="input-ext",
                        source_path=Path("/tmp/project/extensions/input.py"),
                        hooks={"input": [_input]},
                    )
                ]
            ),
        )

        await session.prompt("hello")

    asyncio.run(scenario())

    assert model_prompted is False


def test_agent_session_extension_command_runs_before_input_hook(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    calls: list[str] = []

    async def _command(args: str, ctx):
        del ctx
        calls.append(f"command:{args}")

    def _input(event, ctx):
        del event, ctx
        calls.append("input")

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="demo",
                        source_path=Path("/tmp/project/extensions/demo.py"),
                        hooks={"input": [_input]},
                        commands={
                            "deploy": RegisteredCommand(name="deploy", handler=_command)
                        },
                    )
                ]
            ),
        )

        await session.prompt("/deploy prod")

    asyncio.run(scenario())

    assert calls == ["command:prod"]


def test_agent_session_input_hook_transform_to_extension_command_is_plain_prompt(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        InputEventResult,
        LoadedExtension,
        RegisteredCommand,
    )

    prompted_texts: list[str] = []
    command_calls: list[str] = []

    async def stream_fn(model, context, options=None):
        del model, options
        prompted_texts.append(context.messages[-1].content[0].text)
        return _stream_with_final_message(_assistant_text_message("done"))

    def _input(event, ctx):
        del event, ctx
        return InputEventResult(action="transform", text="/deploy from-input")

    async def _command(args: str, ctx):
        del ctx
        command_calls.append(args)

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(stream_fn=stream_fn),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="demo",
                        source_path=Path("/tmp/project/extensions/demo.py"),
                        hooks={"input": [_input]},
                        commands={
                            "deploy": RegisteredCommand(name="deploy", handler=_command)
                        },
                    )
                ]
            ),
        )

        await session.prompt("hello")

    asyncio.run(scenario())

    assert command_calls == []
    assert prompted_texts == ["/deploy from-input"]


def test_agent_session_forwards_agent_lifecycle_events_to_extensions(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.ai.types import ToolResultMessage
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[object, ...]] = []

    def _agent_start(event, ctx):
        del ctx
        seen.append((event.type,))

    def _turn_start(event, ctx):
        del ctx
        seen.append((event.type, event.turn_index))

    def _turn_end(event, ctx):
        del ctx
        seen.append(
            (event.type, event.turn_index, event.message.role, len(event.tool_results))
        )

    def _agent_end(event, ctx):
        del ctx
        seen.append((event.type, len(event.messages)))

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="events",
                        source_path=Path("/tmp/project/extensions/events.py"),
                        hooks={
                            "agent_start": [_agent_start],
                            "turn_start": [_turn_start],
                            "turn_end": [_turn_end],
                            "agent_end": [_agent_end],
                        },
                    )
                ]
            ),
        )
        assistant = _assistant_text_message("done")
        tool_result = ToolResultMessage(
            role="toolResult",
            tool_call_id="tc1",
            tool_name="bash",
            content=[],
            is_error=False,
            timestamp=0.0,
        )

        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_start"}, session.agent.signal
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "turn_start"}, session.agent.signal
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "turn_end", "message": assistant, "tool_results": [tool_result]},
            session.agent.signal,
        )
        await session._composition.session_runtime.handle_agent_event(
            {"type": "agent_end", "messages": [assistant]}, session.agent.signal
        )

    asyncio.run(scenario())

    assert seen == [
        ("agent_start",),
        ("turn_start", 0),
        ("turn_end", 0, "assistant", 1),
        ("agent_end", 1),
    ]


def test_agent_session_forwards_message_and_tool_execution_events_to_extensions(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[object, ...]] = []

    def _message_start(event, ctx):
        del ctx
        seen.append((event.type, event.message.role))

    def _tool_end(event, ctx):
        del ctx
        seen.append(
            (
                event.type,
                event.tool_call_id,
                event.tool_call_id,
                event.tool_name,
                event.tool_name,
                event.is_error,
                event.is_error,
            )
        )

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="events",
                        source_path=Path("/tmp/project/extensions/events.py"),
                        hooks={
                            "message_start": [_message_start],
                            "tool_execution_end": [_tool_end],
                        },
                    )
                ]
            ),
        )
        assistant = _assistant_text_message("done")
        tool_result = AgentToolResult(
            content=[TextPart(type="text", text="ok")], details={}
        )

        await session._composition.session_runtime.handle_agent_event(
            {"type": "message_start", "message": assistant}, session.agent.signal
        )
        await session._composition.session_runtime.handle_agent_event(
            {
                "type": "tool_execution_end",
                "tool_call_id": "tc1",
                "tool_name": "bash",
                "result": tool_result,
                "is_error": False,
            },
            session.agent.signal,
        )

    asyncio.run(scenario())

    assert seen == [
        ("message_start", "assistant"),
        ("tool_execution_end", "tc1", "tc1", "bash", "bash", False, False),
    ]


def test_agent_session_records_tool_execution_error_diagnostic_with_correlation(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService

    async def scenario() -> DiagnosticsService:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        diagnostics = DiagnosticsService()
        session = AgentSession(
            agent=Agent(), session_manager=manager, diagnostics_service=diagnostics
        )

        await session._composition.session_runtime.handle_agent_event(
            {
                "type": "tool_execution_end",
                "tool_call_id": "tc1",
                "tool_name": "bash",
                "result": AgentToolResult(
                    content=[TextPart(type="text", text="Permission denied")],
                    details={"exit_code": 1},
                ),
                "is_error": True,
            },
            session.agent.signal,
        )
        return diagnostics

    diagnostics = asyncio.run(scenario())
    records = diagnostics.get_diagnostics(query=DiagnosticsQuery(tool_call_id="tc1"))

    assert len(records) == 1
    assert records[0].code == "tool_execution_failed"
    assert records[0].source == "tool"
    assert records[0].details["tool_call_id"] == "tc1"
    assert records[0].details["tool_name"] == "bash"


def test_agent_session_applies_before_agent_start_result(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        BeforeAgentStartResult,
        ExtensionRunner,
        LoadedExtension,
    )

    seen: list[tuple[object, ...]] = []
    prompted_messages: list[list[object]] = []
    prompted_system_prompts: list[str] = []
    session_holder: dict[str, AgentSession] = {}

    async def stream_fn(model, context, options=None):
        del model, options
        prompted_messages.append(list(context.messages))
        prompted_system_prompts.append(context.system_prompt)
        return _stream_with_final_message(_assistant_text_message("done"))

    def _before(event, ctx):
        seen.append((event.prompt, event.system_prompt, ctx.get_system_prompt()))
        return BeforeAgentStartResult(
            system_prompt="Extension system prompt",
            extra_messages=[
                {
                    "customType": "demo_notice",
                    "content": "extension context",
                    "display": True,
                    "details": {"source": "before_agent_start"},
                }
            ],
        )

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(
                stream_fn=stream_fn,
                initial_state={"system_prompt": "Base system prompt"},
            ),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="before",
                        source_path=Path("/tmp/project/extensions/before.py"),
                        hooks={"before_agent_start": [_before]},
                    )
                ]
            ),
        )
        session_holder["session"] = session

        await session.prompt("hello")

    asyncio.run(scenario())

    assert seen == [("hello", "Base system prompt", "Base system prompt")]
    assert prompted_system_prompts == ["Extension system prompt"]
    assert prompted_messages
    entries = session_holder["session"].session_manager.get_entries()
    assert [entry.kind for entry in entries[:2]] == [
        "agent.message",
        "application.message",
    ]
    assert getattr(entries[1].payload, "custom_type", None) == "demo_notice"
    assert entries[1].payload.content == "extension context"


def test_agent_session_extension_hook_ordering_spans_provider_tool_and_agent_end(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.agent.types import AgentToolResult
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        InputEventResult,
        LoadedExtension,
    )
    from loushang.harness.tools.core import ToolDefinition
    from loushang.harness.tools.execution import direct_execution
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

    order: list[str] = []

    async def execute_finish(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        order.append("tool_execute")
        return AgentToolResult(
            content=[TextPart(type="text", text="finished")],
            details={"ok": True},
            terminate=True,
        )

    registry = WorkspaceToolRegistry()
    registry.register_tool(
        ToolDefinition(
            name="finish",
            description="Finish the run",
            parameters={"type": "object", "properties": {}},
            label="Finish",
            execution=direct_execution(execute_finish),
            execution_mode="sequential",
        )
    )

    async def stream_fn(model, context, options=None):
        del model, context
        assert options is not None
        return _stream_with_assistant_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[
                    ToolCall(
                        type="toolCall",
                        id="tool-1",
                        name="finish",
                        arguments={},
                    )
                ],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=_usage(),
                stop_reason="tool_use",
                error_message=None,
                timestamp=0.0,
            )
        )

    def _input(event, ctx):
        del event, ctx
        order.append("input")
        return InputEventResult(action="continue")

    def _before_agent_start(event, ctx):
        del event, ctx
        order.append("before_agent_start")

    def _tool_call(event, ctx):
        del event, ctx
        order.append("tool_call")

    def _tool_result(event, ctx):
        del event, ctx
        order.append("tool_result")

    def _agent_end(event, ctx):
        del event, ctx
        order.append("agent_end")

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(
                stream_fn=stream_fn,
                initial_state={
                    "system_prompt": "Base system prompt",
                    "model": _model(),
                    "thinking_level": "off",
                    "tools": [],
                },
            ),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="ordering",
                        source_path=Path("/tmp/project/extensions/ordering.py"),
                        hooks={
                            "input": [_input],
                            "before_agent_start": [_before_agent_start],
                            "tool_call": [_tool_call],
                            "tool_result": [_tool_result],
                            "agent_end": [_agent_end],
                        },
                    )
                ]
            ),
            tool_registry=registry,
            active_tool_names=["finish"],
        )

        await session.prompt("hello")

    asyncio.run(scenario())

    assert order == [
        "input",
        "before_agent_start",
        "tool_call",
        "tool_execute",
        "tool_result",
        "agent_end",
    ]


def test_agent_session_execute_bash_uses_extension_user_bash_result(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[object, object, object]] = []

    def _user_bash(event, ctx):
        seen.append((event.command, event.exclude_from_context, ctx.cwd))
        return {"result": {"output": "handled by extension\n", "exitCode": 0}}

    async def scenario() -> dict[str, object]:
        session = AgentSession(
            agent=Agent(),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="bash-ext",
                        source_path=Path("/tmp/project/extensions/bash.py"),
                        hooks={"user_bash": [_user_bash]},
                    )
                ]
            ),
        )
        return await session.execute_bash("pwd", exclude_from_context=True)

    result = asyncio.run(scenario())

    assert result == {
        "output": "handled by extension\n",
        "exit_code": 0,
        "cancelled": False,
        "truncated": False,
        "full_output_path": None,
    }
    assert seen == [("pwd", True, "/tmp/project")]


def test_agent_session_execute_bash_uses_extension_user_bash_operations(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )
    from loushang.harness.workspace.exec import ExecOutputChunk, ExecRequest, ExecResult

    class RecordingOperations:
        def __init__(self) -> None:
            self.calls: list[tuple[ExecRequest, object | None]] = []

        async def execute(
            self, request: ExecRequest, *, signal=None, on_update=None
        ) -> ExecResult:
            self.calls.append((request, signal))
            if on_update is not None:
                await on_update(ExecOutputChunk(stream="stdout", text="streamed\n"))
            return ExecResult(exit_code=0, stdout="remote\n")

    operations = RecordingOperations()
    seen: list[str] = []
    chunks: list[ExecOutputChunk] = []

    def _user_bash(event, ctx):
        seen.append(event.command)
        assert ctx.cwd == "/tmp/project"
        return {"operations": operations}

    async def scenario() -> dict[str, object]:
        registry = register_builtin_tools(ToolRegistry())
        session = AgentSession(
            agent=Agent(),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="bash-ext",
                        source_path=Path("/tmp/project/extensions/bash.py"),
                        hooks={"user_bash": [_user_bash]},
                    )
                ]
            ),
            tool_registry=registry,
        )
        return await session.execute_bash("printf remote", on_output=chunks.append)

    result = asyncio.run(scenario())

    assert result == {
        "output": "remote\n",
        "exit_code": 0,
        "cancelled": False,
        "truncated": False,
        "full_output_path": None,
    }
    assert seen == ["printf remote"]
    assert operations.calls[0][0].command == ("/bin/bash", "-lc", "printf remote")
    assert operations.calls[0][1] is not None
    assert chunks == [ExecOutputChunk(stream="stdout", text="streamed\n")]


def test_agent_session_steer_rejects_extension_command_without_executing(
    tmp_path,
) -> None:
    from pathlib import Path

    import pytest

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    calls: list[str] = []

    async def _handler(args: str, ctx):
        del ctx
        calls.append(args)

    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="deploy-ext",
                    source_path=Path("/tmp/project/extensions/deploy-ext.py"),
                    commands={
                        "deploy": RegisteredCommand(name="deploy", handler=_handler)
                    },
                )
            ]
        ),
    )

    with pytest.raises(
        RuntimeError,
        match='Extension command "/deploy" cannot be queued. Use prompt\\(\\) or execute the command when not streaming.',
    ):
        session.steer("/deploy prod")

    assert calls == []


def test_agent_session_follow_up_rejects_extension_command_without_executing(
    tmp_path,
) -> None:
    from pathlib import Path

    import pytest

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    calls: list[str] = []

    async def _handler(args: str, ctx):
        del ctx
        calls.append(args)

    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="deploy-ext",
                    source_path=Path("/tmp/project/extensions/deploy-ext.py"),
                    commands={
                        "deploy": RegisteredCommand(name="deploy", handler=_handler)
                    },
                )
            ]
        ),
    )

    with pytest.raises(
        RuntimeError,
        match='Extension command "/deploy" cannot be queued. Use prompt\\(\\) or execute the command when not streaming.',
    ):
        session.follow_up("/deploy prod")

    assert calls == []


def test_agent_session_get_commands_aggregates_extension_prompt_and_skill_sources(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
        SkillDescriptor,
    )

    async def _handler(args: str, ctx):
        del args, ctx

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(
        agent=Agent(),
        session_manager=manager,
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"),
            prompts=[
                PromptFragmentDescriptor(
                    name="plan",
                    canonical_name="plan.md",
                    source_path=Path("/tmp/project/prompts/plan.md"),
                    text="---\ndescription: Planning prompt\n---\nUse a planning workflow before editing.",
                    source_root=Path("/tmp/project/prompts"),
                )
            ],
            skills=[
                SkillDescriptor(
                    name="debugging",
                    canonical_name="debugging/SKILL.md",
                    source_path=Path("/tmp/project/skills/debugging/SKILL.md"),
                    content=(
                        "---\n"
                        "description: Debug failures by tracing the narrowest failing path.\n"
                        "---\n\n"
                        "Check the failing path first."
                    ),
                    description="Debug failures by tracing the narrowest failing path.",
                    source_root=Path("/tmp/project/skills"),
                )
            ],
        ),
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="deploy-ext",
                    source_path=Path("/tmp/project/extensions/deploy-ext.py"),
                    commands={
                        "deploy": RegisteredCommand(
                            name="deploy",
                            handler=_handler,
                            description="Deploy the project",
                        )
                    },
                )
            ]
        ),
    )

    descriptors = session.list_commands()
    non_builtin = [
        descriptor for descriptor in descriptors if descriptor.source != "builtin"
    ]

    assert {descriptor.name for descriptor in descriptors} >= {
        "copy",
        "rename",
        "session",
        "changelog",
    }
    assert [descriptor.name for descriptor in non_builtin] == [
        "deploy",
        "plan",
        "skill:debugging",
    ]
    assert [descriptor.description for descriptor in non_builtin] == [
        "Deploy the project",
        "Use a planning workflow before editing.",
        "Debug failures by tracing the narrowest failing path.",
    ]
    assert [descriptor.source for descriptor in non_builtin] == [
        "extension",
        "prompt",
        "skill",
    ]
    assert [descriptor.source_info.path for descriptor in non_builtin] == [
        "/tmp/project/extensions/deploy-ext.py",
        "/tmp/project/prompts/plan.md",
        "/tmp/project/skills/debugging/SKILL.md",
    ]
    assert [descriptor.source_info.base_dir for descriptor in non_builtin] == [
        "/tmp/project/extensions",
        "/tmp/project/prompts",
        "/tmp/project/skills",
    ]


def test_agent_session_list_commands_hides_disabled_skills_but_keeps_explicit_only_skills(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.types import (
        ResourceBundle,
        SkillDescriptor,
    )

    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"),
            skills=[
                SkillDescriptor(
                    name="debugging",
                    source_path=Path("/tmp/project/skills/debugging/SKILL.md"),
                    description="Debug failures.",
                    enabled=False,
                ),
                SkillDescriptor(
                    name="deploy",
                    source_path=Path("/tmp/project/skills/deploy/SKILL.md"),
                    description="Deployment-only workflow.",
                    disable_model_invocation=True,
                ),
            ],
        ),
    )

    assert [
        descriptor.name
        for descriptor in session.list_commands()
        if descriptor.source != "builtin"
    ] == ["skill:deploy"]


def test_agent_session_execute_command_async_dispatches_extension_command(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )
    from loushang.harness.session import CommandExecutionResult

    calls: list[tuple[str, str, str]] = []

    async def _handler(args: str, ctx):
        await asyncio.sleep(0)
        calls.append((args, ctx.cwd, type(ctx).__name__))

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        session = AgentSession(
            agent=Agent(),
            session_manager=manager,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="deploy-ext",
                        source_path=Path("/tmp/project/extensions/deploy-ext.py"),
                        commands={
                            "deploy": RegisteredCommand(
                                name="deploy",
                                handler=_handler,
                                description="Deploy the project",
                            )
                        },
                    )
                ]
            ),
        )

        result = await session.execute_command_async("deploy", "now")
        assert isinstance(result, CommandExecutionResult)
        assert result.invocation_name == "deploy"
        assert result.result is None
        assert calls == [("now", "/tmp/project", "_BoundExtensionContext")]

    asyncio.run(scenario())


def test_agent_session_extension_command_context_exec_command_uses_exec_service(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )
    from loushang.harness.workspace.exec import ExecOutputChunk, ExecResult

    class RecordingExecService:
        def __init__(self) -> None:
            self.requests: list[object] = []
            self.signals: list[object | None] = []

        async def execute(self, request, *, signal=None, on_update=None):
            self.requests.append(request)
            self.signals.append(signal)
            if on_update is not None:
                update = on_update(ExecOutputChunk(stream="stdout", text="ok\n"))
                if inspect.isawaitable(update):
                    await update
            return ExecResult(exit_code=0, stdout="ok\n")

    exec_service = RecordingExecService()
    seen: list[tuple[ExecResult, list[ExecOutputChunk]]] = []

    async def _handler(args: str, ctx):
        del args
        updates: list[ExecOutputChunk] = []
        result = await ctx.exec_command(
            "git",
            ["status", "--short"],
            cwd="repo",
            env={"LOUSHANG": "1"},
            timeout_seconds=5,
            stdin="payload",
            on_update=updates.append,
        )
        seen.append((result, updates))

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        session = AgentSession(
            agent=Agent(),
            session_manager=manager,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="deploy-ext",
                        source_path=Path("/tmp/project/extensions/deploy-ext.py"),
                        commands={
                            "deploy": RegisteredCommand(
                                name="deploy",
                                handler=_handler,
                                description="Deploy the project",
                            )
                        },
                    )
                ]
            ),
            exec_service=exec_service,
        )

        await session.execute_command_async("deploy", "now")
        assert exec_service.signals == [session.agent.signal]

    asyncio.run(scenario())

    assert len(exec_service.requests) == 1
    request = exec_service.requests[0]
    assert request.command == ("git", "status", "--short")
    assert request.cwd == "/tmp/project/repo"
    assert ("LOUSHANG", "1") in request.env
    assert request.timeout_seconds == 5
    assert request.stdin == "payload"
    assert seen == [
        (
            ExecResult(exit_code=0, stdout="ok\n"),
            [ExecOutputChunk(stream="stdout", text="ok\n")],
        )
    ]


def test_agent_session_execute_command_async_expands_prompt_and_skill_commands(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
        SkillDescriptor,
    )

    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"),
            prompts=[
                PromptFragmentDescriptor(
                    name="plan",
                    source_path=Path("/tmp/project/prompts/plan.md"),
                    text="Use a planning workflow before editing.",
                )
            ],
            skills=[
                SkillDescriptor(
                    name="debugging",
                    source_path=Path("/tmp/project/skills/debugging/SKILL.md"),
                    content="---\nname: debugging\n---\n\nCheck the failing path first.",
                )
            ],
        ),
    )

    prompt_result = asyncio.run(
        session.execute_command_async("/plan", "focus on retries")
    )
    skill_result = asyncio.run(
        session.execute_command_async("skill:debugging", "inspect the failing branch")
    )

    assert prompt_result is not None
    assert prompt_result.invocation_name == "plan"
    assert prompt_result.result == {
        "source": "prompt",
        "text": "Use a planning workflow before editing.\n\nfocus on retries",
    }
    assert skill_result is not None
    assert skill_result.invocation_name == "skill:debugging"
    assert skill_result.result == {
        "source": "skill",
        "text": '<skill name="debugging" location="/tmp/project/skills/debugging/SKILL.md">\n'
        "References are relative to /tmp/project/skills/debugging.\n\n"
        "Check the failing path first.\n"
        "</skill>\n\n"
        "inspect the failing branch",
    }


def test_agent_session_execute_command_async_prefers_extension_over_prompt(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
    )

    calls: list[str] = []

    async def _handler(args: str, ctx):
        del ctx
        calls.append(args)

    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"),
            prompts=[
                PromptFragmentDescriptor(
                    name="deploy",
                    source_path=Path("/tmp/project/prompts/deploy.md"),
                    text="Prompt deploy",
                )
            ],
        ),
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="deploy-ext",
                    source_path=Path("/tmp/project/extensions/deploy.py"),
                    commands={
                        "deploy": RegisteredCommand(name="deploy", handler=_handler)
                    },
                )
            ]
        ),
    )

    result = asyncio.run(session.execute_command_async("deploy", "now"))

    assert result is not None
    assert result.result is None
    assert calls == ["now"]


def test_agent_session_returns_command_argument_completions(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    async def _handler(args, ctx):
        del args, ctx

    def _complete(prefix: str):
        return [{"value": f"{prefix}-candidate"}]

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="deploy-ext",
                        source_path=Path("/tmp/project/extensions/deploy.py"),
                        commands={
                            "deploy": RegisteredCommand(
                                name="deploy",
                                handler=_handler,
                                get_argument_completions=_complete,
                            )
                        },
                    )
                ]
            ),
        )

        assert await session.get_command_argument_completions("deploy", "prod") == [
            {"value": "prod-candidate"}
        ]
        assert await session.get_command_argument_completions("missing", "") is None

    asyncio.run(scenario())


def test_agent_session_extension_command_context_wait_for_idle_and_reload(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    calls: list[str] = []

    async def _handler(args: str, ctx):
        del args
        await ctx.wait_for_idle()
        await ctx.wait_for_idle()
        await ctx.reload()
        calls.append("done")

    async def scenario() -> None:
        runner = ExtensionRunner(
            [
                LoadedExtension(
                    name="deploy-ext",
                    source_path=Path("/tmp/project/extensions/deploy-ext.py"),
                    commands={
                        "deploy": RegisteredCommand(
                            name="deploy",
                            handler=_handler,
                            description="Deploy the project",
                        )
                    },
                )
            ]
        )
        session = AgentSession(
            agent=Agent(),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=runner,
        )

        result = await session.execute_command_async("deploy", "now")
        assert result.result is None

    asyncio.run(scenario())

    assert calls == ["done"]


def test_agent_session_extension_command_context_navigate_tree(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    results: list[object] = []
    events: list[tuple[object, object, object]] = []

    async def _handler(args: str, ctx):
        result = await ctx.navigate_tree(args, {"label": "from-extension"})
        results.append(result)

    def _session_tree(event, ctx):
        del ctx
        events.append((event.old_leaf_id, event.new_leaf_id, event.summary_entry))

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        await manager.append_message(_user_message("first"))
        target_id = await manager.append_message(_assistant_text_message("assistant"))
        await manager.append_message(_user_message("second"))
        old_leaf_id = manager.get_leaf_id()
        session = AgentSession(
            agent=Agent(),
            session_manager=manager,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="nav-ext",
                        source_path=Path("/tmp/project/extensions/nav-ext.py"),
                        commands={
                            "nav": RegisteredCommand(
                                name="nav",
                                handler=_handler,
                                description="Navigate tree",
                            )
                        },
                        hooks={"session_tree": [_session_tree]},
                    )
                ]
            ),
        )

        result = await session.execute_command_async("nav", target_id)
        assert result.result is None
        assert results == [{"cancelled": False}]
        assert session.session_manager.get_leaf_id() == target_id
        assert [
            message.content[0].text for message in session.agent.state.messages
        ] == ["first", "assistant"]
        assert events == [(old_leaf_id, target_id, None)]

    asyncio.run(scenario())

    assert results == [{"cancelled": False}]


def test_agent_session_execute_command_async_records_errors(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    async def _handler(args: str, ctx):
        del args, ctx
        raise RuntimeError("boom")

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        diagnostics_service = DiagnosticsService()
        session = AgentSession(
            agent=Agent(),
            session_manager=manager,
            diagnostics_service=diagnostics_service,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="deploy-ext",
                        source_path=Path("/tmp/project/extensions/deploy-ext.py"),
                        commands={
                            "deploy": RegisteredCommand(
                                name="deploy",
                                handler=_handler,
                                description="Deploy the project",
                            )
                        },
                    )
                ]
            ),
        )

        result = await session.execute_command_async("deploy", "now")
        assert result is not None
        assert result.result is None
        records = diagnostics_service.get_diagnostics(code="extension_command_failed")
        assert len(records) == 1
        assert records[0].details["invocation_name"] == "deploy"
        assert records[0].details["command_name"] == "deploy"
        assert records[0].details["extension_name"] == "deploy-ext"
        assert records[0].details["source_info"] == {
            "path": "/tmp/project/extensions/deploy-ext.py",
            "source": "filesystem",
            "scope": "project",
            "origin": "top-level",
            "base_dir": None,
        }

    asyncio.run(scenario())


def test_agent_session_execute_command_async_returns_none_for_unknown_command(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    diagnostics_service = DiagnosticsService()
    session = AgentSession(
        agent=Agent(), session_manager=manager, diagnostics_service=diagnostics_service
    )

    assert asyncio.run(session.execute_command_async("missing", "args")) is None
    records = diagnostics_service.get_diagnostics(code="command_not_found")
    assert len(records) == 1
    assert records[0].type == "warning"
    assert records[0].source == "session"
    assert records[0].details == {
        "invocation_name": "missing",
        "args": "args",
    }


def test_agent_session_execute_command_async_keeps_resource_diagnostic_for_unresolved_command(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.resources.types import ResourceBundle

    diagnostics_service = DiagnosticsService()
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        diagnostics_service=diagnostics_service,
        resource_bundle=ResourceBundle(cwd=Path("/tmp/project")),
    )

    assert asyncio.run(session.execute_command_async("missing", "args")) is None
    records = diagnostics_service.get_diagnostics(
        phase="runtime", source="session", type="warning"
    )
    assert [record.code for record in records] == ["unresolved_prompt_reference"]
    assert diagnostics_service.get_diagnostics(code="command_not_found") == []


def test_agent_session_get_commands_includes_all_extension_commands(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    async def _handler(args: str, ctx):
        del args, ctx

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(
        agent=Agent(),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="deploy-ext",
                    source_path=Path("/tmp/project/extensions/deploy-ext.py"),
                    commands={
                        "deploy": RegisteredCommand(
                            name="deploy",
                            handler=_handler,
                            description="Deploy the project",
                        ),
                        "secret": RegisteredCommand(
                            name="secret",
                            handler=_handler,
                            description="Hidden command",
                        ),
                    },
                )
            ]
        ),
    )

    assert [
        command.name
        for command in session.list_commands()
        if command.source != "builtin"
    ] == ["deploy", "secret"]


def test_agent_session_lists_user_messages_for_forking(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.conversation import CommandExecutionRecord

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    first_id = asyncio.run(manager.append_message(_user_message("first")))
    asyncio.run(manager.append_message(_assistant_text_message("assistant")))
    asyncio.run(
        manager.append_message(
            CommandExecutionRecord(
                command="printf hi",
                output="hi\n",
                exit_code=0,
                cancelled=False,
                truncated=False,
                full_output_path=None,
            )
        )
    )
    second_id = asyncio.run(manager.append_message(_user_message("second")))

    session = AgentSession(agent=Agent(), session_manager=manager)

    assert session.get_user_messages_for_forking() == [
        {"entry_id": first_id, "text": "first"},
        {"entry_id": second_id, "text": "second"},
    ]
    assert session.get_user_messages_for_forking() == [
        {"entry_id": first_id, "text": "first"},
        {"entry_id": second_id, "text": "second"},
    ]


def test_agent_session_exposes_last_assistant_text(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
    )
    session.agent.state.set_messages(
        [_user_message("hello"), _assistant_text_message("answer")]
    )

    assert session.get_last_assistant_text() == "answer"


def test_agent_session_exposes_recent_assistant_texts_newest_first(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
    )
    session.agent.state.set_messages(
        [
            _assistant_text_message("first"),
            _assistant_text_message(""),
            _user_message("hello"),
            _assistant_text_message("second"),
        ]
    )

    assert session.get_recent_assistant_texts() == ("second", "first")


def test_agent_session_exposes_standard_state_properties(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=True)
    )
    session = AgentSession(
        agent=Agent(initial_state={"model": _model()}), session_manager=manager
    )
    asyncio.run(session.set_session_name("Demo"))
    asyncio.run(session.set_thinking_level("high"))
    session.set_steering_mode("all")
    session.set_follow_up_mode("one-at-a-time")

    assert session.model == session.agent.model
    assert session.thinking_level == "high"
    assert session.is_streaming is False
    assert session.system_prompt == session.agent.system_prompt
    assert session.retry_attempt == 0
    assert session.is_compacting is False
    assert session.steering_mode == "all"
    assert session.follow_up_mode == "one-at-a-time"
    assert session.get_session_file() == manager.session_file
    assert session.session_id == manager.get_header().conversation_id
    assert session.session_name == "Demo"
    assert session.auto_compaction_enabled is True


def test_agent_session_steer_then_continue_persists_follow_on_turn(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    prompts: list[str] = []
    queue_updates: list[tuple[list[str], list[str]]] = []

    async def stream_fn(model, context, options=None):
        last = context.messages[-1]
        if isinstance(last, UserMessage):
            prompts.append(last.content[0].text)
        return _stream_with_final_message(_assistant_text_message("done"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        session = AgentSession(agent=agent, session_manager=manager)
        agent.state.messages.append(_assistant_text_message("existing"))

        def listener(event) -> None:
            if event["type"] == "queue_update":
                queue_updates.append(
                    (list(event["steering"]), list(event["follow_up"]))
                )

        session.subscribe(listener)
        session.steer("next step")
        await session.continue_run()

        assert prompts == ["next step"]
        assert [
            getattr(message, "role", None)
            for message in session.get_session_context().messages[-2:]
        ] == ["user", "assistant"]
        assert queue_updates[0] == (["next step"], [])

    asyncio.run(scenario())


def test_agent_session_exposes_standard_queue_accessors_and_clear_queue(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
    )
    events: list[tuple[list[str], list[str]]] = []

    def listener(event) -> None:
        if event["type"] == "queue_update":
            events.append((list(event["steering"]), list(event["follow_up"])))

    session.subscribe(listener)
    session.steer("steer one")
    session.follow_up("follow one")

    assert session.pending_message_count == 2
    assert session.get_steering_messages() == ["steer one"]
    assert session.get_follow_up_messages() == ["follow one"]

    cleared = session.clear_queue()

    assert cleared == {
        "steering": ["steer one"],
        "followUp": ["follow one"],
        "follow_up": ["follow one"],
    }
    assert session.pending_message_count == 0
    assert session.get_steering_messages() == []
    assert session.get_follow_up_messages() == []
    assert events[-1] == ([], [])


def test_agent_session_removes_visible_queue_when_queued_user_message_starts(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
    )
    events: list[tuple[list[str], list[str]]] = []

    def listener(event) -> None:
        if event["type"] == "queue_update":
            events.append((list(event["steering"]), list(event["follow_up"])))

    session.subscribe(listener)
    session.steer("queued")

    asyncio.run(
        session._composition.session_runtime.handle_agent_event(
            {
                "type": "message_start",
                "message": UserMessage(
                    role="user",
                    content=[TextPart(type="text", text="queued")],
                    timestamp=0.0,
                ),
            },
            session.agent.signal,
        )
    )

    assert session.get_steering_messages() == []
    assert events[-1] == ([], [])


def test_agent_session_follow_up_and_state_snapshot(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession, RunState
    from loushang.coding.session_manager import SessionManager

    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "off"}
    )
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(agent=agent, session_manager=manager)

    session.follow_up("later")
    session._composition.retry_runtime.retry_future = object()  # type: ignore[assignment]
    state = session.get_state()
    session._composition.retry_runtime.retry_future = None

    assert state.run == RunState(status="idle")
    assert state.follow_up == ["later"]
    assert state.steering == []
    assert state.is_retrying is True
    assert state.is_compacting is False
    assert state.model_selection is not None
    assert state.model_selection.provider == "faux"
    assert state.model_selection.model_id == "faux-model"


def test_agent_session_set_model_and_thinking_level_persist_to_store(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession, ModelSelection
    from loushang.coding.session_manager import SessionManager

    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "off"}
    )
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(agent=agent, session_manager=manager)

    next_model = Model(
        id="alt-model",
        name="Alt",
        provider="alt",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=64000,
            max_tokens=2048,
        ),
    )

    asyncio.run(session.set_model(next_model))
    asyncio.run(session.set_thinking_level("high"))

    assert session.get_model_selection() == ModelSelection(
        endpoint_id="responses", provider="alt", model_id="alt-model"
    )
    assert session.get_state().thinking_level == "high"
    assert [entry.kind for entry in manager.get_entries()] == [
        "agent.model_selection",
        "agent.thinking_selection",
    ]
    assert session.get_session_context().model == {
        "provider": "alt",
        "endpoint_id": "responses",
        "model_id": "alt-model",
    }


def test_agent_session_persists_explicit_model_selection_endpoint(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession, ModelSelection
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    first = _model()
    second = Model(
        id="alt-model",
        name="Alt",
        provider="alt",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=64_000,
            max_tokens=2_048,
        ),
    )
    session = AgentSession(
        agent=Agent(
            initial_state={"system_prompt": "", "model": first, "thinking_level": "off"}
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        model_registry=ModelRegistry(ai_registry=_ai_model_registry(first, second)),
    )

    asyncio.run(
        session.set_model(
            ModelSelection(
                provider="alt",
                endpoint_id="responses",
                model_id="alt-model",
            )
        )
    )

    assert session.get_session_context().model == {
        "provider": "alt",
        "model_id": "alt-model",
        "endpoint_id": "responses",
    }


def test_agent_session_cycles_model_and_thinking_level(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession, ModelSelection
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    first = _model()
    second = Model(
        id="alt-model",
        name="Alt",
        provider="alt",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=64000,
            max_tokens=2048,
        ),
    )
    ai_registry = _ai_model_registry(first, second)

    session = AgentSession(
        agent=Agent(
            initial_state={"system_prompt": "", "model": first, "thinking_level": "low"}
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        model_registry=ModelRegistry(ai_registry=ai_registry),
    )

    assert asyncio.run(session.cycle_model()) == ModelSelection(
        endpoint_id="responses", provider="alt", model_id="alt-model"
    )
    assert session.get_model_selection() == ModelSelection(
        endpoint_id="responses", provider="alt", model_id="alt-model"
    )
    assert asyncio.run(session.cycle_thinking_level()) == "medium"
    assert session.get_state().thinking_level == "medium"


def test_agent_session_emits_model_select_event_for_async_model_control(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession, ModelSelection
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    first = _model()
    second = Model(
        id="alt-model",
        name="Alt",
        provider="alt",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=64000,
            max_tokens=2048,
        ),
    )
    ai_registry = _ai_model_registry(first, second)
    seen: list[tuple[str, object, object, str]] = []

    def _model_select(event, ctx):
        del ctx
        seen.append((event.type, event.model.id, event.previous_model.id, event.source))

    session = AgentSession(
        agent=Agent(
            initial_state={"system_prompt": "", "model": first, "thinking_level": "low"}
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        model_registry=ModelRegistry(ai_registry=ai_registry),
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="model-ext",
                    source_path=Path("/tmp/project/extensions/model.py"),
                    hooks={"model_select": [_model_select]},
                )
            ]
        ),
    )

    asyncio.run(session.set_model(second))
    assert asyncio.run(session.cycle_model("backward")) == ModelSelection(
        endpoint_id="anthropic-messages", provider="faux", model_id="faux-model"
    )

    assert seen == [
        ("model_select", "alt-model", "faux-model", "set"),
        ("model_select", "faux-model", "alt-model", "cycle"),
    ]


def test_agent_session_exposes_standard_model_and_session_mutators(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession, ModelSelection
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    first = _model()
    second = Model(
        id="alt-model",
        name="Alt",
        provider="alt",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=64000,
            max_tokens=2048,
        ),
    )
    ai_registry = _ai_model_registry(first, second)
    session = AgentSession(
        agent=Agent(
            initial_state={"system_prompt": "", "model": first, "thinking_level": "low"}
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        model_registry=ModelRegistry(ai_registry=ai_registry),
    )

    asyncio.run(session.set_model(second))
    assert session.get_model_selection() == ModelSelection(
        endpoint_id="responses", provider="alt", model_id="alt-model"
    )

    assert asyncio.run(session.cycle_model("backward")) == ModelSelection(
        endpoint_id="anthropic-messages", provider="faux", model_id="faux-model"
    )
    assert session.get_model_selection() == ModelSelection(
        endpoint_id="anthropic-messages", provider="faux", model_id="faux-model"
    )

    asyncio.run(session.set_thinking_level("high"))
    assert session.thinking_level == "high"
    assert asyncio.run(session.cycle_thinking_level()) == "xhigh"

    asyncio.run(session.set_session_name("SDK Demo"))
    assert session.session_name == "SDK Demo"


def test_agent_session_applies_extension_provider_registration(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionAPI, ExtensionRunner
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    ai_registry = AiModelRegistry()
    model_registry = ModelRegistry(ai_registry=ai_registry)
    api = ExtensionAPI(name="provider-ext", source_path=Path("/tmp/provider-ext.py"))

    api.register_provider(
        "proxy",
        {
            "displayName": "Proxy Provider",
            "website": "https://proxy.example.com",
            "endpoints": {
                "proxy-simple": {
                    "api": "openai-completions",
                    "displayName": "Proxy Endpoint",
                    "baseUrl": "https://proxy.example.com",
                    "authOverride": {
                        "kind": "apiKey",
                        "apiKeyEnv": "PROXY_API_KEY",
                    },
                    "adapter": {"streamingUsage": True},
                    "defaults": {"temperature": 0.1},
                    "models": {
                        "proxy-model": {
                            "displayName": "Proxy Model",
                            "input": ["text", "image"],
                            "reasoning": True,
                            "contextWindow": 200000,
                            "maxTokens": 8192,
                            "cost": {"input": 1, "output": 2},
                            "adapter": {"reasoningEffort": True},
                            "defaults": {"reasoningEffort": "high"},
                        }
                    },
                }
            },
        },
    )

    AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "low",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        model_registry=model_registry,
        extension_runner=ExtensionRunner([api.build_loaded_extension()]),
    )

    provider = model_registry.ai_registry.get_provider("proxy")
    assert provider is not None
    assert provider.name == "Proxy Provider"
    assert provider.website == "https://proxy.example.com"
    endpoint = model_registry.ai_registry.get_endpoint("proxy", "proxy-simple")
    assert endpoint is not None
    assert endpoint.name == "Proxy Endpoint"
    assert endpoint.base_url == "https://proxy.example.com"
    assert endpoint.auth is not None
    assert endpoint.auth.api_key_env == "PROXY_API_KEY"
    assert endpoint.adapter is not None
    assert endpoint.adapter.streaming_usage is True
    assert dict(endpoint.defaults) == {"temperature": 0.1}
    model = model_registry.ai_registry.get_model("proxy", "proxy-simple", "proxy-model")
    assert model.name == "Proxy Model"
    assert model.supports_image_input is True
    assert model.supports_thinking is True
    assert model.max_tokens == 8192
    assert model.adapter is not None
    assert model.adapter.streaming_usage is True
    assert model.adapter.reasoning_effort is True
    assert dict(model.defaults) == {"temperature": 0.1, "reasoningEffort": "high"}

    api.register_provider(
        "proxy",
        {
            "endpoints": {
                "proxy-simple": {
                    "baseUrl": "https://proxy-updated.example.com",
                    "authOverride": {
                        "kind": "apiKey",
                        "apiKeyEnv": "PROXY_API_KEY",
                    },
                    "adapter": {"store": True},
                    "defaults": {"maxTokens": 1024},
                }
            }
        },
    )
    endpoint = model_registry.ai_registry.get_endpoint("proxy", "proxy-simple")
    assert endpoint is not None
    assert endpoint.base_url == "https://proxy-updated.example.com"
    assert endpoint.auth is not None
    assert endpoint.auth.api_key_env == "PROXY_API_KEY"
    model = model_registry.ai_registry.get_model("proxy", "proxy-simple", "proxy-model")
    assert model.name == "Proxy Model"
    assert model.adapter is not None
    assert model.adapter.streaming_usage is True
    assert model.adapter.reasoning_effort is True
    assert model.adapter.store is True
    assert dict(model.defaults) == {
        "temperature": 0.1,
        "reasoningEffort": "high",
        "maxTokens": 1024,
    }

    api.unregister_provider("proxy")
    assert model_registry.ai_registry.get_provider("proxy") is None


def test_agent_session_rejects_pi_style_extension_provider_config(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.extensions.agent import ExtensionAPI, ExtensionRunner
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    def _build_session(api: ExtensionAPI) -> tuple[AiModelRegistry, DiagnosticsService]:
        ai_registry = AiModelRegistry()
        diagnostics_service = DiagnosticsService()
        AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "",
                    "model": _model(),
                    "thinking_level": "low",
                }
            ),
            session_manager=asyncio.run(
                SessionManager.new(
                    session_dir=tmp_path, cwd="/tmp/project", persist=False
                )
            ),
            model_registry=ModelRegistry(ai_registry=ai_registry),
            diagnostics_service=diagnostics_service,
            extension_runner=ExtensionRunner([api.build_loaded_extension()]),
        )
        return ai_registry, diagnostics_service

    pi_style = ExtensionAPI(
        name="provider-ext", source_path=Path("/tmp/provider-ext.py")
    )
    pi_style.register_provider(
        "proxy",
        {
            "api": "proxy-simple",
            "baseUrl": "https://proxy.example.com",
            "apiKey": "PROXY_API_KEY",
            "models": [{"id": "proxy-model", "name": "Proxy Model"}],
        },
    )
    ai_registry, diagnostics_service = _build_session(pi_style)
    assert ai_registry.get_provider("proxy") is None
    assert any(
        record.code == "extension_runtime_bind_failed"
        and 'loushang-native "endpoints" schema' in record.message
        for record in diagnostics_service.get_diagnostics()
    )

    mixed_stream = ExtensionAPI(
        name="provider-ext", source_path=Path("/tmp/provider-ext.py")
    )
    mixed_stream.register_provider(
        "proxy",
        {
            "endpoints": {
                "proxy-simple": {
                    "api": "proxy-simple",
                    "baseUrl": "https://proxy.example.com",
                    "models": {"proxy-model": {"displayName": "Proxy Model"}},
                }
            },
            "streamSimple": lambda *_args: "not-core-provider-config",
        },
    )
    ai_registry, diagnostics_service = _build_session(mixed_stream)
    assert ai_registry.get_provider("proxy") is None
    assert any(
        record.code == "extension_runtime_bind_failed"
        and "must be registered through explicit API/OAuth APIs" in record.message
        for record in diagnostics_service.get_diagnostics()
    )

    mixed_flat_fields = ExtensionAPI(
        name="provider-ext", source_path=Path("/tmp/provider-ext.py")
    )
    mixed_flat_fields.register_provider(
        "proxy",
        {
            "baseUrl": "https://proxy.example.com",
            "endpoints": {
                "proxy-simple": {
                    "api": "proxy-simple",
                    "models": {"proxy-model": {"displayName": "Proxy Model"}},
                }
            },
        },
    )
    ai_registry, diagnostics_service = _build_session(mixed_flat_fields)
    assert ai_registry.get_provider("proxy") is None
    assert any(
        record.code == "extension_runtime_bind_failed"
        and "top-level baseUrl" in record.message
        for record in diagnostics_service.get_diagnostics()
    )


def test_agent_session_exposes_standard_scoped_models_and_resources(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.coding.session import AgentSession, ModelSelection
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    first = _model()
    second = Model(
        id="alt-model",
        name="Alt",
        provider="alt",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=64000,
            max_tokens=2048,
        ),
    )
    ai_registry = _ai_model_registry(first, second)
    loader = DefaultResourceLoader()
    session = AgentSession(
        agent=Agent(
            initial_state={"system_prompt": "", "model": first, "thinking_level": "low"}
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        model_registry=ModelRegistry(ai_registry=ai_registry),
        resource_loader=loader,
    )

    session.set_scoped_models(
        [
            {"model": first, "thinkingLevel": "low"},
            {
                "model": {
                    "provider": "alt",
                    "endpoint_id": "responses",
                    "model_id": "alt-model",
                },
                "thinkingLevel": "high",
            },
        ]
    )

    assert session.scoped_models[0]["model"] is first
    assert asyncio.run(session.cycle_model()) == ModelSelection(
        endpoint_id="responses", provider="alt", model_id="alt-model"
    )
    assert session.thinking_level == "high"
    assert session.resource_loader is loader
    assert isinstance(session.get_prompt_templates(), list)


def test_agent_session_exposes_pi_style_thinking_and_context_queries(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "low",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
    )
    asyncio.run(session.session_manager.append_message(_user_message("hello")))

    assert session.supports_thinking() is True
    assert session.supports_thinking() is True
    assert session.supports_thinking() is True
    assert session.supports_thinking() is True
    assert session.get_available_thinking_levels() == [
        "off",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert session.get_available_thinking_levels() == [
        "off",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert asyncio.run(session.cycle_thinking_level()) == "medium"
    assert session.get_context_usage()["messageCount"] == 1

    non_reasoning = Model(
        id="basic-model",
        name="Basic",
        provider="basic",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=64000,
            max_tokens=2048,
        ),
    )
    asyncio.run(session.set_model(non_reasoning))

    assert session.supports_thinking() is False
    assert session.supports_thinking() is False
    assert session.supports_thinking() is False
    assert session.supports_thinking() is False
    assert session.get_available_thinking_levels() == ["off"]
    assert session.get_available_thinking_levels() == ["off"]
    assert asyncio.run(session.cycle_thinking_level()) is None
    assert session.thinking_level == "off"


def test_agent_session_exposes_standard_runtime_facades(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import SettingsManager
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    settings = SettingsManager(project_settings_path=tmp_path / "settings.json")
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "low",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        settings_manager=settings,
    )

    control = session.session_control
    assert control is session
    assert control.session_id == session.session_id
    assert control.session_name == session.session_name
    assert session.is_retrying is False
    session.set_auto_retry_enabled(False)
    assert session.auto_retry_enabled is False
    assert control.auto_retry_enabled is False
    session.set_auto_compaction_enabled(False)
    assert session.auto_compaction_enabled is False
    assert control.auto_compaction_enabled is False
    session.abort_compaction()
    session.abort_compaction()
    session.abort_branch_summary()
    assert session.is_command_running is False
    assert session.has_pending_command_messages is False
    asyncio.run(
        session.record_bash_result(
            "echo hi",
            {"output": "hi\n", "exitCode": 0},
            exclude_from_context=True,
        )
    )
    assert session.get_session_context().messages == ()
    assert session.session_manager.get_entries()[-1].kind == "command.execution"


def test_agent_session_persists_queue_modes_to_settings(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import SettingsManager
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    settings_path = tmp_path / "settings.json"
    settings = SettingsManager(global_settings_path=settings_path)
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        settings_manager=settings,
    )

    session.set_steering_mode("all")
    session.set_follow_up_mode("all")

    reloaded = SettingsManager(global_settings_path=settings_path)
    assert reloaded.get_settings().steering_mode == "all"
    assert reloaded.get_settings().follow_up_mode == "all"


def test_agent_session_binds_extensions_before_session_start(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[str, tuple[str, ...]]] = []

    def _session_start(event, ctx):
        del event
        seen.append((ctx.cwd, tuple(ctx.get_active_tool_names())))

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=tmp_path / "demo.py",
                    hooks={"session_start": [_session_start]},
                )
            ]
        ),
    )
    asyncio.run(session.start_extension_runtime())

    assert seen == [("/tmp/project", tuple(session.get_active_tool_names()))]


def test_agent_session_extension_status_updates_footer_data_provider(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    def _session_start(event, ctx):
        del event
        ctx.set_status("deploy", "running")
        ctx.set_status("build", "queued")
        ctx.set_status("build", None)

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="status",
                    source_path=tmp_path / "status.py",
                    hooks={"session_start": [_session_start]},
                )
            ]
        ),
    )
    asyncio.run(session.start_extension_runtime())

    assert session.footer_data_provider.get_extension_statuses() == {
        "deploy": "running"
    }


def test_agent_session_footer_data_provider_tracks_available_provider_count(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionAPI, ExtensionRunner
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    ai_registry = _ai_model_registry(
        Model(id="alpha", provider="base-a", endpoint="anthropic-messages"),
        Model(id="beta", provider="base-a", endpoint="anthropic-messages"),
        Model(id="gamma", provider="base-b", endpoint="anthropic-messages"),
    )
    model_registry = ModelRegistry(ai_registry=ai_registry)
    api = ExtensionAPI(name="provider-ext", source_path=Path("/tmp/provider-ext.py"))
    api.register_provider(
        "proxy",
        {
            "endpoints": {
                "proxy-simple": {
                    "api": "proxy-simple",
                    "models": {"proxy-model": {"input": ["text"]}},
                }
            }
        },
    )

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        model_registry=model_registry,
        extension_runner=ExtensionRunner([api.build_loaded_extension()]),
    )

    assert session.footer_data_provider.get_available_provider_count() == 3

    api.unregister_provider("proxy")

    assert session.footer_data_provider.get_available_provider_count() == 2


def test_agent_session_exposes_available_model_details_for_metadata_consumers(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    detailed = Model(
        id="detail-model",
        provider="detail-provider",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text", "image"),
            context_window=64000,
            max_tokens=2048,
        ),
    )
    ai_registry = _ai_model_registry(detailed)
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        model_registry=ModelRegistry(ai_registry=ai_registry),
    )

    details = session.get_available_model_details()
    assert len(details) == 1
    model = details[0]
    assert model.id == detailed.id
    assert model.provider_id == detailed.provider_id
    assert model.endpoint_id == detailed.endpoint_id
    assert model.api == "anthropic-messages"
    assert model.capabilities == detailed.capabilities


def test_agent_session_disposes_footer_data_provider(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
    )
    changes: list[str | None] = []
    session.footer_data_provider.on_branch_change(changes.append)
    session.footer_data_provider.set_extension_status("deploy", "running")

    asyncio.run(session.dispose())
    session.footer_data_provider.set_cwd("/tmp/other-project")

    assert session.footer_data_provider.get_extension_statuses() == {}
    assert changes == []


def test_agent_session_disposal_paths_complete_pending_approvals(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    async def run(dispose_method: str) -> None:
        presented = asyncio.Event()
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="allow")
        )

        def present_request(payload: dict[str, object]) -> None:
            del payload
            presented.set()

        resolver.set_request_presenter(present_request)
        session = AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "",
                    "model": _model(),
                    "thinking_level": "off",
                }
            ),
            session_manager=await SessionManager.new(
                session_dir=tmp_path / dispose_method,
                cwd="/tmp/project",
                persist=False,
            ),
            approval_resolver=resolver,
        )
        pending = asyncio.create_task(
            resolver.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await presented.wait()

        await getattr(session, dispose_method)()
        decision = await pending

        assert decision.disposition == "deny"
        assert decision.reason == "Session closed before approval was resolved"

    asyncio.run(run("dispose"))
    asyncio.run(run("_dispose_after_session_shutdown"))


def test_agent_session_disposal_closes_approval_before_waiting_for_host(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    async def run(dispose_method: str) -> None:
        presented = asyncio.Event()
        decisions = []
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="allow")
        )
        resolver.set_request_presenter(lambda payload: presented.set())
        session = AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "",
                    "model": _model(),
                    "thinking_level": "off",
                }
            ),
            session_manager=await SessionManager.new(
                session_dir=tmp_path / f"host-{dispose_method}",
                cwd="/tmp/project",
                persist=False,
            ),
            approval_resolver=resolver,
        )

        async def wait_for_approval() -> None:
            decisions.append(
                await resolver.resolve(ApprovalRequest(tool_name="write", arguments={}))
            )

        active_run = asyncio.create_task(
            session._composition.session_runtime.host_runtime.run(wait_for_approval)
        )
        await presented.wait()
        await asyncio.wait_for(getattr(session, dispose_method)(), timeout=0.2)
        await active_run
        late_decision = await resolver.resolve(
            ApprovalRequest(tool_name="edit", arguments={})
        )

        assert decisions[0].disposition == "deny"
        assert late_decision.disposition == "deny"
        assert late_decision.reason == "Session closed before approval was resolved"

    asyncio.run(run("dispose"))
    asyncio.run(run("_dispose_after_session_shutdown"))


def test_agent_session_presenter_detach_denies_pending_approvals(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    async def run() -> None:
        presented = asyncio.Event()
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="allow")
        )
        session = AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "",
                    "model": _model(),
                    "thinking_level": "off",
                }
            ),
            session_manager=await SessionManager.new(
                session_dir=tmp_path,
                cwd="/tmp/project",
                persist=False,
            ),
            approval_resolver=resolver,
        )
        session.set_approval_presenter(lambda payload: presented.set())
        pending = asyncio.create_task(
            resolver.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await presented.wait()

        session.set_approval_presenter(None)
        decision = await pending

        assert decision.disposition == "deny"
        assert decision.reason == (
            "Approval presenter closed before approval was resolved"
        )
        assert resolver._request_presenter is None

    asyncio.run(run())


def test_agent_session_presenter_rebind_reopens_active_approval_generation(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    async def run() -> None:
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        )
        session = AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "",
                    "model": _model(),
                    "thinking_level": "off",
                }
            ),
            session_manager=await SessionManager.new(
                session_dir=tmp_path,
                cwd="/tmp/project",
                persist=False,
            ),
            approval_resolver=resolver,
        )
        session.set_approval_presenter(lambda payload: None)
        session.set_approval_presenter(None)

        presented = asyncio.Event()
        session.set_approval_presenter(lambda payload: presented.set())
        pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="rebound-session-approval",
                )
            )
        )
        await asyncio.wait_for(presented.wait(), timeout=0.5)
        await session.handle_screen_approval(
            {"action_id": "rebound-session-approval", "approved": True}
        )

        assert (await pending).disposition == "allow"
        await session.dispose()

    asyncio.run(run())


async def _approval_interaction_session(tmp_path):
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.approval import (
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=await SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=False,
        ),
        approval_resolver=resolver,
    )
    interaction = session.approval_interaction
    assert interaction is not None
    return session, resolver, interaction


def test_agent_session_approval_presenter_replacement_replays_pending(
    tmp_path,
) -> None:
    from loushang.harness.approval import ApprovalRequest

    async def run() -> None:
        session, resolver, interaction = await _approval_interaction_session(tmp_path)
        first_presented = asyncio.Event()
        first_payloads: list[dict[str, object]] = []

        def present_first(payload: dict[str, object]) -> None:
            first_payloads.append(payload)
            first_presented.set()

        interaction.bind_presenter(present_first)
        pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="replace-presenter",
                )
            )
        )
        await asyncio.wait_for(first_presented.wait(), timeout=0.5)

        second_presented = asyncio.Event()
        second_payloads: list[dict[str, object]] = []

        def present_second(payload: dict[str, object]) -> None:
            second_payloads.append(payload)
            second_presented.set()

        second = interaction.bind_presenter(present_second)
        await asyncio.wait_for(second_presented.wait(), timeout=0.5)

        assert not pending.done()
        assert [payload["action_id"] for payload in first_payloads] == [
            "replace-presenter"
        ]
        assert [payload["action_id"] for payload in second_payloads] == [
            "replace-presenter"
        ]
        assert await interaction.respond(
            "replace-presenter",
            outcome="allow_once",
        )
        assert (await pending).disposition == "allow"
        second.close()
        await session.dispose()

    asyncio.run(run())


def test_agent_session_superseded_approval_lease_cannot_close_replacement(
    tmp_path,
) -> None:
    from loushang.harness.approval import ApprovalRequest

    async def run() -> None:
        session, resolver, interaction = await _approval_interaction_session(tmp_path)
        first_presented = asyncio.Event()
        first = interaction.bind_presenter(lambda _payload: first_presented.set())
        pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="superseded-lease",
                )
            )
        )
        await asyncio.wait_for(first_presented.wait(), timeout=0.5)

        second_presented = asyncio.Event()
        second = interaction.bind_presenter(lambda _payload: second_presented.set())
        await asyncio.wait_for(second_presented.wait(), timeout=0.5)
        first.close()

        assert not pending.done()
        pending_ids = [
            item.permission_id for item in resolver.permissions_snapshot().pending
        ]
        assert pending_ids == ["superseded-lease"]
        assert await interaction.respond(
            "superseded-lease",
            outcome="allow_once",
        )
        assert (await pending).disposition == "allow"
        second.close()
        await session.dispose()

    asyncio.run(run())


def test_agent_session_current_approval_lease_close_denies_pending(
    tmp_path,
) -> None:
    from loushang.harness.approval import ApprovalRequest

    async def run() -> None:
        session, resolver, interaction = await _approval_interaction_session(tmp_path)
        first_presented = asyncio.Event()
        interaction.bind_presenter(lambda _payload: first_presented.set())
        pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="current-lease-close",
                )
            )
        )
        await asyncio.wait_for(first_presented.wait(), timeout=0.5)

        second_presented = asyncio.Event()
        second = interaction.bind_presenter(lambda _payload: second_presented.set())
        await asyncio.wait_for(second_presented.wait(), timeout=0.5)
        second.close("Replacement presenter disconnected")

        decision = await pending
        assert decision.disposition == "deny"
        assert decision.reason == "Replacement presenter disconnected"
        assert resolver.permissions_snapshot().pending == ()
        await session.dispose()

    asyncio.run(run())


def test_agent_session_disposal_finalizes_when_host_dispose_fails(tmp_path) -> None:
    import pytest

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    class FailingHostRuntime:
        async def dispose(self) -> None:
            raise RuntimeError("host dispose failed")

    async def run(dispose_method: str) -> None:
        presented = asyncio.Event()
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="allow")
        )
        resolver.set_request_presenter(lambda payload: presented.set())
        session = AgentSession(
            agent=Agent(
                initial_state={
                    "system_prompt": "",
                    "model": _model(),
                    "thinking_level": "off",
                }
            ),
            session_manager=await SessionManager.new(
                session_dir=tmp_path / dispose_method,
                cwd="/tmp/project",
                persist=False,
            ),
            approval_resolver=resolver,
        )
        session._composition.session_runtime._host_runtime = FailingHostRuntime()  # type: ignore[assignment]
        pending = asyncio.create_task(
            resolver.resolve(ApprovalRequest(tool_name="write", arguments={}))
        )
        await presented.wait()

        with pytest.raises(RuntimeError, match="host dispose failed"):
            await getattr(session, dispose_method)()
        decision = await pending

        assert decision.disposition == "deny"
        assert decision.reason == "Session closed before approval was resolved"

    asyncio.run(run("dispose"))
    asyncio.run(run("_dispose_after_session_shutdown"))


def test_agent_session_extension_runtime_actions_update_session_store(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[object, ...]] = []

    async def _before(event, ctx):
        del event
        entry_id = await ctx.session_manager.append_message(_user_message("root"))
        await ctx.append_entry("demo_state", {"enabled": True})
        await ctx.send_message(
            {
                "customType": "demo_notice",
                "content": "visible note",
                "display": True,
                "details": {"source": "extension"},
            }
        )
        await ctx.set_session_name("Demo Session")
        await ctx.set_label(entry_id, "Root")
        seen.append(
            (
                ctx.get_session_name(),
                ctx.get_active_tool_names(),
                len(ctx.get_all_tools()),
                ctx.list_commands(),
            )
        )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=tmp_path / "demo.py",
                    hooks={"session_start": [_before]},
                )
            ]
        ),
    )
    asyncio.run(session.start_extension_runtime())

    entries = manager.get_entries()
    assert [entry.kind for entry in entries] == [
        "agent.message",
        "extension.data",
        "application.message",
        "conversation.metadata_patch",
        "record.annotation_patch",
    ]
    assert entries[1].payload.extension_type == "demo_state"
    assert entries[1].payload.data == {"enabled": True}
    assert entries[2].payload.custom_type == "demo_notice"
    assert entries[2].payload.content == "visible note"
    assert entries[2].payload.details == {"source": "extension"}
    assert manager.get_session_record().metadata.name == "Demo Session"
    assert manager.get_label(entries[0].record_id) == "Root"
    assert [
        getattr(message, "role", None)
        for message in session.get_session_context().messages
    ] == [
        "user",
        "application",
    ]
    assert seen == [
        (
            "Demo Session",
            session.get_active_tool_names(),
            len(session.get_all_tools()),
            session.list_commands(),
        )
    ]


def test_agent_session_extension_send_user_message_triggers_turn_without_command_preflight(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    prompted_texts: list[str] = []
    nested_command_calls: list[str] = []

    async def stream_fn(model, context, options=None):
        del model, options
        prompted_texts.append(context.messages[-1].content[0].text)
        return _stream_with_final_message(_assistant_text_message("done"))

    async def _emit_command(args: str, ctx):
        del args
        await ctx.send_user_message("/nested should stay text")

    async def _nested_command(args: str, ctx):
        del ctx
        nested_command_calls.append(args)
        return "nested"

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        session = AgentSession(
            agent=Agent(stream_fn=stream_fn),
            session_manager=manager,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="demo",
                        source_path=tmp_path / "demo.py",
                        commands={
                            "emit": RegisteredCommand(
                                name="emit", handler=_emit_command
                            ),
                            "nested": RegisteredCommand(
                                name="nested", handler=_nested_command
                            ),
                        },
                    )
                ]
            ),
        )

        result = await session.execute_command_async("emit", "")
        for _ in range(20):
            if prompted_texts:
                break
            await asyncio.sleep(0.01)

        assert result.result is None
        assert prompted_texts == ["/nested should stay text"]
        assert nested_command_calls == []
        assert [
            getattr(message, "role", None)
            for message in session.get_session_context().messages
        ] == [
            "user",
            "assistant",
        ]

    asyncio.run(scenario())


def test_agent_session_extension_send_user_message_queues_while_streaming(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    async def _queue_command(args: str, ctx):
        del args
        await ctx.send_user_message("queued steer", {"deliverAs": "steer"})
        await ctx.send_user_message("queued follow", {"deliverAs": "followUp"})

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        agent = Agent()
        session = AgentSession(
            agent=agent,
            session_manager=manager,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="demo",
                        source_path=tmp_path / "demo.py",
                        commands={
                            "queue": RegisteredCommand(
                                name="queue", handler=_queue_command
                            )
                        },
                    )
                ]
            ),
        )
        agent.state.is_streaming = True

        result = await session.execute_command_async("queue", "")
        await asyncio.sleep(0.01)

        assert result.result is None
        assert session.get_state().steering == ["queued steer"]
        assert session.get_state().follow_up == ["queued follow"]

    asyncio.run(scenario())


def test_agent_session_send_message_next_turn_is_appended_after_user_message(
    tmp_path,
) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    async def stream_fn(model, context, options=None):
        del model, context, options
        return _stream_with_final_message(_assistant_text_message("ack"))

    async def _queue_next_turn(args: str, ctx):
        del args
        await ctx.send_message(
            {"customType": "queued_note", "content": "queued note"},
            {"deliverAs": "nextTurn"},
        )

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        session = AgentSession(
            agent=Agent(stream_fn=stream_fn),
            session_manager=manager,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="next-turn",
                        source_path=tmp_path / "demo.py",
                        commands={
                            "queue": RegisteredCommand(
                                name="queue", handler=_queue_next_turn
                            )
                        },
                    )
                ]
            ),
        )

        result = await session.execute_command_async("queue", "")
        assert result.result is None
        await session.prompt("hello")

        assert [message.role for message in session.messages[:2]] == [
            "user",
            "application",
        ]
        assert [
            message.custom_type
            for message in session.messages
            if getattr(message, "role", None) == "application"
        ] == ["queued_note"]

    asyncio.run(scenario())


def test_agent_session_send_custom_message_public_api_persists_and_emits_events(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
    )
    events: list[tuple[str, str]] = []

    def listener(event) -> None:
        if event["type"] in {"message_start", "message_end"}:
            events.append((event["type"], event["message"].custom_type))

    session.subscribe(listener)

    asyncio.run(
        session.send_message(
            {
                "customType": "demo_notice",
                "content": "visible note",
                "display": True,
                "details": {"source": "sdk"},
            }
        )
    )

    assert [entry.kind for entry in session.session_manager.get_entries()] == [
        "application.message"
    ]
    assert [message.role for message in session.messages] == ["application"]
    assert events == [("message_start", "demo_notice"), ("message_end", "demo_notice")]


def test_agent_session_send_user_message_public_api_triggers_turn_without_command_preflight(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    prompted_texts: list[str] = []
    nested_command_calls: list[str] = []

    async def stream_fn(model, context, options=None):
        del model, options
        prompted_texts.append(context.messages[-1].content[0].text)
        return _stream_with_final_message(_assistant_text_message("done"))

    async def _nested_command(args: str, ctx):
        del ctx
        nested_command_calls.append(args)
        return "nested"

    async def scenario() -> None:
        session = AgentSession(
            agent=Agent(stream_fn=stream_fn),
            session_manager=await SessionManager.new(
                session_dir=tmp_path, cwd="/tmp/project", persist=False
            ),
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="demo",
                        source_path=tmp_path / "demo.py",
                        commands={
                            "nested": RegisteredCommand(
                                name="nested", handler=_nested_command
                            )
                        },
                    )
                ]
            ),
        )

        await session.send_user_message("/nested should stay text")

        assert prompted_texts == ["/nested should stay text"]
        assert nested_command_calls == []
        assert [
            getattr(message, "role", None)
            for message in session.get_session_context().messages
        ] == [
            "user",
            "assistant",
        ]

    asyncio.run(scenario())


def test_agent_session_reload_extensions_refreshes_resources_before_session_start(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionResourceContribution,
        ExtensionRunner,
        LoadedExtension,
    )
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
    )

    seen: list[list[str]] = []
    reload_calls: list[str] = []

    def _session_start(event, ctx):
        del event
        seen.append(ctx.get_system_prompt().splitlines())

    def _resources_discover(event, ctx):
        del event, ctx
        return ExtensionResourceContribution(
            prompt_descriptors=[
                PromptFragmentDescriptor(
                    name="ext-refresh",
                    source_path=Path("/tmp/ext-refresh.md"),
                    text="extension refresh prompt",
                )
            ]
        )

    class _ReloadingLoader(DefaultResourceLoader):
        def reload_resources(self, cwd):
            reload_calls.append(str(cwd))
            return ResourceBundle(cwd=Path(cwd), prompt_fragments=["reloaded prompt"])

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "base prompt",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=Path("/tmp/demo.py"),
                    hooks={
                        "session_start": [_session_start],
                        "resources_discover": [_resources_discover],
                    },
                )
            ]
        ),
        resource_loader=_ReloadingLoader(),
    )

    seen.clear()
    asyncio.run(session.reload_extension_runtime())

    assert seen == [
        [
            "base prompt",
            "",
            "reloaded prompt",
            "",
            "extension refresh prompt",
            "",
            *_runtime_footer_lines("/tmp/project"),
        ]
    ]
    assert reload_calls == ["/tmp/project"]
    assert session.resource_bundle is not None
    assert session.resource_bundle.prompt_fragments == [
        "reloaded prompt",
        "extension refresh prompt",
    ]
    assert "extension refresh prompt" in session.agent.system_prompt


def test_agent_session_set_active_tools_emits_session_refresh(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.tools.core import tool
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    @tool()
    async def read_file() -> str:
        return "read"

    @tool()
    async def grep_file() -> str:
        return "grep"

    seen: list[tuple[str, tuple[str, ...]]] = []

    def _session_refresh(event, ctx):
        seen.append((event.reason, tuple(ctx.get_active_tool_names())))

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    registry.register_tool(direct_tool(read_file))
    registry.register_tool(direct_tool(grep_file))
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=tmp_path / "demo.py",
                    hooks={"session_refresh": [_session_refresh]},
                )
            ]
        ),
        tool_registry=registry,
        active_tool_names=["read_file"],
    )

    asyncio.run(session.set_active_tools(["read_file", "grep_file"]))

    assert seen == [("active_tools_changed", ("read_file", "grep_file"))]


def test_agent_session_refresh_does_not_reemit_session_start(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.tools.core import tool
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    @tool()
    async def read_file() -> str:
        return "read"

    @tool()
    async def grep_file() -> str:
        return "grep"

    start_events: list[str] = []
    refresh_events: list[str] = []

    def _session_start(event, ctx):
        del event, ctx
        start_events.append("startup")

    def _session_refresh(event, ctx):
        del ctx
        refresh_events.append(event.reason)

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    registry.register_tool(direct_tool(read_file))
    registry.register_tool(direct_tool(grep_file))
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=tmp_path / "demo.py",
                    hooks={
                        "session_start": [_session_start],
                        "session_refresh": [_session_refresh],
                    },
                )
            ]
        ),
        tool_registry=registry,
        active_tool_names=["read_file"],
    )

    asyncio.run(session.start_extension_runtime())
    asyncio.run(session.set_active_tools(["read_file", "grep_file"]))

    assert start_events == ["startup"]
    assert refresh_events == ["active_tools_changed"]


def test_agent_session_set_extension_ui_context_rebinds_context_without_lifecycle_hooks(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    start_events: list[bool] = []
    refresh_events: list[tuple[str, bool]] = []

    def _session_start(event, ctx):
        del event
        start_events.append(ctx.has_ui)

    def _session_refresh(event, ctx):
        refresh_events.append((event.reason, ctx.has_ui))

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=tmp_path / "demo.py",
                hooks={
                    "session_start": [_session_start],
                    "session_refresh": [_session_refresh],
                },
            )
        ]
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=runner,
    )
    context = runner.create_command_context(fallback_cwd="/tmp/project")

    asyncio.run(session.start_extension_runtime())
    session.set_extension_ui_context(object())

    assert start_events == [False]
    assert refresh_events == []
    assert context.has_ui is True


def test_agent_session_dispose_invalidates_extension_contexts_after_shutdown_hooks(
    tmp_path,
) -> None:
    import pytest

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[str] = []
    captured_context = None

    def _session_shutdown(event, ctx):
        del event, ctx
        seen.append(captured_context.cwd)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=tmp_path / "demo.py",
                hooks={"session_shutdown": [_session_shutdown]},
            )
        ]
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=runner,
    )
    captured_context = runner.create_command_context(fallback_cwd="/tmp/project")

    asyncio.run(session.dispose())

    assert seen == ["/tmp/project"]
    with pytest.raises(
        RuntimeError, match="stale after session replacement or shutdown"
    ):
        captured_context.cwd


def test_agent_session_dispose_invalidates_extension_contexts_when_shutdown_emit_fails(
    tmp_path,
) -> None:
    import pytest

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    runner = ExtensionRunner(
        [LoadedExtension(name="demo", source_path=tmp_path / "demo.py")]
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=runner,
    )
    captured_context = runner.create_command_context(fallback_cwd="/tmp/project")

    async def _emit_session_shutdown(_event) -> None:
        raise RuntimeError("shutdown transport boom")

    runner.emit_session_shutdown = _emit_session_shutdown  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="shutdown transport boom"):
        asyncio.run(session.dispose())

    with pytest.raises(
        RuntimeError, match="stale after session replacement or shutdown"
    ):
        captured_context.cwd


def test_agent_session_set_model_emits_session_refresh(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    next_model = Model(
        id="next-model",
        name="Next",
        provider="demo",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=64000,
            max_tokens=2048,
        ),
    )

    seen: list[tuple[str, object | None]] = []

    def _session_refresh(event, ctx):
        seen.append((event.reason, ctx.get_model_selection()))

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=tmp_path / "demo.py",
                    hooks={"session_refresh": [_session_refresh]},
                )
            ]
        ),
    )

    asyncio.run(session.set_model(next_model))

    assert seen == [("model_selection_changed", session.get_model_selection())]


def test_agent_session_invalid_extension_refresh_model_change_keeps_top_level_model(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    next_model = Model(
        id="next-model",
        name="Next",
        provider="demo",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=64000,
            max_tokens=2048,
        ),
    )

    async def _session_refresh(event, ctx):
        del event
        await ctx.set_model(object())

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    diagnostics = DiagnosticsService()
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=tmp_path / "demo.py",
                    hooks={"session_refresh": [_session_refresh]},
                )
            ]
        ),
        diagnostics_service=diagnostics,
    )

    asyncio.run(session.set_model(next_model))

    diagnostics = [
        record
        for record in session.get_last_diagnostics()
        if record.code == "extension_session_refresh_failed"
    ]

    assert session.agent.model is next_model
    assert session.get_model_selection() is not None
    assert session.get_model_selection().provider == "demo"
    assert session.get_model_selection().model_id == "next-model"
    assert len(diagnostics) == 1
    assert diagnostics[0].type == "error"
    assert session.get_last_error_report() is not None
    assert (
        session.get_last_error_report().primary.code
        == "extension_session_refresh_failed"
    )


def test_extension_session_refresh_actions_do_not_recursively_emit_refresh(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.tools.core import tool
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    @tool()
    async def read_file() -> str:
        return "read"

    @tool()
    async def grep_file() -> str:
        return "grep"

    refresh_reasons: list[str] = []

    async def _session_refresh(event, ctx):
        refresh_reasons.append(event.reason)
        await ctx.set_active_tools(["read_file", "grep_file"])

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    registry.register_tool(direct_tool(read_file))
    registry.register_tool(direct_tool(grep_file))
    next_model = Model(
        id="next-model",
        name="Next",
        provider="demo",
        endpoint="responses",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=64000,
            max_tokens=2048,
        ),
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=tmp_path / "demo.py",
                    hooks={"session_refresh": [_session_refresh]},
                )
            ]
        ),
        tool_registry=registry,
        active_tool_names=["read_file"],
    )

    asyncio.run(session.set_model(next_model))

    assert refresh_reasons == ["model_selection_changed"]


def test_agent_session_extension_can_request_resource_refresh(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    requested: list[str] = []

    def _before(event, ctx):
        del event
        ctx.request_resource_refresh()
        requested.append(ctx.cwd)

    loader = DefaultResourceLoader()
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(
        agent=Agent(),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=Path("/tmp/demo.py"),
                    hooks={"session_start": [_before]},
                )
            ]
        ),
        resource_loader=loader,
    )
    asyncio.run(session.start_extension_runtime())

    assert requested == ["/tmp/project"]
    assert session.resource_bundle is not None


def test_agent_session_extension_request_resource_refresh_is_nonfatal_without_loader(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    requested: list[str] = []

    def _before(event, ctx):
        del event
        ctx.request_resource_refresh()
        requested.append(ctx.cwd)

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=Path("/tmp/demo.py"),
                    hooks={"session_start": [_before]},
                )
            ]
        ),
    )
    asyncio.run(session.start_extension_runtime())

    assert requested == ["/tmp/project"]
    assert (
        session.resource_bundle is None
        or session.resource_bundle.cwd == manager.get_cwd()
    )


def test_agent_session_resource_refresh_rebuilds_prompt_and_tools_without_emitting_session_refresh(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.tools.core import tool
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    @tool()
    async def read_file() -> str:
        return "read"

    refresh_reasons: list[str] = []

    def _session_refresh(event, ctx):
        del ctx
        refresh_reasons.append(event.reason)

    class _ReloadingLoader(DefaultResourceLoader):
        def reload_resources(self, cwd):
            return ResourceBundle(cwd=Path(cwd), prompt_fragments=["reloaded prompt"])

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    registry.register_tool(direct_tool(read_file))
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "base prompt",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=Path("/tmp/demo.py"),
                    hooks={"session_refresh": [_session_refresh]},
                )
            ]
        ),
        resource_loader=_ReloadingLoader(),
        tool_registry=registry,
        active_tool_names=["read_file"],
        resource_bundle=ResourceBundle(cwd=Path("/tmp/project")),
        base_prompt="base prompt",
    )

    asyncio.run(session.refresh_resources())

    assert refresh_reasons == []
    assert session.resource_bundle is not None
    assert session.resource_bundle.prompt_fragments == ["reloaded prompt"]
    assert session.get_active_tool_names() == ["read_file"]
    assert [tool.name for tool in session.agent.tools] == ["read_file"]
    assert "reloaded prompt" in session.agent.system_prompt


def test_agent_session_records_reload_failures_as_diagnostics(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.resources.types import ResourceBundle

    class _BrokenReloadLoader(DefaultResourceLoader):
        def reload_resources(self, cwd):
            del cwd
            raise RuntimeError("reload boom")

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    diagnostics = DiagnosticsService()
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [LoadedExtension(name="demo", source_path=tmp_path / "demo.py", hooks={})]
        ),
        resource_loader=_BrokenReloadLoader(),
        resource_bundle=ResourceBundle(cwd=tmp_path),
        diagnostics_service=diagnostics,
    )

    asyncio.run(session.reload_extension_runtime())

    records = [
        record
        for record in session.get_last_diagnostics()
        if record.code == "extension_resource_refresh_failed"
    ]

    assert len(records) == 1
    assert records[0].type == "error"


def test_agent_session_records_bind_failures_as_diagnostics(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.extensions.agent import (
        ExtensionResourceContribution,
        ExtensionRunner,
        LoadedExtension,
    )
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
    )

    class _BrokenBindRunner(ExtensionRunner):
        def __init__(self, extensions) -> None:
            super().__init__(extensions)
            self._bind_calls = 0

        def bind_runtime(self, bindings) -> None:
            self._bind_calls += 1
            if self._bind_calls == 1:
                return super().bind_runtime(bindings)
            del bindings
            raise RuntimeError("bind boom")

    class _ReloadingLoader(DefaultResourceLoader):
        def reload_resources(self, cwd):
            return ResourceBundle(cwd=Path(cwd), prompt_fragments=["reloaded prompt"])

    def _resources_discover(event, ctx):
        del event, ctx
        return ExtensionResourceContribution(
            prompt_descriptors=[
                PromptFragmentDescriptor(
                    name="ext-refresh",
                    source_path=Path("/tmp/ext-refresh.md"),
                    text="extension refresh prompt",
                )
            ]
        )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    diagnostics = DiagnosticsService()
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=_BrokenBindRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=tmp_path / "demo.py",
                    hooks={"resources_discover": [_resources_discover]},
                )
            ]
        ),
        resource_loader=_ReloadingLoader(),
        resource_bundle=ResourceBundle(cwd=tmp_path),
        diagnostics_service=diagnostics,
    )

    asyncio.run(session.reload_extension_runtime())

    records = [
        record
        for record in session.get_last_diagnostics()
        if record.code == "extension_runtime_bind_failed"
    ]

    assert len(records) == 1
    assert records[0].type == "error"


def test_agent_session_exposes_session_metadata_and_messages(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=True)
    )
    asyncio.run(manager.append_session_info(" Demo Session "))
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="hi")],
                timestamp=0.0,
            )
        )
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        diagnostics_service=DiagnosticsService(),
    )

    assert session.messages == session.agent.state.messages
    assert session.get_session_file() == manager.get_session_file()
    assert session.session_id == manager.get_session_record().session_id
    assert session.session_name == "Demo Session"


def test_agent_session_exposes_context_usage_and_stats(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.ai.types import ToolCall, ToolResultMessage
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="hi")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(
        manager.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[
                    TextPart(type="text", text="reading"),
                    ToolCall(
                        type="toolCall",
                        id="tool-1",
                        name="read",
                        arguments={"path": "README.md"},
                    ),
                ],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=Usage(
                    input=2,
                    output=3,
                    cache_read=5,
                    cache_write=7,
                    total_tokens=17,
                    cost={"total": 0.25},
                ),
                stop_reason="toolUse",
                error_message=None,
                timestamp=1.0,
            )
        )
    )
    asyncio.run(
        manager.append_message(
            ToolResultMessage(
                role="toolResult",
                tool_call_id="tool-1",
                tool_name="read",
                content=[TextPart(type="text", text="ok")],
                is_error=False,
                timestamp=2.0,
            )
        )
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
    )

    usage = session.get_context_usage()
    assert usage is not None
    pi_stats = session.get_session_stats()
    pi_usage = pi_stats["context_usage"]
    assert pi_stats | {"context_usage": None} == {
        "session_file": None,
        "session_id": session.session_id,
        "user_messages": 1,
        "assistant_messages": 1,
        "tool_calls": 1,
        "tool_results": 1,
        "total_messages": 3,
        "tokens": {
            "input": 2,
            "output": 3,
            "cache_read": 5,
            "cache_write": 7,
            "total": 17,
        },
        "cost": 0.25,
        "context_usage": None,
        "latest_compaction": None,
    }
    assert isinstance(pi_usage, dict)
    assert pi_usage == usage
    assert pi_usage["messageCount"] == usage["messageCount"]
    assert pi_usage["estimatedContextTokens"] == usage["estimatedContextTokens"]
    assert pi_usage["contextWindow"] == usage["contextWindow"]
    assert pi_usage["compactPercent"] == usage["compactPercent"]
    assert pi_usage["thresholdReason"] == usage["thresholdReason"]
    assert "message_count" not in pi_usage
    assert not hasattr(session, "getContextUsage")
    assert not hasattr(session, "getSessionStats")
    assert not hasattr(session, "get_stats")


def test_agent_session_exposes_session_state_runtime_queue(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
    )

    session.steer("adjust current task")
    session.follow_up("continue later")

    runtime_state = session.get_state()

    assert runtime_state.run.status == "idle"
    assert runtime_state.steering == ["adjust current task"]
    assert runtime_state.follow_up == ["continue later"]
    assert runtime_state.is_compacting is False
    assert runtime_state.is_retrying is False
    assert runtime_state.thinking_level == "off"
    assert runtime_state.model_selection is not None
    assert runtime_state.model_selection.provider == "faux"
    assert runtime_state.model_selection.model_id == "faux-model"


def test_agent_session_set_session_name_emits_session_info_changed(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
    )
    events: list[object] = []
    session.subscribe(events.append)

    asyncio.run(session.set_session_name("Demo"))

    assert session.session_name == "Demo"
    assert events == [{"type": "session_info_changed", "name": "Demo"}]


def test_agent_session_exposes_session_scoped_diagnostics(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService

    diagnostics = DiagnosticsService()
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        diagnostics_service=diagnostics,
    )
    diagnostics.record(
        diagnostics.normalize_exception(
            code="current_session_error",
            exc="boom",
            phase="runtime",
            source="session",
            session_id=session.session_id,
        )
    )
    diagnostics.record(
        diagnostics.normalize_exception(
            code="other_session_error",
            exc="other",
            phase="runtime",
            source="session",
            session_id="other-session",
        )
    )

    assert [record.code for record in session.get_session_diagnostics()] == [
        "current_session_error"
    ]
    assert [
        record.code
        for record in session.get_session_diagnostics(
            DiagnosticsQuery(code="current_session_error")
        )
    ] == ["current_session_error"]


def test_agent_session_get_packages_projects_materializer_state(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    source = "https://packages.example.invalid/review-pack.git"
    settings = SettingsManager(ControlConfig(plugin_sources=(source,)))
    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    materializer.prepare_remote_source(source)
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        package_materializer=materializer,
    )

    packages = session.get_packages()

    assert packages[0]["lifecycle"] == "materialization_pending"
    assert packages[0]["path"] == str(tmp_path / "packages" / "review-pack")


def test_agent_session_records_remote_package_manifest_diagnostics(tmp_path) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.security import PackageSecurityPolicy
    from loushang.harness.resources.packages.source import PackageSourceConfig

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        (record.target_path / "plugin.json").write_text("{not json", encoding="utf-8")
        return record.with_lifecycle("installed", target_path=record.target_path)

    diagnostics = DiagnosticsService()
    settings = SettingsManager(ControlConfig())
    settings.set_package_sources((PackageSourceConfig(source=source),), scope="session")
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
        security_policy=PackageSecurityPolicy(
            trusted_hosts=("packages.example.invalid",)
        ),
    )
    asyncio.run(materializer.materialize_remote_source(source))
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        package_materializer=materializer,
        diagnostics_service=diagnostics,
    )

    packages = session.get_packages()

    assert packages[0]["manifestDiagnostics"][0]["code"] == "invalid_package_manifest"
    records = diagnostics.get_diagnostics(code="invalid_package_manifest")
    assert len(records) == 1
    assert records[0].phase == "resource_loading"
    assert records[0].source == "package"
    assert (
        records[0].source_path == tmp_path / "packages" / "review-pack" / "plugin.json"
    )


def test_agent_session_records_package_catalog_diagnostics(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text("{not json", encoding="utf-8")
    diagnostics = DiagnosticsService()
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=SettingsManager(ControlConfig()),
        diagnostics_service=diagnostics,
    )

    packages = session.get_packages(catalog_path=str(catalog_path))

    assert packages[0]["catalogDiagnostics"][0]["code"] == "invalid_package_catalog"
    records = diagnostics.get_diagnostics(code="invalid_package_catalog")
    assert len(records) == 1
    assert records[0].phase == "resource_loading"
    assert records[0].source == "package"
    assert records[0].source_path == catalog_path


def test_agent_session_materialize_package_returns_policy_denied_record(
    tmp_path,
) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    source = "http://packages.example.invalid/review-pack.git"
    settings = SettingsManager(ControlConfig(plugin_sources=(source,)))
    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        package_materializer=materializer,
    )

    record = asyncio.run(session.materialize_package(source))
    packages = session.get_packages()

    assert record["lifecycle"] == "failed"
    assert record["security"] == "denied"
    assert packages[0]["lifecycle"] == "failed"
    assert packages[0]["security"] == "denied"


def test_agent_session_updates_and_removes_materialized_packages(tmp_path) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"
    settings = SettingsManager(ControlConfig(plugin_sources=(source,)))
    versions = ["1.0.0", "2.0.0"]

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True, exist_ok=True)
        (record.target_path / "plugin.json").write_text(
            json.dumps({"name": "review-pack", "version": versions.pop(0)}),
            encoding="utf-8",
        )
        return record.with_lifecycle("installed")

    materializer = PackageMaterializer(
        install_root=tmp_path / "packages", backend=backend
    )
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        package_materializer=materializer,
    )

    installed = asyncio.run(session.materialize_package(source))
    updated = asyncio.run(session.update_package(source))

    assert installed["lifecycle"] == "installed"
    assert updated["lifecycle"] == "installed"
    assert (
        json.loads(
            (tmp_path / "packages" / "review-pack" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )["version"]
        == "2.0.0"
    )
    removed = session.remove_package(source)
    assert removed["lifecycle"] == "remote_registered"
    assert (tmp_path / "packages" / "review-pack").exists() is False


def test_agent_session_installs_and_uninstalls_package_with_settings(tmp_path) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True, exist_ok=True)
        return record.with_lifecycle("installed")

    settings = SettingsManager(ControlConfig())
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages", backend=backend
    )
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        package_materializer=materializer,
    )

    installed = asyncio.run(session.install_package(source))

    assert installed["lifecycle"] == "installed"
    assert [package.source for package in settings.get_package_sources()] == [source]
    assert settings.get_plugin_sources() == []
    uninstalled = session.uninstall_package(source)
    assert uninstalled["lifecycle"] == "remote_registered"
    assert settings.get_package_sources() == []
    assert materializer.get_record(source) is None
    assert (
        json.loads((tmp_path / "package-lock.json").read_text(encoding="utf-8"))[
            "packages"
        ]
        == []
    )


def test_agent_session_installs_and_uninstalls_local_package_with_settings(
    tmp_path,
) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    local_package = tmp_path / "local-pack"
    local_package.mkdir()
    settings = SettingsManager(ControlConfig())
    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        package_materializer=materializer,
    )

    installed = asyncio.run(
        session.install_package(str(local_package), scope="project")
    )

    assert installed["lifecycle"] == "installed"
    assert installed["source"] == str(local_package)
    assert installed["targetPath"] == str(local_package.resolve())
    assert [package.source for package in settings.get_package_sources()] == [
        str(local_package)
    ]
    uninstalled = session.uninstall_package(str(local_package), scope="project")
    assert uninstalled["lifecycle"] == "remote_registered"
    assert settings.get_package_sources() == []


def test_agent_session_install_package_does_not_persist_failed_materialization(
    tmp_path,
) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        return record.with_lifecycle("failed", error_message="clone failed")

    settings = SettingsManager(ControlConfig())
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages", backend=backend
    )
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        package_materializer=materializer,
    )

    installed = asyncio.run(session.install_package(source))

    assert installed["lifecycle"] == "failed"
    assert settings.get_package_sources() == []
    assert session.get_packages() == []


def test_agent_session_install_package_refreshes_resources_for_current_session(
    tmp_path,
) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        (record.target_path / "prompts").mkdir(parents=True, exist_ok=True)
        (record.target_path / "skills" / "review").mkdir(parents=True, exist_ok=True)
        (record.target_path / "prompts" / "review.md").write_text(
            "Package review prompt", encoding="utf-8"
        )
        (record.target_path / "skills" / "review" / "SKILL.md").write_text(
            "Package review skill", encoding="utf-8"
        )
        return record.with_lifecycle("installed")

    settings = SettingsManager(ControlConfig(system_prompt="Base"))
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages", backend=backend
    )
    session = AgentSession(
        agent=Agent(initial_state={"system_prompt": "Base"}),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        resource_loader=DefaultResourceLoader(),
        package_materializer=materializer,
        base_prompt="Base",
    )

    asyncio.run(session.install_package(source))

    assert "Package review prompt" in session.agent.system_prompt
    assert [
        command.name
        for command in session.list_commands()
        if command.source != "builtin"
    ] == ["review", "skill:review"]


def test_agent_session_emits_package_progress_events(tmp_path) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True, exist_ok=True)
        return record.with_lifecycle("installed")

    settings = SettingsManager(ControlConfig())
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages", backend=backend
    )
    session = AgentSession(
        agent=Agent(initial_state={"system_prompt": "Base"}),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        package_materializer=materializer,
    )
    events: list[dict[str, object]] = []
    session.subscribe(
        lambda event: (
            events.append(event) if event["type"] == "package_progress" else None
        )
    )

    asyncio.run(session.install_package(source))

    assert [
        (event["progress_type"], event["action"], event["source"]) for event in events
    ] == [
        ("start", "install", source),
        ("complete", "install", source),
    ]


def test_agent_session_updates_all_packages_and_checks_updates(tmp_path) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"
    calls: list[str] = []

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        calls.append(record.source)
        record.target_path.mkdir(parents=True, exist_ok=True)
        return record.with_lifecycle("installed", target_path=record.target_path)

    materializer = PackageMaterializer(
        install_root=tmp_path / "packages", backend=backend
    )
    materializer.prepare_remote_source(source)
    settings = SettingsManager(ControlConfig(plugin_sources=(source,)))
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        package_materializer=materializer,
    )

    records = asyncio.run(session.update_packages())
    updates = asyncio.run(session.check_package_updates())

    assert [record["source"] for record in records] == [source]
    assert calls == [source]
    assert updates == []


def test_agent_session_updates_and_checks_configured_package_sources(
    tmp_path, monkeypatch
) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.source import PackageSourceConfig

    source = "https://packages.example.invalid/review-pack.git"
    calls: list[str] = []

    async def _failed_remote_check(
        source: str, timeout_seconds: float | None = None
    ) -> tuple[str | None, str]:
        del source, timeout_seconds
        return None, "remote check unavailable"

    monkeypatch.setattr(
        "loushang.harness.resources.packages.materializer._remote_git_head_result_async",
        _failed_remote_check,
    )

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        calls.append(record.source)
        record.target_path.mkdir(parents=True, exist_ok=True)
        return record.with_lifecycle(
            "installed", target_path=record.target_path
        ).with_git_state(
            installed_commit="abc123",
            resolved_commit="abc123",
        )

    settings = SettingsManager(
        ControlConfig(package_sources=(PackageSourceConfig(source=source),))
    )
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages", backend=backend
    )
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=settings,
        package_materializer=materializer,
    )

    records = asyncio.run(session.update_packages())
    updates = asyncio.run(session.check_package_updates())

    assert [record["source"] for record in records] == [source]
    assert calls == [source]
    assert updates[0]["status"] == "check_failed"


def test_agent_session_update_packages_dedupes_configured_sources_by_identity(
    tmp_path,
) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.security import PackageSecurityPolicy

    global_settings = tmp_path / "global" / "settings.json"
    project_settings = tmp_path / "project" / ".loushang" / "settings.json"
    global_settings.parent.mkdir()
    project_settings.parent.mkdir(parents=True)
    global_settings.write_text(
        json.dumps({"packages": ["https://github.com/acme/review-pack.git"]}),
        encoding="utf-8",
    )
    project_settings.write_text(
        json.dumps({"packages": ["git+https://github.com/acme/review-pack"]}),
        encoding="utf-8",
    )
    calls: list[str] = []

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        calls.append(record.source)
        record.target_path.mkdir(parents=True, exist_ok=True)
        return record.with_lifecycle("installed", target_path=record.target_path)

    settings = SettingsManager(
        global_settings_path=global_settings, project_settings_path=project_settings
    )
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
        security_policy=PackageSecurityPolicy(trusted_hosts=("github.com",)),
    )
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path, cwd=str(tmp_path / "project"), persist=False
            )
        ),
        settings_manager=settings,
        package_materializer=materializer,
    )

    records = asyncio.run(session.update_packages())

    assert [record["source"] for record in records] == [
        "git+https://github.com/acme/review-pack"
    ]
    assert calls == ["git+https://github.com/acme/review-pack"]


def test_agent_session_package_projection_dedupes_pinned_versions_by_package_identity(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    global_settings = tmp_path / "global" / "settings.json"
    project_settings = tmp_path / "project" / ".loushang" / "settings.json"
    global_settings.parent.mkdir()
    project_settings.parent.mkdir(parents=True)
    global_settings.write_text(
        json.dumps({"packages": ["pypi:acme-review-pack==1.2.3"]}), encoding="utf-8"
    )
    project_settings.write_text(
        json.dumps({"packages": ["pypi:acme-review-pack==1.3.0"]}), encoding="utf-8"
    )

    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path, cwd=str(tmp_path / "project"), persist=False
            )
        ),
        settings_manager=SettingsManager(
            global_settings_path=global_settings, project_settings_path=project_settings
        ),
        package_materializer=PackageMaterializer(install_root=tmp_path / "packages"),
    )

    packages = session.get_packages()

    assert [package["source"] for package in packages] == [
        "pypi:acme-review-pack==1.3.0"
    ]
    assert "versionConflict" not in packages[0]


def test_agent_session_configures_package_roots_from_all_settings_scopes(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    global_settings = tmp_path / "agent" / "settings.json"
    project_settings = tmp_path / "project" / ".loushang" / "settings.json"
    global_pack = tmp_path / "agent" / "packages" / "global-pack"
    project_pack = tmp_path / "project" / ".loushang" / "packages" / "project-pack"
    global_settings.parent.mkdir()
    project_settings.parent.mkdir(parents=True)
    global_pack.mkdir(parents=True)
    project_pack.mkdir(parents=True)
    global_settings.write_text(
        json.dumps({"packages": ["packages/global-pack"]}), encoding="utf-8"
    )
    project_settings.write_text(
        json.dumps({"packages": ["packages/project-pack"]}), encoding="utf-8"
    )

    settings = SettingsManager(
        global_settings_path=global_settings, project_settings_path=project_settings
    )
    loader = DefaultResourceLoader()
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path, cwd=str(tmp_path / "project"), persist=False
            )
        ),
        settings_manager=settings,
        resource_loader=loader,
        package_materializer=PackageMaterializer(install_root=tmp_path / "packages"),
    )

    session._configure_package_resource_roots()

    assert tuple(str(root) for root in loader._package_roots) == (
        str(project_pack.resolve()),
        str(global_pack.resolve()),
    )


def test_agent_session_configures_same_relative_package_roots_from_distinct_scopes(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    global_settings = tmp_path / "agent" / "settings.json"
    project_settings = tmp_path / "project" / ".loushang" / "settings.json"
    global_pack = tmp_path / "agent" / "packages" / "shared-pack"
    project_pack = tmp_path / "project" / ".loushang" / "packages" / "shared-pack"
    global_settings.parent.mkdir()
    project_settings.parent.mkdir(parents=True)
    global_pack.mkdir(parents=True)
    project_pack.mkdir(parents=True)
    global_settings.write_text(
        json.dumps({"packages": ["packages/shared-pack"]}), encoding="utf-8"
    )
    project_settings.write_text(
        json.dumps({"packages": ["packages/shared-pack"]}), encoding="utf-8"
    )

    settings = SettingsManager(
        global_settings_path=global_settings, project_settings_path=project_settings
    )
    loader = DefaultResourceLoader()
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path, cwd=str(tmp_path / "project"), persist=False
            )
        ),
        settings_manager=settings,
        resource_loader=loader,
        package_materializer=PackageMaterializer(install_root=tmp_path / "packages"),
    )

    session._configure_package_resource_roots()

    assert tuple(str(root) for root in loader._package_roots) == (
        str(project_pack.resolve()),
        str(global_pack.resolve()),
    )


def test_agent_session_records_package_update_check_failures(
    tmp_path, monkeypatch
) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.source import PackageSourceConfig

    source = (tmp_path / "missing.git").as_uri()

    async def _failed_remote_check(
        source: str, timeout_seconds: float | None = None
    ) -> tuple[str | None, str]:
        del source, timeout_seconds
        return None, "Failed to check remote package update: unavailable"

    monkeypatch.setattr(
        "loushang.harness.resources.packages.materializer._remote_git_head_result_async",
        _failed_remote_check,
    )

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True, exist_ok=True)
        return record.with_lifecycle(
            "installed", target_path=record.target_path
        ).with_git_state(
            installed_commit="abc123",
            resolved_commit="abc123",
        )

    diagnostics = DiagnosticsService()
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages", backend=backend
    )
    asyncio.run(materializer.materialize_remote_source(source))
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=SettingsManager(
            ControlConfig(package_sources=(PackageSourceConfig(source=source),))
        ),
        package_materializer=materializer,
        diagnostics_service=diagnostics,
    )

    updates = asyncio.run(session.check_package_updates())

    assert updates[0]["status"] == "check_failed"
    records = diagnostics.get_diagnostics(code="package_update_check_failed")
    assert len(records) == 1
    assert records[0].phase == "runtime"
    assert records[0].source == "package"
    assert records[0].details["package_source"] == source


def test_agent_session_records_package_version_conflict_diagnostics(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService

    first = tmp_path / "plugins" / "debug-pack-a"
    second = tmp_path / "plugins" / "debug-pack-b"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "plugin.json").write_text(
        json.dumps({"name": "debug-pack", "version": "1.0.0"}), encoding="utf-8"
    )
    (second / "plugin.json").write_text(
        json.dumps({"name": "debug-pack", "version": "2.0.0"}), encoding="utf-8"
    )
    diagnostics = DiagnosticsService()
    session = AgentSession(
        agent=Agent(),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
        ),
        settings_manager=SettingsManager(
            ControlConfig(plugin_sources=(str(first), str(second)))
        ),
        diagnostics_service=diagnostics,
    )

    packages = session.get_packages()

    assert [package["versionConflict"] for package in packages] == [True, True]
    records = diagnostics.get_diagnostics(code="package_version_conflict")
    assert len(records) == 2
    assert records[0].phase == "resource_loading"
    assert records[0].source == "package"
    assert records[0].details["package_name"] == "debug-pack"
    assert records[0].details["conflict_versions"] == ["1.0.0", "2.0.0"]


def test_agent_session_exposes_jsonl_and_html_export_methods(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd=str(project_dir), persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="hi")],
                timestamp=0.0,
            )
        )
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
    )

    jsonl_output = session.export_to_jsonl()
    html_output = session.export_to_html()

    assert jsonl_output.endswith(".jsonl")
    assert html_output.endswith(".html")
    assert Path(jsonl_output).exists()
    assert Path(html_output).exists()


def test_agent_session_exposes_diagnostics_views(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService

    diagnostics_service = DiagnosticsService()
    diagnostics_service.record(
        diagnostics_service.normalize_exception(
            code="session_warning",
            exc="watch this",
            phase="runtime",
            source="session",
            level="warning",
        )
    )
    diagnostics_service.record(
        diagnostics_service.normalize_exception(
            code="session_error",
            exc="broken",
            phase="runtime",
            source="session",
            level="error",
        )
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        diagnostics_service=diagnostics_service,
    )

    assert [record.code for record in session.get_last_diagnostics()] == [
        "session_warning",
        "session_error",
    ]
    assert session.get_last_error_report() is not None
    assert session.get_last_error_report().primary.code == "session_error"


def test_agent_session_serializes_async_queue_updates_for_steer(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    event_types: list[str] = []

    async def stream_fn(model, context, options=None):
        return _stream_with_final_message(_assistant_text_message("done"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        session = AgentSession(agent=agent, session_manager=manager)
        agent.state.messages.append(_assistant_text_message("existing"))

        async def listener(event) -> None:
            if event["type"] == "queue_update" and event["steering"]:
                await asyncio.sleep(0.01)
            event_types.append(event["type"])

        session.subscribe(listener)
        session.steer("next step")
        await session.continue_run()
        await asyncio.sleep(0.05)

        assert event_types[0] == "queue_update"
        assert event_types.count("queue_update") == 2
        assert event_types.index("agent_start") > 0
        queue_update_indexes = [
            index
            for index, event_type in enumerate(event_types)
            if event_type == "queue_update"
        ]
        assert queue_update_indexes[1] < event_types.index("message_start")

    asyncio.run(scenario())


def test_agent_session_serializes_async_queue_updates_for_follow_up(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    event_types: list[str] = []

    async def stream_fn(model, context, options=None):
        return _stream_with_final_message(_assistant_text_message("done"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=False
        )
        session = AgentSession(agent=agent, session_manager=manager)
        agent.state.messages.append(_assistant_text_message("existing"))

        async def listener(event) -> None:
            if event["type"] == "queue_update" and event["follow_up"]:
                await asyncio.sleep(0.01)
            event_types.append(event["type"])

        session.subscribe(listener)
        session.follow_up("later")
        await session.continue_run()
        await asyncio.sleep(0.05)

        assert event_types[0] == "queue_update"
        assert event_types.count("queue_update") == 2
        assert event_types.index("agent_start") > 0
        queue_update_indexes = [
            index
            for index, event_type in enumerate(event_types)
            if event_type == "queue_update"
        ]
        assert queue_update_indexes[1] < event_types.index("message_start")

    asyncio.run(scenario())
