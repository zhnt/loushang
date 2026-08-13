from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import pytest

from loushang.agent import Agent
from loushang.agent.types import AgentState, AgentToolResult
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import (
    AssistantMessage,
    Context,
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
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )


@dataclass(frozen=True)
class ModelCall:
    index: int


@dataclass(frozen=True)
class UserConsumed:
    text: str


@dataclass(frozen=True)
class ToolStarted:
    name: str = "scenario_tool"


@dataclass(frozen=True)
class ToolFinished:
    name: str = "scenario_tool"


@dataclass(frozen=True)
class ModelText:
    text: str

    async def run(self, runtime: ScenarioRuntime) -> None:
        await runtime.model_responses.put(self)


@dataclass(frozen=True)
class ModelToolCall:
    name: str = "scenario_tool"
    tool_call_id: str = "tc_1"

    async def run(self, runtime: ScenarioRuntime) -> None:
        await runtime.model_responses.put(self)


@dataclass(frozen=True)
class ToolResult:
    text: str = "tool result"

    async def run(self, runtime: ScenarioRuntime) -> None:
        await runtime.tool_responses.put(self)


@dataclass(frozen=True)
class StartPrompt:
    text: str

    async def run(self, runtime: ScenarioRuntime) -> None:
        runtime.start_prompt(self.text)


@dataclass(frozen=True)
class Prompt:
    text: str
    response: ModelText = ModelText("ok")

    async def run(self, runtime: ScenarioRuntime) -> None:
        next_call = ModelCall(runtime.model_call_count + 1)
        runtime.start_prompt(self.text)
        await runtime.wait_for(next_call)
        await self.response.run(runtime)
        await runtime.wait_idle()


@dataclass(frozen=True)
class Steer:
    text: str

    async def run(self, runtime: ScenarioRuntime) -> None:
        runtime.agent.steer(_user_message(self.text))


@dataclass(frozen=True)
class FollowUp:
    text: str

    async def run(self, runtime: ScenarioRuntime) -> None:
        runtime.agent.follow_up(_user_message(self.text))


@dataclass(frozen=True)
class Abort:
    clear_queues: bool = True

    async def run(self, runtime: ScenarioRuntime) -> None:
        runtime.abort(clear_queues=self.clear_queues)


@dataclass(frozen=True)
class AbortOnToolFinished:
    name: str = "scenario_tool"
    clear_queues: bool = True

    async def run(self, runtime: ScenarioRuntime) -> None:
        def abort_after_public_tool_result(event: dict, signal: object) -> None:
            del signal
            if event.get("type") != "tool_execution_end":
                return
            if event.get("tool_name") != self.name:
                return
            unsubscribe()
            runtime.abort(clear_queues=self.clear_queues)

        unsubscribe = runtime.agent.subscribe(abort_after_public_tool_result)


@dataclass(frozen=True)
class WaitFor:
    checkpoint: object
    timeout: float = 1.0

    async def run(self, runtime: ScenarioRuntime) -> None:
        await runtime.wait_for(self.checkpoint, timeout=self.timeout)


@dataclass(frozen=True)
class WaitIdle:
    async def run(self, runtime: ScenarioRuntime) -> None:
        await runtime.wait_idle()


@dataclass(frozen=True)
class Expect:
    model_user_inputs: Sequence[str] | None = None
    consumed_users: Sequence[str] | None = None
    not_consumed: Sequence[str] = ()
    roles: Sequence[str] | None = None
    abort_boundaries: int | None = None
    final_idle: bool = True
    no_queued_messages: bool = True

    async def run(self, runtime: ScenarioRuntime) -> None:
        if self.model_user_inputs is not None:
            assert runtime.model_user_inputs == list(self.model_user_inputs)
        if self.consumed_users is not None:
            assert runtime.consumed_user_texts == list(self.consumed_users)
        for text in self.not_consumed:
            assert text not in runtime.consumed_user_texts
            assert text not in runtime.model_user_inputs
        if self.roles is not None:
            assert [
                getattr(message, "role", None)
                for message in runtime.agent.state.messages
            ] == list(self.roles)
        if self.abort_boundaries is not None:
            assert (
                _abort_boundary_count(runtime.agent.state.messages)
                == self.abort_boundaries
            )
        if self.final_idle:
            assert runtime.agent.state.is_streaming is False
            assert runtime.agent.signal is None
        if self.no_queued_messages:
            assert runtime.agent.has_queued_messages() is False


