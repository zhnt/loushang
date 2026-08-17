from __future__ import annotations

import asyncio

import pytest

from loushang.agent import Agent
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.runtime import (
    SideQuestionAnswer,
    SideQuestionCoordinator,
)


def _assistant_message(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=Usage(
            input=3,
            output=2,
            cache_read=1,
            cache_write=0,
            total_tokens=5,
            cost={},
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _completed_stream(message: AssistantMessage) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()
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
    stream.push({"type": "done", "reason": "stop", "message": message})
    return stream


def test_agent_side_question_uses_committed_context_without_persisting(
    tmp_path,
) -> None:
    async def scenario() -> None:
        from loushang.harness.tools.core import ToolDefinition
        from loushang.harness.tools.execution import direct_execution
        from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

        async def never_run(*args, **kwargs):
            del args, kwargs
            raise AssertionError("side-question tools must be blocked")

        registry = WorkspaceToolRegistry()
        registry.register_tool(
            ToolDefinition(
                name="dangerous",
                label="Dangerous",
                description="Must stay advertised for cache compatibility.",
                parameters={"type": "object", "properties": {}},
                execution=direct_execution(never_run),
            )
        )
        captured_contexts: list[object] = []

        async def stream_fn(model, context, options=None):
            del model, options
            captured_contexts.append(context)
            return _completed_stream(_assistant_message("A transient answer."))

        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=False,
        )
        await manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="Committed context")],
                timestamp=0.0,
            )
        )
        parent = Agent(
            initial_state={
                "system_prompt": "Stable parent prompt",
                "tools": [],
            },
            stream_fn=stream_fn,
        )
        session = AgentSession(
            agent=parent,
            session_manager=manager,
            tool_registry=registry,
            active_tool_names=["dangerous"],
        )
        entries_before = list(manager.get_entries())
        parent_messages_before = list(parent.state.messages)
        updates: list[str] = []

        answer = await session.ask_side_question(
            "What matters here?",
            on_update=updates.append,
        )

        assert answer.text == "A transient answer."
        assert updates[-1] == "A transient answer."
        assert answer.context_revision == manager.get_leaf_id()
        assert manager.get_entries() == entries_before
        assert parent.state.messages == parent_messages_before
        assert len(captured_contexts) == 1
        context = captured_contexts[0]
        assert [tool.name for tool in getattr(context, "tools")] == ["dangerous"]
        assert [
            getattr(message, "role", None) for message in getattr(context, "messages")
        ] == ["user", "user"]
        assert getattr(context, "system_prompt") == "Stable parent prompt"
        side_prompt = getattr(context, "messages")[-1].content[0].text
        assert "one-shot side question" in side_prompt
        assert side_prompt.endswith("Question:\nWhat matters here?")
        await session.dispose()

    asyncio.run(scenario())


def test_side_question_coordinator_cancels_only_its_active_request() -> None:
    class _Provider:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = False

        async def ask(
            self,
            question: str,
            *,
            on_update=None,
        ) -> SideQuestionAnswer:
            assert question == "question"
            assert on_update is None
            self.started.set()
            await asyncio.Future()
            raise AssertionError("unreachable")

        def cancel(self) -> None:
            self.cancelled = True

    async def scenario() -> None:
        provider = _Provider()
        coordinator = SideQuestionCoordinator(provider)
        task = asyncio.create_task(coordinator.ask("question"))
        await provider.started.wait()

        assert coordinator.active is True
        assert coordinator.cancel() is True
        with pytest.raises(asyncio.CancelledError):
            await task
        assert provider.cancelled is True
        assert coordinator.active is False

    asyncio.run(scenario())


def test_side_question_cancel_error_still_joins_the_owned_request() -> None:
    class _Provider:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def ask(self, question: str, *, on_update=None) -> SideQuestionAnswer:
            del question, on_update
            self.started.set()
            await asyncio.Future()
            raise AssertionError("unreachable")

        def cancel(self) -> None:
            raise RuntimeError("provider cancel failed")

    async def scenario() -> None:
        provider = _Provider()
        coordinator = SideQuestionCoordinator(provider)
        task = asyncio.create_task(coordinator.ask("question"))
        await provider.started.wait()

        with pytest.raises(RuntimeError, match="provider cancel failed"):
            await coordinator.cancel_and_wait()
        assert task.done()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert coordinator.active is False

    asyncio.run(scenario())
