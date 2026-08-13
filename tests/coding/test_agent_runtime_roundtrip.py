from __future__ import annotations

import asyncio

from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


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


def test_agent_messages_roundtrip_through_persisted_session_manager(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session_manager import SessionManager

    async def stream_fn(model, context, options=None):
        return _stream_with_final_message(_assistant_text_message("hello"))

    async def scenario() -> None:
        agent = Agent(
            stream_fn=stream_fn,
            initial_state={"system_prompt": "You are helpful.", "model": _model()},
        )
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd="/tmp/project", persist=True
        )

        await agent.prompt("hi")
        for message in agent.state.messages:
            await manager.append_message(message)

        assert manager.session_file is not None
        reloaded = await SessionManager.load(manager.session_file)
        context = reloaded.build_session_context()

        assert [getattr(message, "role", None) for message in context.messages] == [
            "user",
            "assistant",
        ]
        assert context.model == {
            "provider": "faux",
            "endpoint_id": "test-endpoint",
            "model_id": "faux-model",
        }

    asyncio.run(scenario())