class Step(Protocol):
    async def run(self, runtime: "ScenarioRuntime") -> None: ...


@dataclass(frozen=True)
class Scenario:
    name: str
    steps: Sequence[Step]
    steering_mode: str = "one-at-a-time"
    follow_up_mode: str = "one-at-a-time"


class ScenarioTool:
    name = "scenario_tool"
    description = "scenario tool"
    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }
    label = "Scenario Tool"
    prepare_arguments = None

    def __init__(self, runtime: "ScenarioRuntime") -> None:
        self.runtime = runtime

    async def execute(
        self, tool_call_id: str, params: dict, signal=None, on_update=None
    ) -> AgentToolResult[dict]:
        del tool_call_id, params, on_update
        self.runtime.signal(ToolStarted(self.name))
        response = await self.runtime.next_tool_result(signal=signal)
        return AgentToolResult(
            content=[TextPart(type="text", text=response.text)],
            details={"text": response.text},
        )


class ScenarioRuntime:
    def __init__(self, *, steering_mode: str, follow_up_mode: str) -> None:
        self.model_responses: asyncio.Queue[ModelText | ModelToolCall] = asyncio.Queue()
        self.tool_responses: asyncio.Queue[ToolResult] = asyncio.Queue()
        self.checkpoints: dict[object, asyncio.Event] = {}
        self.tasks: list[asyncio.Task[None]] = []
        self.current_abort_event: asyncio.Event | None = None
        self.model_call_count = 0
        self.model_user_inputs: list[str] = []
        self.consumed_user_texts: list[str] = []
        state = AgentState(
            system_prompt="",
            model=_model(),
            thinking_level="off",
            tools=[ScenarioTool(self)],
        )
        self.agent = Agent(
            stream_fn=self.stream_fn,
            initial_state=state,
            steering_mode=steering_mode,
            follow_up_mode=follow_up_mode,
        )
        self.agent.subscribe(self._handle_event)

    def start_prompt(self, text: str) -> None:
        if self.current_abort_event is None or self.current_abort_event.is_set():
            self.current_abort_event = asyncio.Event()
        self.tasks.append(asyncio.create_task(self.agent.prompt(text)))

    async def wait_idle(self) -> None:
        if self.tasks:
            await asyncio.gather(*self.tasks)
            self.tasks.clear()
        self.current_abort_event = None

    async def wait_for(self, checkpoint: object, *, timeout: float = 1.0) -> None:
        async with asyncio.timeout(timeout):
            await self._event_for(checkpoint).wait()

    def abort(self, *, clear_queues: bool) -> None:
        self.agent.abort()
        if clear_queues:
            self.agent.clear_all_queues()
        self.signal_abort()

    def signal(self, checkpoint: object) -> None:
        self._event_for(checkpoint).set()

    def signal_abort(self) -> None:
        if self.current_abort_event is not None:
            self.current_abort_event.set()

    async def stream_fn(
        self, model, context: Context, options=None
    ) -> AssistantMessageEventStream:
        del model
        self.model_call_count += 1
        self.model_user_inputs.append(_last_user_text(context.messages))
        self.signal(ModelCall(self.model_call_count))
        response = await self.next_model_response(
            signal=getattr(options, "cancellation", None)
        )
        if isinstance(response, ModelToolCall):
            return _stream_with_final_message(
                _assistant_tool_call_message(response.name, response.tool_call_id)
            )
        return _stream_with_final_message(_assistant_text_message(response.text))

    async def next_model_response(
        self, *, signal: object | None
    ) -> ModelText | ModelToolCall:
        response = await self._wait_for_queue_or_abort(
            self.model_responses, signal=signal
        )
        return response

    async def next_tool_result(self, *, signal: object | None) -> ToolResult:
        response = await self._wait_for_queue_or_abort(
            self.tool_responses, signal=signal
        )
        return response

    async def _wait_for_queue_or_abort(
        self, queue: asyncio.Queue, *, signal: object | None
    ):
        abort_event = self.current_abort_event
        if abort_event is None:
            return await queue.get()
        response_task = asyncio.create_task(queue.get())
        abort_task = asyncio.create_task(abort_event.wait())
        done, pending = await asyncio.wait(
            {response_task, abort_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if abort_task in done and _is_aborted(signal):
            raise RuntimeError("Request aborted by user")
        return response_task.result()

    async def _handle_event(self, event: dict, signal: object) -> None:
        del signal
        if event.get("type") == "tool_execution_end":
            self.signal(ToolFinished(str(event.get("tool_name", ""))))
            return
        if event.get("type") != "message_start":
            return
        message = event.get("message")
        if isinstance(message, UserMessage):
            text = _user_text(message)
            self.consumed_user_texts.append(text)
            self.signal(UserConsumed(text))

    def _event_for(self, checkpoint: object) -> asyncio.Event:
        event = self.checkpoints.get(checkpoint)
        if event is None:
            event = asyncio.Event()
            self.checkpoints[checkpoint] = event
        return event


SCENARIOS = [
    Scenario(
        name="abort_during_model_then_new_prompt",
        steps=[
            StartPrompt("long task"),
            WaitFor(ModelCall(1)),
            Abort(),
            WaitIdle(),
            Prompt("你好", ModelText("hello")),
            Expect(
                model_user_inputs=["long task", "你好"],
                consumed_users=["long task", "你好"],
                roles=["user", "assistant", "user", "assistant"],
                abort_boundaries=1,
            ),
        ],
    ),
    Scenario(
        name="steer_consumed_followup_aborted_before_consumed",
        steps=[
            StartPrompt("long task"),
            WaitFor(ModelCall(1)),
            Steer("steer current run"),
            ModelText("first"),
            WaitFor(UserConsumed("steer current run")),
            WaitFor(ModelCall(2)),
            FollowUp("queued follow-up"),
            Abort(),
            WaitIdle(),
            Prompt("你好", ModelText("hello")),
            Expect(
                model_user_inputs=["long task", "steer current run", "你好"],
                consumed_users=["long task", "steer current run", "你好"],
                not_consumed=["queued follow-up"],
                abort_boundaries=1,
            ),
        ],
    ),
    Scenario(
        name="followup_runs_when_not_aborted",
        steps=[
            StartPrompt("first"),
            WaitFor(ModelCall(1)),
            FollowUp("follow-up"),
            ModelText("first response"),
            WaitFor(UserConsumed("follow-up")),
            WaitFor(ModelCall(2)),
            ModelText("follow-up response"),
            WaitIdle(),
            Expect(
                model_user_inputs=["first", "follow-up"],
                consumed_users=["first", "follow-up"],
                abort_boundaries=0,
                roles=["user", "assistant", "user", "assistant"],
            ),
        ],
    ),
    Scenario(
        name="steer_aborted_before_consumed",
        steps=[
            StartPrompt("first"),
            WaitFor(ModelCall(1)),
            Steer("steer that should be cleared"),
            Abort(),
            WaitIdle(),
            Prompt("你好", ModelText("hello")),
            Expect(
                model_user_inputs=["first", "你好"],
                consumed_users=["first", "你好"],
                not_consumed=["steer that should be cleared"],
                abort_boundaries=1,
            ),
        ],
    ),
    Scenario(
        name="tool_started_then_abort_then_new_prompt",
        steps=[
            StartPrompt("use tool"),
            WaitFor(ModelCall(1)),
            ModelToolCall(),
            WaitFor(ToolStarted()),
            Abort(),
            WaitIdle(),
            Prompt("你好", ModelText("hello")),
            Expect(
                model_user_inputs=["use tool", "你好"],
                consumed_users=["use tool", "你好"],
                abort_boundaries=1,
            ),
        ],
    ),
    Scenario(
        name="tool_result_then_abort_then_new_prompt",
        steps=[
            StartPrompt("use tool"),
            WaitFor(ModelCall(1)),
            ModelToolCall(),
            WaitFor(ToolStarted()),
            AbortOnToolFinished(),
            ToolResult("done"),
            WaitFor(ToolFinished()),
            WaitIdle(),
            Prompt("你好", ModelText("hello")),
            Expect(
                model_user_inputs=["use tool", "你好"],
                consumed_users=["use tool", "你好"],
                roles=[
                    "user",
                    "assistant",
                    "toolResult",
                    "assistant",
                    "user",
                    "assistant",
                ],
                abort_boundaries=1,
            ),
        ],
    ),
    Scenario(
        name="steer_after_tool_call_preserves_tool_result",
        steps=[
            StartPrompt("use tool then steer"),
            WaitFor(ModelCall(1)),
            ModelToolCall(),
            WaitFor(ToolStarted()),
            Steer("steer after tool"),
            ToolResult("done"),
            WaitFor(ToolFinished()),
            WaitFor(UserConsumed("steer after tool")),
            WaitFor(ModelCall(2)),
            ModelText("steer response"),
            WaitIdle(),
            Expect(
                model_user_inputs=["use tool then steer", "steer after tool"],
                consumed_users=["use tool then steer", "steer after tool"],
                roles=["user", "assistant", "toolResult", "user", "assistant"],
                abort_boundaries=0,
            ),
        ],
    ),
    Scenario(
        name="multiple_steers_one_at_a_time_abort_before_second",
        steps=[
            StartPrompt("first"),
            WaitFor(ModelCall(1)),
            Steer("steer one"),
            Steer("steer two"),
            ModelText("first response"),
            WaitFor(UserConsumed("steer one")),
            WaitFor(ModelCall(2)),
            Abort(),
            WaitIdle(),
            Prompt("你好", ModelText("hello")),
            Expect(
                model_user_inputs=["first", "steer one", "你好"],
                consumed_users=["first", "steer one", "你好"],
                not_consumed=["steer two"],
                abort_boundaries=1,
            ),
        ],
    ),
    Scenario(
        name="multiple_steers_all_mode_consumed_together",
        steering_mode="all",
        steps=[
            StartPrompt("first"),
            WaitFor(ModelCall(1)),
            Steer("steer one"),
            Steer("steer two"),
            ModelText("first response"),
            WaitFor(UserConsumed("steer one")),
            WaitFor(UserConsumed("steer two")),
            WaitFor(ModelCall(2)),
            ModelText("steer response"),
            WaitIdle(),
            Expect(
                model_user_inputs=["first", "steer two"],
                consumed_users=["first", "steer one", "steer two"],
                abort_boundaries=0,
            ),
        ],
    ),
    Scenario(
        name="multiple_followups_all_mode_consumed_together",
        follow_up_mode="all",
        steps=[
            StartPrompt("first"),
            WaitFor(ModelCall(1)),
            FollowUp("follow one"),
            FollowUp("follow two"),
            ModelText("first response"),
            WaitFor(UserConsumed("follow one")),
            WaitFor(UserConsumed("follow two")),
            WaitFor(ModelCall(2)),
            ModelText("follow response"),
            WaitIdle(),
            Expect(
                model_user_inputs=["first", "follow two"],
                consumed_users=["first", "follow one", "follow two"],
                abort_boundaries=0,
            ),
        ],
    ),
    Scenario(
        name="followup_queued_then_abort_before_first_response",
        steps=[
            StartPrompt("first"),
            WaitFor(ModelCall(1)),
            FollowUp("follow-up"),
            Abort(),
            WaitIdle(),
            Prompt("你好", ModelText("hello")),
            Expect(
                model_user_inputs=["first", "你好"],
                consumed_users=["first", "你好"],
                not_consumed=["follow-up"],
                abort_boundaries=1,
            ),
        ],
    ),
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_agent_loop_control_flow_scenarios(scenario: Scenario) -> None:
    async def run() -> None:
        runtime = ScenarioRuntime(
            steering_mode=scenario.steering_mode,
            follow_up_mode=scenario.follow_up_mode,
        )
        for step in scenario.steps:
            await step.run(runtime)

    asyncio.run(run())


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


def _assistant_tool_call_message(name: str, tool_call_id: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[ToolCall(type="toolCall", id=tool_call_id, name=name, arguments={})],
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
    message: AssistantMessage,
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()
    stream.push({"type": "start", "partial": message})
    if message.content and isinstance(message.content[0], TextPart):
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
    elif message.content and isinstance(message.content[0], ToolCall):
        stream.push({"type": "toolcall_start", "content_index": 0, "partial": message})
        stream.push(
            {
                "type": "toolcall_delta",
                "content_index": 0,
                "delta": "{}",
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
    return stream


def _user_message(text: str) -> UserMessage:
    return UserMessage(
        role="user", content=[TextPart(type="text", text=text)], timestamp=0.0
    )


def _user_text(message: UserMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "\n".join(part.text for part in content if isinstance(part, TextPart))


def _last_user_text(messages: Sequence[object]) -> str:
    for message in reversed(messages):
        if isinstance(message, UserMessage):
            return _user_text(message)
    return ""


def _abort_boundary_count(messages: Sequence[object]) -> int:
    return sum(
        1
        for message in messages
        if isinstance(message, AssistantMessage) and message.stop_reason == "aborted"
    )


def _is_aborted(signal: object | None) -> bool:
    return bool(signal is not None and getattr(signal, "aborted", False))
