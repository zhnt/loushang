from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any

from loushang.agent.agent_loop import run_agent_loop, run_agent_loop_continue
from loushang.agent.types import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentOptions,
    AgentState,
    AgentTool,
    BeforeToolCallContext,
    BeforeToolCallResult,
    ThinkingLevel,
    ToolExecutionMode,
)
from loushang.ai.api import stream
from loushang.ai.messages import canonicalize_user_message
from loushang.ai.model import Capabilities, Model
from loushang.ai.model.registry import resolve_model_api
from loushang.ai.options import CallOptions, ReasoningOptions, RetryOptions
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    Message,
    TextPart,
    Usage,
    UserMessage,
)

_ABORT_EXECUTION_CANCEL_DELAY_S = 0.05


class AgentStateError(RuntimeError):
    """Agent 状态错误，当操作在非法状态下执行时抛出。"""

    pass


async def _default_stream(model, context, options=None):
    return await stream(model, context, options)


def _default_model() -> Model:
    return Model(
        id="unknown",
        name="unknown",
        provider="unknown",
        endpoint="unknown",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=None,
            max_tokens=None,
        ),
    )


def _default_convert_to_llm(messages: list[AgentMessage]) -> list[Message]:
    return [
        message
        for message in messages
        if isinstance(message, UserMessage)
        or isinstance(message, AssistantMessage)
        or getattr(message, "role", None) == "toolResult"
    ]


class AbortSignal:
    def __init__(self) -> None:
        self.aborted = False
        self._execution_tasks: set[asyncio.Task[Any]] = set()

    def _register_execution_task(self, task: asyncio.Task[Any]) -> None:
        self._execution_tasks.add(task)
        task.add_done_callback(self._execution_tasks.discard)
        if self.aborted and not task.done():
            task.cancel()

    def _unregister_execution_task(self, task: asyncio.Task[Any]) -> None:
        self._execution_tasks.discard(task)

    def _cancel_execution_tasks(self) -> None:
        for task in tuple(self._execution_tasks):
            if not task.done():
                task.cancel()


class AbortController:
    def __init__(self) -> None:
        self.signal = AbortSignal()
        self._force_cancel_handle: asyncio.TimerHandle | None = None

    def abort(self) -> None:
        if self.signal.aborted:
            return
        self.signal.aborted = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.signal._cancel_execution_tasks()
            return
        self._force_cancel_handle = loop.call_later(
            _ABORT_EXECUTION_CANCEL_DELAY_S,
            self.signal._cancel_execution_tasks,
        )

    def finish(self) -> None:
        if self._force_cancel_handle is not None:
            self._force_cancel_handle.cancel()
            self._force_cancel_handle = None


class PendingMessageQueue:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self._messages: list[AgentMessage] = []

    def enqueue(self, message: AgentMessage) -> None:
        self._messages.append(message)

    def has_items(self) -> bool:
        return bool(self._messages)

    def drain(self) -> list[AgentMessage]:
        if self.mode == "all":
            drained = list(self._messages)
            self._messages.clear()
            return drained
        if not self._messages:
            return []
        return [self._messages.pop(0)]

    def clear(self) -> None:
        self._messages.clear()


