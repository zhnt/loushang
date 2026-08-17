from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.agent import (
    Agent,
    AgentToolResult,
    FunctionalToolOutputProjector,
)
from loushang.agent.types import AfterToolCallContext, AfterToolCallResult, AgentContext
from loushang.ai.types import TextPart, UserMessage
from loushang.harness.extensions.agent import (
    ContextResult,
    ExtensionAgentHookRuntime,
    ExtensionRunner,
    LoadedExtension,
)
from loushang.harness.extensions.agent.hooks import compose_after_tool_call_hooks


def _user_message(text: str) -> UserMessage:
    return UserMessage(
        role="user", content=[TextPart(type="text", text=text)], timestamp=0.0
    )


def test_extension_hooks_compose_existing_transform_with_extension_context(
    tmp_path,
) -> None:
    seen: list[str] = []

    async def _existing_transform(messages, signal):
        del signal
        return messages + [_user_message("from-existing")]

    def _extension_context(event, ctx):
        seen.append(f"{event.messages[-1].content[0].text}:{ctx.cwd}")
        return ContextResult(
            messages=event.messages + [_user_message("from-extension")]
        )

    agent = Agent(transform_context=_existing_transform)
    ExtensionAgentHookRuntime(
        agent=agent,
        extension_runtime=ExtensionRunner(
            [
                LoadedExtension(
                    name="context",
                    source_path=tmp_path / "context.py",
                    hooks={"context": [_extension_context]},
                )
            ]
        ),
        get_cwd=lambda: "/tmp/project",
    ).install()

    transformed = asyncio.run(agent.transform_context([_user_message("base")], None))

    assert [message.content[0].text for message in transformed] == [
        "base",
        "from-existing",
        "from-extension",
    ]
    assert seen == ["from-existing:/tmp/project"]


def test_after_hook_composition_refreshes_hook_view_for_projector_only_override() -> (
    None
):
    first_projector = FunctionalToolOutputProjector(
        transcript=lambda details: {"view": "transcript-0"},
        hook=lambda details: {"view": "hook-0"},
    )
    second_projector = FunctionalToolOutputProjector(
        transcript=lambda details: {"view": "transcript-1"},
        hook=lambda details: {"view": "hook-1"},
    )
    raw_details = object()
    initial_result = AgentToolResult(
        content=[TextPart(type="text", text="original")],
        details=raw_details,
        projector=first_projector,
    )
    seen: list[tuple[object, object]] = []

    async def replace_projector(context, signal):
        del signal
        seen.append((context.result.details, context.hook_details))
        return AfterToolCallResult(projector=second_projector)

    async def observe_replacement(context, signal):
        del signal
        seen.append((context.result.details, context.hook_details))
        return None

    context = AfterToolCallContext(
        assistant_message=SimpleNamespace(),
        tool_call=SimpleNamespace(),
        args={},
        result=initial_result,
        is_error=False,
        context=AgentContext(system_prompt="", messages=[], tools=[]),
        hook_details=initial_result.hook_details(),
    )

    result = asyncio.run(
        compose_after_tool_call_hooks(
            context,
            None,
            [replace_projector, observe_replacement],
        )
    )

    assert result is not None
    assert result.projector is second_projector
    assert seen == [
        (raw_details, {"view": "hook-0"}),
        (raw_details, {"view": "hook-1"}),
    ]


def test_after_hook_composition_can_clear_details_to_json_null() -> None:
    initial_result = AgentToolResult(
        content=[TextPart(type="text", text="original")],
        details={"value": 1},
    )
    seen: list[tuple[object, object]] = []

    async def clear_details(context, signal):
        del signal
        seen.append((context.result.details, context.hook_details))
        return AfterToolCallResult(details=None)

    async def observe_null(context, signal):
        del signal
        seen.append((context.result.details, context.hook_details))
        return None

    context = AfterToolCallContext(
        assistant_message=SimpleNamespace(),
        tool_call=SimpleNamespace(),
        args={},
        result=initial_result,
        is_error=False,
        context=AgentContext(system_prompt="", messages=[], tools=[]),
        hook_details=initial_result.hook_details(),
    )

    result = asyncio.run(
        compose_after_tool_call_hooks(
            context,
            None,
            [clear_details, observe_null],
        )
    )

    assert result is not None
    assert result.details_provided is True
    assert result.details is None
    assert seen == [
        ({"value": 1}, {"value": 1}),
        (None, None),
    ]


def test_after_hook_composition_propagates_projection_failure_from_middle_of_chain() -> (
    None
):
    from loushang.agent import ToolOutputProjectionError

    projector = FunctionalToolOutputProjector(
        transcript=lambda details: {"view": "transcript"},
        hook=lambda details: {"path": Path("notes.txt")},
    )
    initial_result = AgentToolResult(
        content=[TextPart(type="text", text="original")],
        details={"value": 1},
    )
    called: list[str] = []

    async def invalid_override(context, signal):
        del context, signal
        called.append("invalid")
        return AfterToolCallResult(projector=projector)

    async def later_hook(context, signal):
        del context, signal
        called.append("later")
        return None

    context = AfterToolCallContext(
        assistant_message=SimpleNamespace(),
        tool_call=SimpleNamespace(),
        args={},
        result=initial_result,
        is_error=False,
        context=AgentContext(system_prompt="", messages=[], tools=[]),
        hook_details=initial_result.hook_details(),
    )

    with pytest.raises(ToolOutputProjectionError) as exc_info:
        asyncio.run(
            compose_after_tool_call_hooks(
                context,
                None,
                [invalid_override, later_hook],
            )
        )

    assert exc_info.value.target == "hook"
    assert exc_info.value.path == "tool_output.details.path"
    assert called == ["invalid"]
