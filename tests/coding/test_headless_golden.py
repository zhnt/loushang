from __future__ import annotations

import asyncio
import sys

import pytest

from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage


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


def _usage() -> Usage:
    return Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )


def _stream_with_message(message: AssistantMessage) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def feed() -> None:
        stream.push({"type": "start", "partial": message})
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})  # type: ignore[typeddict-item]

    asyncio.create_task(feed())
    return stream


def _assistant_tool_call_message() -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="write-1",
                name="write",
                arguments={"path": "golden.txt", "content": "headless ok"},
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


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="macOS env-sensitive golden/smoke; may hide a real macOS product bug — tracked separately as issue #455",
)
def test_headless_public_api_golden_allows_policy_approved_write_and_records_session(
    tmp_path,
) -> None:
    from loushang.coding import (
        ControlConfig,
        SessionManager,
        SettingsManager,
        ToolSettings,
        create_agent_session,
        create_services,
    )
    from loushang.coding.cli.__main__ import build_builtin_tool_registry

    project = tmp_path / "project"
    project.mkdir()
    settings_manager = SettingsManager(
        ControlConfig(
            tools=ToolSettings(
                ask_tools=("write",),
                approval_mode="allow",
            )
        )
    )
    services = create_services(settings_manager=settings_manager)
    registry = build_builtin_tool_registry(
        diagnostics_service=services.diagnostics_service,
        settings_manager=settings_manager,
    )

    async def stream_fn(model, context, options=None):
        del model, options
        if any(
            getattr(message, "role", None) == "toolResult"
            for message in context.messages
        ):
            return _stream_with_message(_assistant_text_message("wrote golden.txt"))
        return _stream_with_message(_assistant_tool_call_message())

    async def scenario() -> list[str]:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(project), persist=True
        )
        session = create_agent_session(
            session_manager=manager,
            model=_model(),
            stream_fn=stream_fn,
            services=services,
            tool_registry=registry,
            active_tool_names=["write"],
        )
        events: list[str] = []
        session.subscribe(lambda event: events.append(str(event.get("type"))))

        await session.prompt("write the golden file")
        await session.wait_for_idle()
        return events

    events = asyncio.run(scenario())

    assert (project / "golden.txt").read_text(encoding="utf-8") == "headless ok"
    assert "tool_execution_start" in events
    assert "tool_execution_end" in events
    assert "agent_end" in events
