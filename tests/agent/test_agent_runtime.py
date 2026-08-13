import asyncio
from contextlib import suppress
from typing import Any

import pytest

from loushang.agent.types import AgentToolResult
from loushang.ai.auth import ApiKeyAuth, OAuthBearerAuth
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.options import CallOptions, ReasoningOptions, RetryOptions
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    TextPart,
    ToolCall,
    Usage,
    UserMessage,
)


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        api="anthropic-messages",
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


def _assistant_text_message(
    text: str, *, stop_reason: str = "stop", error_message: str | None = None
) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(),
        stop_reason=stop_reason,
        error_message=error_message,
        timestamp=0.0,
    )


def _assistant_tool_call_message() -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[ToolCall(type="toolCall", id="tc_1", name="calc", arguments={"x": 1})],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )


def _stream_with_final_message(
    message: AssistantMessage, *, delay: float = 0.0
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def _feed() -> None:
        stream.push({"type": "start", "partial": message})
        if message.content and isinstance(message.content[0], TextPart):
            stream.push({"type": "text_start", "content_index": 0, "partial": message})
            if delay:
                await asyncio.sleep(delay)
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
        elif message.content and isinstance(message.content[0], ToolCall):
            stream.push(
                {"type": "toolcall_start", "content_index": 0, "partial": message}
            )
            if delay:
                await asyncio.sleep(delay)
            stream.push(
                {
                    "type": "toolcall_delta",
                    "content_index": 0,
                    "delta": '{"x": 1}',
                    "partial": message,
                }
            )
            stream.push(
                {
                    "type": "toolcall_end",
                    "content_index": 0,
                    "tool_call": message.content[0],
                    "partial": message,
                }
            )
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})  # type: ignore[typeddict-item]

    asyncio.create_task(_feed())
    return stream


def _user_text_content(message: UserMessage) -> str:
    return message.content[0].text


class FakeTool:
    name = "calc"
    description = "calculate"
    parameters = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
        "additionalProperties": False,
    }
    label = "Calc"
    prepare_arguments = None

    async def execute(
        self, tool_call_id: str, params: dict[str, Any], signal=None, on_update=None
    ) -> AgentToolResult[dict[str, Any]]:
        if on_update is not None:
            on_update(
                AgentToolResult(
                    content=[TextPart(type="text", text="partial")],
                    details={"progress": "half"},
                )
            )
        return AgentToolResult(
            content=[TextPart(type="text", text=str(params["x"] + 1))],
            details={"value": params["x"] + 1},
        )