class Agent:
    def __init__(self, **kwargs: Any) -> None:
        options = AgentOptions(**kwargs)
        self._state = _create_agent_state(options.initial_state)
        self.convert_to_llm = options.convert_to_llm or _default_convert_to_llm
        self.transform_context = options.transform_context
        self.stream_fn = options.stream_fn or _default_stream
        self.call_options = options.call_options or CallOptions()
        self.before_tool_call = options.before_tool_call
        self.after_tool_call = options.after_tool_call
        self.mailbox_queue = PendingMessageQueue("all")
        self.steering_queue = PendingMessageQueue(options.steering_mode)
        self.follow_up_queue = PendingMessageQueue(options.follow_up_mode)
        self._session_id = options.session_id
        self._thinking_budgets = options.thinking_budgets
        self._max_retry_delay_ms = options.max_retry_delay_ms
        self.tool_execution = options.tool_execution
        self._listeners: dict[
            Callable[[AgentEvent, AbortSignal], Awaitable[None] | None], None
        ] = {}
        self._active_run_task: asyncio.Task[None] | None = None
        self._active_abort_controller: AbortController | None = None

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def signal(self) -> AbortSignal | None:
        if self._active_abort_controller is None:
            return None
        return self._active_abort_controller.signal

    # === Runtime state setters (aligned with pi-agent) ===

    @property
    def system_prompt(self) -> str:
        """Get the current system prompt."""
        return self._state.system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        """Set the system prompt."""
        self._state.system_prompt = value

    @property
    def model(self) -> Model:
        """Get the current model."""
        return self._state.model

    @model.setter
    def model(self, value: Model) -> None:
        """Set the model for subsequent calls."""
        self._state.model = value

    @property
    def thinking_level(self) -> ThinkingLevel:
        """Get the current thinking/reasoning level."""
        return self._state.thinking_level

    @thinking_level.setter
    def thinking_level(self, value: ThinkingLevel) -> None:
        """Set the thinking/reasoning level."""
        self._state.thinking_level = value

    @property
    def tools(self) -> list[AgentTool[Any]]:
        """Get a copy of the current tools list."""
        return list(self._state.tools)

    @tools.setter
    def tools(self, value: list[AgentTool[Any]]) -> None:
        """Set the tools list."""
        self._state.set_tools(value)

    @property
    def tool_execution(self) -> ToolExecutionMode:
        """Get the tool execution mode (sequential or parallel)."""
        return self._tool_execution

    @tool_execution.setter
    def tool_execution(self, value: ToolExecutionMode) -> None:
        """Set the tool execution mode."""
        self._tool_execution = value

    @property
    def before_tool_call(
        self,
    ) -> (
        Callable[
            [BeforeToolCallContext, object | None],
            Awaitable[BeforeToolCallResult | None],
        ]
        | None
    ):
        """Get the beforeToolCall hook if set."""
        return self._before_tool_call

    @before_tool_call.setter
    def before_tool_call(
        self,
        value: Callable[
            [BeforeToolCallContext, object | None],
            Awaitable[BeforeToolCallResult | None],
        ]
        | None,
    ) -> None:
        """Set the beforeToolCall hook called before each tool execution."""
        self._before_tool_call = value

    @property
    def after_tool_call(
        self,
    ) -> (
        Callable[
            [AfterToolCallContext, object | None], Awaitable[AfterToolCallResult | None]
        ]
        | None
    ):
        """Get the afterToolCall hook if set."""
        return self._after_tool_call

    @after_tool_call.setter
    def after_tool_call(
        self,
        value: Callable[
            [AfterToolCallContext, object | None], Awaitable[AfterToolCallResult | None]
        ]
        | None,
    ) -> None:
        """Set the afterToolCall hook called after each tool execution."""
        self._after_tool_call = value

    # === Stream/advanced options (aligned with pi-agent) ===

    @property
    def session_id(self) -> str | None:
        """Get the current session ID used for provider caching."""
        return self._session_id

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        """Set the session ID for provider caching.

        Call this when switching sessions (new session, branch, resume).
        """
        self._session_id = value

    @property
    def thinking_budgets(self) -> dict[str, int] | None:
        """Get custom token budgets for thinking levels (token-based providers only)."""
        return self._thinking_budgets

    @thinking_budgets.setter
    def thinking_budgets(self, value: dict[str, int] | None) -> None:
        """Set custom thinking budgets for token-based providers."""
        self._thinking_budgets = value

    @property
    def max_retry_delay_ms(self) -> int | None:
        """Get the maximum delay in milliseconds to wait for a server-requested retry."""
        return self._max_retry_delay_ms

    @max_retry_delay_ms.setter
    def max_retry_delay_ms(self, value: int | None) -> None:
        """Set the maximum delay to wait for server-requested retries.

        If the server's requested delay exceeds this value, the request fails immediately,
        allowing higher-level retry logic to handle it with user visibility.
        Set to 0 to disable the cap.
        """
        self._max_retry_delay_ms = value

    # === Convenience properties ===

    @property
    def is_streaming(self) -> bool:
        """Check if the agent is currently processing a prompt."""
        return self._state.is_streaming

    @property
    def messages(self) -> list[AgentMessage]:
        """Get a copy of the conversation messages."""
        return list(self._state.messages)

    @property
    def error_message(self) -> str | None:
        """Get the last error message if any."""
        return self._state.error_message

    # === Message manipulation methods (aligned with pi-agent) ===

    def replace_messages(self, messages: list[AgentMessage]) -> None:
        """Replace all messages in the conversation.

        Equivalent to pi-agent's replaceMessages().

        Whole-list replacement must use `AgentState.set_messages()` to preserve
        top-level copy semantics. Incremental updates should mutate the live
        list returned by `state.messages`.
        """
        self._state.set_messages([canonicalize_user_message(m) for m in messages])

    def append_message(self, message: AgentMessage) -> None:
        """Append a single message to the conversation.

        Equivalent to pi-agent's appendMessage().
        """
        self._state.messages.append(canonicalize_user_message(message))

    def clear_messages(self) -> None:
        """Clear all messages from the conversation.

        Equivalent to pi-agent's clearMessages().

        This is an intentional in-place mutation of the live messages list,
        rather than a whole-list replacement.
        """
        self._state.messages.clear()

    @property
    def steering_mode(self) -> str:
        return self.steering_queue.mode

    @steering_mode.setter
    def steering_mode(self, mode: str) -> None:
        self.steering_queue.mode = mode

    @property
    def follow_up_mode(self) -> str:
        return self.follow_up_queue.mode

    @follow_up_mode.setter
    def follow_up_mode(self, mode: str) -> None:
        self.follow_up_queue.mode = mode

    def subscribe(
        self, listener: Callable[[AgentEvent, AbortSignal], Awaitable[None] | None]
    ) -> Callable[[], None]:
        self._listeners.setdefault(listener, None)

        def unsubscribe() -> None:
            self._listeners.pop(listener, None)

        return unsubscribe

    def steer(self, message: AgentMessage) -> AgentMessage:
        queued_message = canonicalize_user_message(message)
        self.steering_queue.enqueue(queued_message)
        return queued_message

    def follow_up(self, message: AgentMessage) -> AgentMessage:
        queued_message = canonicalize_user_message(message)
        self.follow_up_queue.enqueue(queued_message)
        return queued_message

    def enqueue_mailbox(self, message: AgentMessage) -> AgentMessage:
        """Queue system-owned input outside the editable user queues."""

        queued_message = canonicalize_user_message(message)
        self.mailbox_queue.enqueue(queued_message)
        return queued_message

    def clear_mailbox_queue(self) -> None:
        self.mailbox_queue.clear()

    def clear_steering_queue(self) -> None:
        self.steering_queue.clear()

    def clear_follow_up_queue(self) -> None:
        self.follow_up_queue.clear()

    def clear_all_queues(self) -> None:
        self.clear_mailbox_queue()
        self.clear_steering_queue()
        self.clear_follow_up_queue()

    def has_queued_messages(self) -> bool:
        return (
            self.mailbox_queue.has_items()
            or self.steering_queue.has_items()
            or self.follow_up_queue.has_items()
        )

    def abort(self) -> None:
        if self._active_abort_controller is not None:
            self._active_abort_controller.abort()

    async def wait_for_idle(self) -> None:
        active_task = self._active_run_task
        if active_task is not None:
            await asyncio.shield(active_task)

    def reset(self) -> None:
        self._state.set_messages([])
        self._state.is_streaming = False
        self._state.streaming_message = None
        self._state.pending_tool_calls = set()
        self._state.error_message = None
        self.clear_all_queues()

    async def prompt(
        self,
        input: str | AgentMessage | list[AgentMessage],
        images: list[ImagePart] | None = None,
    ) -> None:
        if self._active_run_task is not None:
            raise AgentStateError(
                "Agent is already processing a prompt. Use steer() or followUp() to queue messages, or wait for completion."
            )
        messages = self._normalize_prompt_input(input, images)
        await self._run_prompt_messages(messages)

    async def continue_run(self) -> None:
        if self._active_run_task is not None:
            raise AgentStateError(
                "Agent is already processing. Wait for completion before continuing."
            )

        last_message = self._state.messages[-1] if self._state.messages else None
        if last_message is None:
            raise RuntimeError("No messages to continue from")

        if getattr(last_message, "role", None) == "assistant":
            queued_mailbox = self.mailbox_queue.drain()
            if queued_mailbox:
                await self._run_prompt_messages(queued_mailbox)
                return

            queued_steering = self.steering_queue.drain()
            if queued_steering:
                await self._run_prompt_messages(
                    queued_steering, skip_initial_steering_poll=True
                )
                return

            queued_follow_ups = self.follow_up_queue.drain()
            if queued_follow_ups:
                await self._run_prompt_messages(queued_follow_ups)
                return

            raise RuntimeError("Cannot continue from message role: assistant")

        await self._run_continuation()

    async def _run_prompt_messages(
        self, messages: list[AgentMessage], skip_initial_steering_poll: bool = False
    ) -> None:
        async def executor(signal: AbortSignal) -> None:
            await run_agent_loop(
                list(messages),
                self._create_context_snapshot(),
                self._create_loop_config(
                    skip_initial_steering_poll=skip_initial_steering_poll
                ),
                self._process_event,
                signal=signal,
                stream_fn=self.stream_fn,
            )

        await self._run_with_lifecycle(executor)

    async def _run_continuation(self) -> None:
        async def executor(signal: AbortSignal) -> None:
            await run_agent_loop_continue(
                self._create_context_snapshot(),
                self._create_loop_config(),
                self._process_event,
                signal=signal,
                stream_fn=self.stream_fn,
            )

        await self._run_with_lifecycle(executor)

    def _create_context_snapshot(self) -> AgentContext:
        return AgentContext(
            system_prompt=self._state.system_prompt,
            messages=[
                canonicalize_user_message(message) for message in self._state.messages
            ],
            tools=list(self._state.tools),
        )

    def _create_loop_config(
        self, *, skip_initial_steering_poll: bool = False
    ) -> AgentLoopConfig:
        local_skip = skip_initial_steering_poll

        async def get_mailbox_messages() -> list[AgentMessage]:
            return self.mailbox_queue.drain()

        async def get_steering_messages() -> list[AgentMessage]:
            nonlocal local_skip
            if local_skip:
                local_skip = False
                return []
            return self.steering_queue.drain()

        async def get_follow_up_messages() -> list[AgentMessage]:
            return self.follow_up_queue.drain()

        call_options = replace(
            self.call_options,
            cache_key=self.call_options.cache_key or self.session_id,
            reasoning=self.call_options.reasoning
            or _reasoning_options(
                self._state.thinking_level,
                self.thinking_budgets,
            ),
            retry=self.call_options.retry or _retry_options(self.max_retry_delay_ms),
        )
        return AgentLoopConfig(
            model=self._state.model,
            call_options=call_options,
            tool_execution=self.tool_execution,
            before_tool_call=self.before_tool_call,
            after_tool_call=self.after_tool_call,
            convert_to_llm=self.convert_to_llm,
            transform_context=self.transform_context,
            get_mailbox_messages=get_mailbox_messages,
            get_steering_messages=get_steering_messages,
            get_follow_up_messages=get_follow_up_messages,
        )

    def _normalize_prompt_input(
        self,
        input: str | AgentMessage | list[AgentMessage],
        images: list[ImagePart] | None = None,
    ) -> list[AgentMessage]:
        if isinstance(input, list):
            return [canonicalize_user_message(message) for message in input]
        if not isinstance(input, str):
            return [canonicalize_user_message(input)]
        content: list[TextPart | ImagePart] = [TextPart(type="text", text=input)]
        if images:
            content.extend(images)
        return [UserMessage(role="user", content=content, timestamp=time.time() * 1000)]

    async def _run_with_lifecycle(
        self, executor: Callable[[AbortSignal], Awaitable[None]]
    ) -> None:
        if self._active_run_task is not None:
            raise AgentStateError("Agent is already processing.")

        abort_controller = AbortController()
        self._active_abort_controller = abort_controller
        self._state.is_streaming = True
        self._state.streaming_message = None
        self._state.error_message = None

        async def runner() -> None:
            try:
                await executor(abort_controller.signal)
            except asyncio.CancelledError:
                if abort_controller.signal.aborted:
                    await self._handle_run_failure(
                        RuntimeError("Request aborted by user"), aborted=True
                    )
                    return
                raise
            except Exception as error:
                await self._handle_run_failure(
                    error, aborted=abort_controller.signal.aborted
                )
            finally:
                self._finish_run()

        self._active_run_task = asyncio.create_task(runner())
        active_task = self._active_run_task
        caller_cancelled = False
        while not active_task.done():
            try:
                await asyncio.shield(active_task)
            except asyncio.CancelledError:
                caller_cancelled = True
                abort_controller.abort()
        active_task.result()
        if caller_cancelled:
            raise asyncio.CancelledError

    async def _handle_run_failure(self, error: Exception, *, aborted: bool) -> None:
        failure_message = AssistantMessage(
            role="assistant",
            content=[TextPart(type="text", text="")],
            api=_resolve_failure_message_api(self._state.model),
            provider=self._state.model.provider_id,
            endpoint=self._state.model.endpoint_id,
            model=self._state.model.id,
            response_id=None,
            usage=_empty_usage(),
            stop_reason="aborted" if aborted else "error",
            error_message=str(error),
            timestamp=time.time() * 1000,
        )
        self._state.messages.append(failure_message)
        self._state.error_message = failure_message.error_message
        await self._process_event({"type": "agent_end", "messages": [failure_message]})

    def _finish_run(self) -> None:
        self._state.is_streaming = False
        self._state.streaming_message = None
        self._state.pending_tool_calls = set()
        if self._active_abort_controller is not None:
            self._active_abort_controller.finish()
        self._active_abort_controller = None
        self._active_run_task = None

    async def _process_event(self, event: AgentEvent) -> None:
        event_type = event["type"]
        if event_type in {"message_start", "message_update"}:
            self._state.streaming_message = event["message"]
        elif event_type == "message_end":
            self._state.streaming_message = None
            self._state.messages.append(event["message"])
        elif event_type == "tool_execution_start":
            self._state.pending_tool_calls = set(self._state.pending_tool_calls)
            self._state.pending_tool_calls.add(event["tool_call_id"])
        elif event_type == "tool_execution_end":
            self._state.pending_tool_calls = set(self._state.pending_tool_calls)
            self._state.pending_tool_calls.discard(event["tool_call_id"])
        elif event_type == "turn_end":
            message = event["message"]
            if isinstance(message, AssistantMessage) and message.error_message:
                self._state.error_message = message.error_message
        elif event_type == "agent_end":
            self._state.streaming_message = None

        if self._active_abort_controller is None:
            raise RuntimeError("Agent listener invoked outside active run")
        signal = self._active_abort_controller.signal
        for listener in list(self._listeners):
            result = listener(event, signal)
            if asyncio.iscoroutine(result):
                await result