def test_prompt_updates_state_and_notifies_subscribers() -> None:
    from loushang.agent import Agent

    events: list[str] = []

    async def stream_fn(model, context, options=None):
        return _stream_with_final_message(_assistant_text_message("hello"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)

        async def listener(event, signal) -> None:
            events.append(event["type"])

        agent.subscribe(listener)
        await agent.prompt("hi")

        assert [getattr(message, "role", None) for message in agent.state.messages] == [
            "user",
            "assistant",
        ]
        assert agent.state.messages[-1].content[0].text == "hello"
        assert agent.state.is_streaming is False
        assert agent.state.streaming_message is None
        assert events[0] == "agent_start"
        assert events[-1] == "agent_end"

    asyncio.run(scenario())


def test_subscribe_deduplicates_same_listener() -> None:
    from loushang.agent import Agent

    calls = 0

    async def stream_fn(model, context, options=None):
        return _stream_with_final_message(_assistant_text_message("hello"))

    async def scenario() -> None:
        nonlocal calls
        agent = Agent(stream_fn=stream_fn)

        def listener(event, signal) -> None:
            nonlocal calls
            if event["type"] == "agent_start":
                calls += 1

        agent.subscribe(listener)
        agent.subscribe(listener)
        await agent.prompt("hi")

        assert calls == 1

    asyncio.run(scenario())


def test_subscribe_preserves_first_registration_order() -> None:
    from loushang.agent import Agent

    observed: list[str] = []

    async def stream_fn(model, context, options=None):
        return _stream_with_final_message(_assistant_text_message("hello"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)

        def first(event, signal) -> None:
            if event["type"] == "agent_start":
                observed.append("first")

        def second(event, signal) -> None:
            if event["type"] == "agent_start":
                observed.append("second")

        agent.subscribe(first)
        agent.subscribe(second)
        agent.subscribe(first)
        await agent.prompt("hi")

        assert observed == ["first", "second"]

    asyncio.run(scenario())


def test_continue_prefers_queued_steering_then_follow_up_when_last_message_is_assistant() -> (
    None
):
    from loushang.agent import Agent

    calls: list[str] = []

    async def stream_fn(model, context, options=None):
        last = context.messages[-1]
        if isinstance(last, UserMessage):
            calls.append(_user_text_content(last))
        return _stream_with_final_message(_assistant_text_message("ok"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        agent.state.messages.append(_assistant_text_message("done"))

        agent.steer(UserMessage(role="user", content="steer-now", timestamp=0.0))
        await agent.continue_run()

        agent.state.messages.append(_assistant_text_message("done-again"))
        agent.follow_up(
            UserMessage(role="user", content="follow-up-now", timestamp=0.0)
        )
        await agent.continue_run()

        assert calls == ["steer-now", "follow-up-now"]

    asyncio.run(scenario())


def test_continue_consumes_system_mailbox_from_an_idle_assistant_boundary() -> None:
    from loushang.agent import Agent

    calls: list[str] = []

    async def stream_fn(model, context, options=None):
        del model, options
        last = context.messages[-1]
        if isinstance(last, UserMessage):
            calls.append(_user_text_content(last))
        return _stream_with_final_message(_assistant_text_message("ok"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        agent.state.messages.append(_assistant_text_message("done"))
        agent.enqueue_mailbox(
            UserMessage(role="user", content="system result", timestamp=0.0)
        )

        await agent.continue_run()

        assert calls == ["system result"]
        assert agent.mailbox_queue.has_items() is False

    asyncio.run(scenario())


def test_wait_for_idle_waits_for_agent_end_listener_settlement() -> None:
    from loushang.agent import Agent

    listener_finished = False

    async def stream_fn(model, context, options=None):
        return _stream_with_final_message(_assistant_text_message("slow"), delay=0.01)

    async def scenario() -> None:
        nonlocal listener_finished
        agent = Agent(stream_fn=stream_fn)

        async def listener(event, signal) -> None:
            nonlocal listener_finished
            if event["type"] == "agent_end":
                await asyncio.sleep(0.02)
                listener_finished = True

        agent.subscribe(listener)
        run_task = asyncio.create_task(agent.prompt("hi"))
        await asyncio.sleep(0)
        await agent.wait_for_idle()
        await run_task
        assert listener_finished is True

    asyncio.run(scenario())


def test_state_folding_tracks_tool_execution_and_error_message() -> None:
    from loushang.agent import Agent

    pending_snapshots: list[set[str]] = []

    async def stream_fn(model, context, options=None):
        if any(
            getattr(message, "role", None) == "toolResult"
            for message in context.messages
        ):
            return _stream_with_final_message(
                _assistant_text_message("", stop_reason="error", error_message="boom")
            )
        return _stream_with_final_message(_assistant_tool_call_message())

    async def scenario() -> None:
        initial_state = agent_state_seed()
        initial_state.set_tools([FakeTool()])
        agent = Agent(stream_fn=stream_fn, initial_state=initial_state)

        async def listener(event, signal) -> None:
            if event["type"] in {"tool_execution_start", "tool_execution_end"}:
                pending_snapshots.append(set(agent.state.pending_tool_calls))

        agent.subscribe(listener)
        await agent.prompt("use tool")

        assert pending_snapshots[0] == {"tc_1"}
        assert pending_snapshots[-1] == set()
        assert agent.state.pending_tool_calls == set()
        assert agent.state.error_message == "boom"

    asyncio.run(scenario())


def agent_state_seed():
    from loushang.agent.types import AgentState

    return AgentState(system_prompt="", model=_model(), thinking_level="off")


def test_signal_property_exposes_active_abort_signal() -> None:
    from loushang.agent import Agent

    captured_signals: list[object | None] = []

    async def stream_fn(model, context, options=None):
        await asyncio.sleep(0.01)
        return _stream_with_final_message(_assistant_text_message("done"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        task = asyncio.create_task(agent.prompt("hi"))
        await asyncio.sleep(0)
        captured_signals.append(agent.signal)
        await task
        captured_signals.append(agent.signal)

        assert captured_signals[0] is not None
        assert getattr(captured_signals[0], "aborted", None) is False
        assert captured_signals[1] is None

    asyncio.run(scenario())


def test_reset_clears_runtime_state_and_all_queues() -> None:
    from loushang.agent import Agent

    async def scenario() -> None:
        agent = Agent()
        agent.state.messages.append(_assistant_text_message("stale"))
        agent.state.is_streaming = True
        agent.state.streaming_message = _assistant_text_message("partial")
        agent.state.pending_tool_calls.add("tc_1")
        agent.state.error_message = "boom"
        agent.steer(UserMessage(role="user", content="steer", timestamp=0.0))
        agent.follow_up(UserMessage(role="user", content="follow", timestamp=0.0))

        agent.reset()

        assert agent.state.messages == []
        assert agent.state.is_streaming is False
        assert agent.state.streaming_message is None
        assert agent.state.pending_tool_calls == set()
        assert agent.state.error_message is None
        assert agent.has_queued_messages() is False

    asyncio.run(scenario())


def test_clear_all_queues_removes_steering_and_follow_up_messages() -> None:
    from loushang.agent import Agent

    agent = Agent()
    agent.enqueue_mailbox(UserMessage(role="user", content="system", timestamp=0.0))
    agent.steer(UserMessage(role="user", content="steer", timestamp=0.0))
    agent.follow_up(UserMessage(role="user", content="follow", timestamp=0.0))

    agent.clear_all_queues()

    assert agent.has_queued_messages() is False


def test_process_event_requires_active_run_signal() -> None:
    from loushang.agent import Agent

    async def scenario() -> None:
        agent = Agent()
        with pytest.raises(RuntimeError, match="outside active run"):
            await agent._process_event({"type": "agent_start"})

    asyncio.run(scenario())


def test_request_auth_is_forwarded_to_stream_function_options() -> None:
    from loushang.agent import Agent

    captured_auth: list[object] = []

    async def stream_fn(model, context, options=None):
        captured_auth.append(getattr(options, "auth", None))
        return _stream_with_final_message(_assistant_text_message("hello"))

    async def scenario() -> None:
        agent = Agent(
            stream_fn=stream_fn,
            call_options=CallOptions(auth=ApiKeyAuth("secret-token")),
            initial_state=agent_state_seed(),
        )
        await agent.prompt("hi")

        assert captured_auth == [ApiKeyAuth("secret-token")]

    asyncio.run(scenario())


def test_agent_forwards_oauth_request_auth_without_provider_judgment() -> None:
    from loushang.agent import Agent
    from loushang.agent.types import AgentState

    captured_auth: list[object] = []

    async def stream_fn(model, context, options=None):
        captured_auth.append(getattr(options, "auth", None))
        return _stream_with_final_message(_assistant_text_message("hello"))

    async def scenario() -> None:
        oauth_model = Model(
            id="oauth-model",
            provider="faux",
            endpoint="anthropic-messages",
            api="anthropic-messages",
            auth=Auth(kind="oauth"),
            capabilities=Capabilities(input=("text",), output=("text",)),
        )
        agent = Agent(
            stream_fn=stream_fn,
            call_options=CallOptions(auth=OAuthBearerAuth("oauth-token")),
            initial_state=AgentState(
                system_prompt="",
                model=oauth_model,
                thinking_level="off",
            ),
        )
        await agent.prompt("hi")

        assert captured_auth == [OAuthBearerAuth("oauth-token")]

    asyncio.run(scenario())


def test_default_agent_stream_preserves_canonical_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loushang.agent.agent as agent_module
    from loushang.agent import Agent

    captured_options: list[object] = []

    async def stream_fn(model, context, options=None):
        del model, context
        captured_options.append(options)
        return _stream_with_final_message(_assistant_text_message("hello"))

    monkeypatch.setattr(agent_module, "stream", stream_fn)

    async def scenario() -> None:
        agent = Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "high",
            },
            session_id="session-1",
            thinking_budgets={"high": 2048},
            max_retry_delay_ms=1234,
        )
        await agent.prompt("hi")

    asyncio.run(scenario())

    assert len(captured_options) == 1
    options = captured_options[0]
    assert isinstance(options, CallOptions)
    assert options.cache_key == "session-1"
    assert options.reasoning == ReasoningOptions(
        enabled=True,
        effort="high",
        budget_tokens=2048,
    )
    assert options.retry == RetryOptions(
        max_attempts=1,
        max_delay_seconds=1.234,
    )
    assert not hasattr(options, "signal")
    assert not hasattr(options, "transport")
    assert not hasattr(options, "max_retry_delay_ms")
    assert not hasattr(options, "on_payload")
    assert not hasattr(options, "on_response")


def test_abort_marks_run_as_aborted_and_sets_error_message() -> None:
    from loushang.agent import Agent

    async def stream_fn(model, context, options=None):
        await asyncio.sleep(0.02)
        if (
            getattr(options, "cancellation", None) is not None
            and options.cancellation.aborted
        ):
            raise RuntimeError("stream aborted")
        return _stream_with_final_message(_assistant_text_message("late"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn, initial_state=agent_state_seed())
        task = asyncio.create_task(agent.prompt("hi"))
        await asyncio.sleep(0)
        agent.abort()
        await task

        assert agent.state.is_streaming is False
        assert agent.state.streaming_message is None
        assert agent.state.messages[-1].stop_reason == "aborted"
        assert agent.state.error_message == "Request aborted by user"

    asyncio.run(scenario())


def test_abort_then_task_cancel_adds_aborted_boundary() -> None:
    from loushang.agent import Agent

    started = asyncio.Event()

    async def stream_fn(model, context, options=None):
        del model, context, options
        started.set()
        await asyncio.Event().wait()
        return _stream_with_final_message(_assistant_text_message("late"))

    async def scenario() -> Agent:
        agent = Agent(stream_fn=stream_fn, initial_state=agent_state_seed())
        task = asyncio.create_task(agent.prompt("hi"))
        await started.wait()
        agent.abort()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return agent

    agent = asyncio.run(scenario())

    assert agent.state.is_streaming is False
    assert [
        getattr(message, "role", None) for message in agent.state.messages[-2:]
    ] == ["user", "assistant"]
    assert agent.state.messages[-1].stop_reason == "aborted"
    assert agent.state.error_message == "Request aborted by user"


def test_abort_cancels_non_cooperative_stream_prompt() -> None:
    from loushang.agent import Agent

    started = asyncio.Event()

    async def stream_fn(model, context, options=None):
        del model, context, options
        started.set()
        await asyncio.Event().wait()
        return _stream_with_final_message(_assistant_text_message("late"))

    async def scenario() -> Agent:
        agent = Agent(stream_fn=stream_fn, initial_state=agent_state_seed())
        task = asyncio.create_task(agent.prompt("hi"))
        await started.wait()
        agent.abort()
        done, pending = await asyncio.wait({task}, timeout=0.2)
        if pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        assert task in done
        return agent

    agent = asyncio.run(scenario())

    assert agent.state.is_streaming is False
    assert agent.state.streaming_message is None
    assert agent.state.messages[-1].stop_reason == "aborted"
    assert agent.state.error_message == "Request aborted by user"


def test_abort_during_stream_does_not_cancel_durable_terminalization() -> None:
    from loushang.agent import Agent

    started = asyncio.Event()
    finalizer_started = asyncio.Event()
    release_finalizer = asyncio.Event()
    emitted: list[dict[str, object]] = []

    async def stream_fn(model, context, options=None):
        del model, context, options
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn, initial_state=agent_state_seed())

        async def listener(event, signal) -> None:
            del signal
            emitted.append(event)
            message = event.get("message")
            if (
                event["type"] == "message_end"
                and isinstance(message, AssistantMessage)
                and message.stop_reason == "aborted"
            ):
                finalizer_started.set()
                await release_finalizer.wait()

        agent.subscribe(listener)
        task = asyncio.create_task(agent.prompt("hi"))
        await started.wait()
        agent.abort()
        await asyncio.wait_for(finalizer_started.wait(), timeout=0.2)

        agent.abort()
        await asyncio.sleep(0.06)
        assert task.done() is False

        release_finalizer.set()
        await task
        assert agent.state.is_streaming is False

    asyncio.run(scenario())

    aborted_ends = [
        event
        for event in emitted
        if event["type"] == "message_end"
        and isinstance(event.get("message"), AssistantMessage)
        and event["message"].stop_reason == "aborted"  # type: ignore[union-attr]
    ]
    assert len(aborted_ends) == 1
    assert sum(event["type"] == "agent_end" for event in emitted) == 1


def test_abort_during_sequential_tool_persists_one_result_and_boundary() -> None:
    from loushang.agent import Agent

    started = asyncio.Event()
    emitted: list[dict[str, object]] = []

    class BlockingTool(FakeTool):
        async def execute(
            self, tool_call_id, params, signal=None, on_update=None
        ) -> AgentToolResult[dict[str, Any]]:
            del tool_call_id, params, signal, on_update
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    calls = 0

    async def stream_fn(model, context, options=None):
        nonlocal calls
        del model, context, options
        calls += 1
        return _stream_with_final_message(_assistant_tool_call_message())

    async def scenario() -> Agent:
        state = agent_state_seed()
        state.set_tools([BlockingTool()])
        agent = Agent(
            stream_fn=stream_fn,
            initial_state=state,
            tool_execution="sequential",
        )
        agent.subscribe(lambda event, signal: emitted.append(event))
        task = asyncio.create_task(agent.prompt("use tool"))
        await started.wait()
        agent.abort()
        await asyncio.wait_for(task, timeout=0.2)
        return agent

    agent = asyncio.run(scenario())

    tool_ends = [event for event in emitted if event["type"] == "tool_execution_end"]
    assert len(tool_ends) == 1
    assert tool_ends[0]["tool_call_id"] == "tc_1"
    assert tool_ends[0]["is_error"] is True
    aborted_messages = [
        message
        for message in agent.state.messages
        if isinstance(message, AssistantMessage) and message.stop_reason == "aborted"
    ]
    assert len(aborted_messages) == 1
    assert (
        sum(
            event["type"] == "message_end"
            and isinstance(event.get("message"), AssistantMessage)
            and event["message"].stop_reason == "aborted"  # type: ignore[union-attr]
            for event in emitted
        )
        == 1
    )
    assert calls == 1


def test_abort_during_parallel_tools_preserves_only_precompleted_result() -> None:
    from loushang.agent import Agent
    from loushang.ai.types import ToolResultMessage

    slow_started = asyncio.Event()
    fast_completed = asyncio.Event()
    emitted: list[dict[str, object]] = []

    class PartialTool(FakeTool):
        async def execute(
            self, tool_call_id, params, signal=None, on_update=None
        ) -> AgentToolResult[dict[str, Any]]:
            del params, signal, on_update
            if tool_call_id == "tc_fast":
                fast_completed.set()
                return AgentToolResult(
                    content=[TextPart(type="text", text="fast")],
                    details={"value": "fast"},
                )
            slow_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    tool_message = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="tc_slow", name="calc", arguments={"x": 1}),
            ToolCall(type="toolCall", id="tc_fast", name="calc", arguments={"x": 2}),
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

    async def stream_fn(model, context, options=None):
        del model, context, options
        return _stream_with_final_message(tool_message)

    async def scenario() -> Agent:
        state = agent_state_seed()
        state.set_tools([PartialTool()])
        agent = Agent(stream_fn=stream_fn, initial_state=state)
        agent.subscribe(lambda event, signal: emitted.append(event))
        task = asyncio.create_task(agent.prompt("use tools"))
        await slow_started.wait()
        await fast_completed.wait()
        agent.abort()
        await asyncio.wait_for(task, timeout=0.2)
        return agent

    agent = asyncio.run(scenario())

    results = {
        message.tool_call_id: message
        for message in agent.state.messages
        if isinstance(message, ToolResultMessage)
    }
    assert set(results) == {"tc_slow", "tc_fast"}
    assert results["tc_slow"].details == {"code": "tool_call_aborted"}
    assert results["tc_fast"].details == {"value": "fast"}
    tool_end_ids = [
        event["tool_call_id"]
        for event in emitted
        if event["type"] == "tool_execution_end"
    ]
    assert sorted(tool_end_ids) == ["tc_fast", "tc_slow"]


def test_external_prompt_cancellation_waits_for_terminalization_then_propagates() -> (
    None
):
    from loushang.agent import Agent

    started = asyncio.Event()
    finalizer_started = asyncio.Event()
    release_finalizer = asyncio.Event()

    async def stream_fn(model, context, options=None):
        del model, context, options
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn, initial_state=agent_state_seed())

        async def listener(event, signal) -> None:
            del signal
            message = event.get("message")
            if (
                event["type"] == "message_end"
                and isinstance(message, AssistantMessage)
                and message.stop_reason == "aborted"
            ):
                finalizer_started.set()
                await release_finalizer.wait()

        agent.subscribe(listener)
        task = asyncio.create_task(agent.prompt("hi"))
        await started.wait()
        task.cancel()
        await asyncio.wait_for(finalizer_started.wait(), timeout=0.2)
        task.cancel()
        await asyncio.sleep(0)
        assert task.done() is False
        release_finalizer.set()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert agent.state.messages[-1].stop_reason == "aborted"
        assert agent.state.is_streaming is False

    asyncio.run(scenario())


def test_cancelling_wait_for_idle_does_not_cancel_the_active_run() -> None:
    from loushang.agent import Agent

    started = asyncio.Event()

    async def stream_fn(model, context, options=None):
        del model, context, options
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn, initial_state=agent_state_seed())
        prompt_task = asyncio.create_task(agent.prompt("hi"))
        await started.wait()
        waiter = asyncio.create_task(agent.wait_for_idle())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        assert prompt_task.done() is False
        assert agent.state.is_streaming is True
        agent.abort()
        await asyncio.wait_for(prompt_task, timeout=0.2)

    asyncio.run(scenario())


def test_prompt_with_images_builds_single_user_message_with_text_and_images() -> None:
    from loushang.agent import Agent

    seen_user_messages: list[UserMessage] = []
    image = ImagePart(type="image", data="base64-image", mime_type="image/png")

    async def stream_fn(model, context, options=None):
        user_message = context.messages[0]
        assert isinstance(user_message, UserMessage)
        seen_user_messages.append(user_message)
        return _stream_with_final_message(_assistant_text_message("described"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        await agent.prompt("describe this", images=[image])

        user_message = seen_user_messages[0]
        assert isinstance(user_message.content, list)
        assert len(user_message.content) == 2
        assert isinstance(user_message.content[0], TextPart)
        assert user_message.content[0].text == "describe this"
        assert user_message.content[1] == image

    asyncio.run(scenario())


def test_queue_mode_properties_are_readable_and_mutable() -> None:
    from loushang.agent import Agent

    agent = Agent()

    assert agent.steering_mode == "one-at-a-time"
    assert agent.follow_up_mode == "one-at-a-time"

    agent.steering_mode = "all"
    agent.follow_up_mode = "all"

    assert agent.steering_mode == "all"
    assert agent.follow_up_mode == "all"


def test_steering_mode_all_drains_all_messages_in_single_turn() -> None:
    from loushang.agent import Agent

    seen_user_messages: list[list[str]] = []

    async def stream_fn(model, context, options=None):
        seen_user_messages.append(
            [
                _user_text_content(message)
                for message in context.messages
                if isinstance(message, UserMessage)
            ]
        )
        return _stream_with_final_message(_assistant_text_message("done"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        agent.state.messages.append(_assistant_text_message("done"))
        agent.steering_mode = "all"
        agent.steer(UserMessage(role="user", content="s1", timestamp=0.0))
        agent.steer(UserMessage(role="user", content="s2", timestamp=0.0))

        await agent.continue_run()

        assert seen_user_messages == [["s1", "s2"]]

    asyncio.run(scenario())


def test_follow_up_mode_all_drains_all_messages_after_agent_would_stop() -> None:
    from loushang.agent import Agent

    seen_user_messages: list[list[str]] = []

    async def stream_fn(model, context, options=None):
        seen_user_messages.append(
            [
                _user_text_content(message)
                for message in context.messages
                if isinstance(message, UserMessage)
            ]
        )
        return _stream_with_final_message(_assistant_text_message("done"))

    async def scenario() -> None:
        agent = Agent(stream_fn=stream_fn)
        agent.state.messages.append(_assistant_text_message("done"))
        agent.follow_up_mode = "all"
        agent.follow_up(UserMessage(role="user", content="f1", timestamp=0.0))
        agent.follow_up(UserMessage(role="user", content="f2", timestamp=0.0))

        await agent.continue_run()

        assert seen_user_messages == [["f1", "f2"]]

    asyncio.run(scenario())


def test_initial_state_accepts_partial_mapping() -> None:
    from loushang.agent import Agent

    agent = Agent(
        initial_state={
            "system_prompt": "sys",
            "model": _model(),
            "thinking_level": "low",
        }
    )

    assert agent.state.system_prompt == "sys"
    assert agent.state.model.id == "faux-model"
    assert agent.state.thinking_level == "low"
    assert agent.state.messages == []
    assert agent.state.tools == []
    assert agent.state.pending_tool_calls == set()
    assert agent.state.is_streaming is False