def _initial_state_value(
    initial_state: AgentState | Mapping[str, Any] | object, key: str, default: Any
) -> Any:
    if isinstance(initial_state, Mapping):
        return initial_state.get(key, default)
    return getattr(initial_state, key, default)


def _create_agent_state(
    initial_state: AgentState | Mapping[str, Any] | object | None,
) -> AgentState:
    if initial_state is None:
        return AgentState(
            system_prompt="", model=_default_model(), thinking_level="off"
        )

    return AgentState(
        system_prompt=_initial_state_value(initial_state, "system_prompt", ""),
        model=_initial_state_value(initial_state, "model", _default_model()),
        thinking_level=_initial_state_value(initial_state, "thinking_level", "off"),
        tools=_initial_state_value(initial_state, "tools", []),
        messages=_initial_state_value(initial_state, "messages", []),
        is_streaming=_initial_state_value(initial_state, "is_streaming", False),
        streaming_message=_initial_state_value(
            initial_state, "streaming_message", None
        ),
        pending_tool_calls=set(
            _initial_state_value(initial_state, "pending_tool_calls", set())
        ),
        error_message=_initial_state_value(initial_state, "error_message", None),
    )


def _reasoning_options(
    thinking_level: ThinkingLevel,
    thinking_budgets: Mapping[str, int] | None,
) -> ReasoningOptions | None:
    if thinking_level == "off":
        return None
    budget_tokens = None
    if thinking_budgets is not None:
        budget = thinking_budgets.get(thinking_level)
        if isinstance(budget, int):
            budget_tokens = budget
    return ReasoningOptions(
        enabled=True,
        effort=thinking_level,
        budget_tokens=budget_tokens,
    )


def _retry_options(max_retry_delay_ms: int | None) -> RetryOptions | None:
    if not isinstance(max_retry_delay_ms, int):
        return None
    return RetryOptions(
        max_attempts=1, max_delay_seconds=max(0, max_retry_delay_ms) / 1000
    )


def _empty_usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost=None,
    )


def _resolve_failure_message_api(model: Model) -> str:
    try:
        return resolve_model_api(model)
    except ValueError:
        return model.endpoint_id


__all__ = [
    "Agent",
    "AbortController",
    "AbortSignal",
    "PendingMessageQueue",
    "AgentStateError",
]
