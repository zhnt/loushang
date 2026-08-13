from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any, TypeVar

from loushang.agent.tool_output import (
    STRICT_JSON_TOOL_OUTPUT_PROJECTOR,
    ToolOutputProjectionError,
)
from loushang.agent.types import (
    AfterToolCallContext,
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentTool,
    AgentToolCall,
    AgentToolResult,
    BeforeToolCallContext,
    StreamFn,
)
from loushang.ai.api import stream
from loushang.ai.event_stream import EventStream
from loushang.ai.tool.validation import validate_tool_arguments
from loushang.ai.types import (
    AssistantMessage,
    Context,
    TextPart,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
)
from loushang.foundation.json import JSONValue
from loushang.foundation.observability import get_log

AgentEventSink = Callable[[AgentEvent], Awaitable[None] | None]
AgentEventStream = EventStream[AgentEvent, list[AgentMessage]]
log = get_log(__name__).bind(component="AgentLoop")
ExecutionResultT = TypeVar("ExecutionResultT")


class _ExecutionAborted(Exception):
    """An owned provider/tool execution child was cancelled by its run."""


def agent_loop(
    prompts: list[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    signal: object | None = None,
    stream_fn: StreamFn | None = None,
) -> AgentEventStream:
    stream = _create_agent_stream()

    async def _runner() -> None:
        try:
            await run_agent_loop(
                prompts,
                context,
                config,
                stream.push,
                signal=signal,
                stream_fn=stream_fn,
            )
        except Exception as error:
            stream.fail(
                error if isinstance(error, Exception) else RuntimeError(str(error))
            )

    asyncio.create_task(_runner())
    return stream


def agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    signal: object | None = None,
    stream_fn: StreamFn | None = None,
) -> EventStream[AgentEvent, list[AgentMessage]]:
    if not context.messages:
        raise ValueError("Cannot continue: no messages in context")

    if getattr(context.messages[-1], "role", None) == "assistant":
        raise ValueError("Cannot continue from message role: assistant")

    stream = _create_agent_stream()

    async def _runner() -> None:
        try:
            await run_agent_loop_continue(
                context,
                config,
                stream.push,
                signal=signal,
                stream_fn=stream_fn,
            )
        except Exception as error:
            stream.fail(
                error if isinstance(error, Exception) else RuntimeError(str(error))
            )

    asyncio.create_task(_runner())
    return stream


def _create_agent_stream() -> EventStream[AgentEvent, list[AgentMessage]]:
    return EventStream(
        is_terminal=lambda event: event["type"] == "agent_end",
        extract_result=lambda event: event["messages"],
    )


async def run_agent_loop(
    prompts: list[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    signal: object | None = None,
    stream_fn: StreamFn | None = None,
) -> list[AgentMessage]:
    new_messages: list[AgentMessage] = list(prompts)
    current_context = AgentContext(
        system_prompt=context.system_prompt,
        messages=[*context.messages, *prompts],
        tools=context.tools,
    )

    await _emit(emit, {"type": "agent_start"})
    await _emit(emit, {"type": "turn_start"})
    for prompt in prompts:
        await _emit(emit, {"type": "message_start", "message": prompt})
        await _emit(emit, {"type": "message_end", "message": prompt})

    await _run_loop(
        current_context, new_messages, config, emit, signal=signal, stream_fn=stream_fn
    )
    return new_messages


async def run_agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    signal: object | None = None,
    stream_fn: StreamFn | None = None,
) -> list[AgentMessage]:
    if not context.messages:
        raise ValueError("Cannot continue: no messages in context")

    if getattr(context.messages[-1], "role", None) == "assistant":
        raise ValueError("Cannot continue from message role: assistant")

    new_messages: list[AgentMessage] = []
    current_context = AgentContext(
        system_prompt=context.system_prompt,
        messages=[*context.messages],
        tools=context.tools,
    )

    await _emit(emit, {"type": "agent_start"})
    await _emit(emit, {"type": "turn_start"})
    await _run_loop(
        current_context, new_messages, config, emit, signal=signal, stream_fn=stream_fn
    )
    return new_messages


async def _run_loop(
    current_context: AgentContext,
    new_messages: list[AgentMessage],
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: object | None,
    stream_fn: StreamFn | None,
) -> None:
    first_turn = True
    pending_messages = await _poll_immediate_inputs(config)

    while True:
        has_more_tool_calls = True

        while has_more_tool_calls or pending_messages:
            if _is_aborted(signal):
                await _emit_aborted_turn(
                    current_context,
                    new_messages,
                    config,
                    emit,
                    error_message="Request aborted by user",
                )
                return

            if first_turn:
                first_turn = False
            else:
                await _emit(emit, {"type": "turn_start"})

            if pending_messages:
                for message in pending_messages:
                    await _emit(emit, {"type": "message_start", "message": message})
                    await _emit(emit, {"type": "message_end", "message": message})
                    current_context.messages.append(message)
                    new_messages.append(message)
                pending_messages = []

            if _is_aborted(signal):
                await _emit_aborted_turn(
                    current_context,
                    new_messages,
                    config,
                    emit,
                    error_message="Request aborted by user",
                )
                return

            try:
                assistant_message = await _stream_assistant_response(
                    current_context,
                    config,
                    emit,
                    signal=signal,
                    stream_fn=stream_fn,
                )
            except _ExecutionAborted:
                await _emit_aborted_turn(
                    current_context,
                    new_messages,
                    config,
                    emit,
                    error_message="Request aborted by user",
                )
                return
            except Exception as error:
                if not _is_user_abort_error(error, signal):
                    raise
                await _emit_aborted_turn(
                    current_context,
                    new_messages,
                    config,
                    emit,
                    error_message="Request aborted by user",
                )
                return
            new_messages.append(assistant_message)

            if assistant_message.stop_reason in {"error", "aborted"}:
                await _emit(
                    emit,
                    {
                        "type": "turn_end",
                        "message": assistant_message,
                        "tool_results": [],
                    },
                )
                await _emit(emit, {"type": "agent_end", "messages": new_messages})
                return
            if _is_aborted(signal):
                await _emit_aborted_turn(
                    current_context,
                    new_messages,
                    config,
                    emit,
                    error_message="Request aborted by user",
                )
                return

            tool_calls = [
                item for item in assistant_message.content if isinstance(item, ToolCall)
            ]
            has_more_tool_calls = len(tool_calls) > 0

            tool_results: list[ToolResultMessage] = []
            terminate_after_tool_batch = False
            if has_more_tool_calls:
                if _is_aborted(signal):
                    tool_results.extend(
                        await _emit_aborted_tool_results(tool_calls, (), emit)
                    )
                    _append_tool_results(
                        current_context,
                        new_messages,
                        tool_results,
                    )
                    await _emit_tool_turn_end(
                        emit,
                        assistant_message,
                        tool_results,
                    )
                    await _emit_aborted_turn(
                        current_context,
                        new_messages,
                        config,
                        emit,
                        error_message="Request aborted by user",
                    )
                    return
                finalized_tool_results: list[ToolResultMessage] = []
                try:
                    executed_tool_batch = await _execute_tool_calls(
                        current_context,
                        assistant_message,
                        config,
                        emit,
                        signal=signal,
                        finalized_messages=finalized_tool_results,
                    )
                except _ExecutionAborted:
                    tool_results.extend(finalized_tool_results)
                    tool_results.extend(
                        await _emit_aborted_tool_results(
                            tool_calls,
                            tool_results,
                            emit,
                        )
                    )
                    _append_tool_results(
                        current_context,
                        new_messages,
                        tool_results,
                    )
                    await _emit_tool_turn_end(
                        emit,
                        assistant_message,
                        tool_results,
                    )
                    await _emit_aborted_turn(
                        current_context,
                        new_messages,
                        config,
                        emit,
                        error_message="Request aborted by user",
                    )
                    return
                except asyncio.CancelledError:
                    tool_results.extend(finalized_tool_results)
                    tool_results.extend(
                        await _emit_aborted_tool_results(
                            tool_calls,
                            tool_results,
                            emit,
                        )
                    )
                    _append_tool_results(
                        current_context,
                        new_messages,
                        tool_results,
                    )
                    await _emit_tool_turn_end(
                        emit,
                        assistant_message,
                        tool_results,
                    )
                    raise
                tool_results.extend(finalized_tool_results)
                terminate_after_tool_batch = executed_tool_batch.terminate
                if _is_aborted(signal):
                    tool_results.extend(
                        await _emit_aborted_tool_results(
                            tool_calls,
                            tool_results,
                            emit,
                        )
                    )
                    _append_tool_results(
                        current_context,
                        new_messages,
                        tool_results,
                    )
                    await _emit_tool_turn_end(
                        emit,
                        assistant_message,
                        tool_results,
                    )
                    await _emit_aborted_turn(
                        current_context,
                        new_messages,
                        config,
                        emit,
                        error_message="Request aborted by user",
                    )
                    return
                _append_tool_results(
                    current_context,
                    new_messages,
                    tool_results,
                )

            await _emit_tool_turn_end(emit, assistant_message, tool_results)
            if terminate_after_tool_batch:
                await _emit(emit, {"type": "agent_end", "messages": new_messages})
                return
            pending_messages = await _poll_immediate_inputs(config)

        mailbox_messages = await _maybe_call(config.get_mailbox_messages, default=[])
        if mailbox_messages:
            pending_messages = mailbox_messages
            continue
        follow_up_messages = await _maybe_call(
            config.get_follow_up_messages, default=[]
        )
        if follow_up_messages:
            pending_messages = follow_up_messages
            continue

        break

    await _emit(emit, {"type": "agent_end", "messages": new_messages})


async def _poll_immediate_inputs(config: AgentLoopConfig) -> list[AgentMessage]:
    """Drain system mailbox before user steering at each sampling boundary."""

    mailbox = await _maybe_call(config.get_mailbox_messages, default=[])
    steering = await _maybe_call(config.get_steering_messages, default=[])
    return [*mailbox, *steering]


async def _stream_assistant_response(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: object | None,
    stream_fn: StreamFn | None,
) -> AssistantMessage:
    if _is_aborted(signal):
        raise RuntimeError("Request aborted by user")

    final_message, added_partial = await _run_execution(
        _collect_assistant_response(
            context,
            config,
            emit,
            signal=signal,
            stream_fn=stream_fn,
        ),
        signal,
    )
    if added_partial:
        context.messages[-1] = final_message
    else:
        context.messages.append(final_message)
        await _emit(emit, {"type": "message_start", "message": final_message})
    await _emit(emit, {"type": "message_end", "message": final_message})
    return final_message


async def _collect_assistant_response(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: object | None,
    stream_fn: StreamFn | None,
) -> tuple[AssistantMessage, bool]:
    """Collect provider output without owning its durable message boundary."""

    messages = context.messages
    if config.transform_context is not None:
        messages = await config.transform_context(messages, signal)

    llm_messages = await _resolve(config.convert_to_llm(messages))
    llm_context = Context(
        system_prompt=context.system_prompt,
        messages=llm_messages,
        tools=_project_tools_for_llm(context.tools),
    )

    call_stream = stream_fn or stream
    options = replace(
        config.call_options,
        cancellation=signal if signal is not None else config.call_options.cancellation,
    )

    if _is_aborted(signal):
        raise RuntimeError("Request aborted by user")

    try:
        response = await _resolve(call_stream(config.model, llm_context, options))
    except Exception as error:
        _report_provider_problem(
            "provider_request_failed",
            config.model,
            message=str(error) or error.__class__.__name__,
            exc=error,
        )
        raise

    partial_message: AssistantMessage | None = None
    added_partial = False

    try:
        async for event in response:
            if _is_aborted(signal):
                raise RuntimeError("Request aborted by user")
            event_type = event["type"]
            if event_type == "start":
                partial_message = event["partial"]
                context.messages.append(partial_message)
                added_partial = True
                await _emit(emit, {"type": "message_start", "message": partial_message})
                continue

            if event_type in {
                "text_start",
                "text_delta",
                "text_end",
                "thinking_start",
                "thinking_delta",
                "thinking_end",
                "toolcall_start",
                "toolcall_delta",
                "toolcall_end",
            }:
                partial_message = event["partial"]
                if added_partial:
                    context.messages[-1] = partial_message
                await _emit(
                    emit,
                    {
                        "type": "message_update",
                        "message": partial_message,
                        "assistant_message_event": event,
                    },
                )
                continue

            if event_type in {"done", "error"}:
                final_message = await response.result()
                return final_message, added_partial

        final_message = await response.result()
    except Exception as error:
        if _is_user_abort_error(error, signal):
            raise
        _report_provider_problem(
            "provider_request_failed",
            config.model,
            message=str(error) or error.__class__.__name__,
            exc=error,
        )
        raise

    return final_message, added_partial


async def _execute_tool_calls(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: object | None,
    finalized_messages: list[ToolResultMessage],
) -> "_ToolCallBatchOutcome":
    if _is_aborted(signal):
        return _ToolCallBatchOutcome(messages=[], terminate=True)
    tool_calls = [
        item for item in assistant_message.content if isinstance(item, ToolCall)
    ]
    if config.tool_execution == "sequential" or _has_sequential_tool_call(
        current_context, tool_calls
    ):
        return await _execute_tool_calls_sequential(
            current_context,
            assistant_message,
            tool_calls,
            config,
            emit,
            signal=signal,
            finalized_messages=finalized_messages,
        )
    return await _execute_tool_calls_parallel(
        current_context,
        assistant_message,
        tool_calls,
        config,
        emit,
        signal=signal,
        finalized_messages=finalized_messages,
    )


def _append_tool_results(
    current_context: AgentContext,
    new_messages: list[AgentMessage],
    tool_results: list[ToolResultMessage],
) -> None:
    for result in tool_results:
        current_context.messages.append(result)
        new_messages.append(result)


async def _emit_tool_turn_end(
    emit: AgentEventSink,
    assistant_message: AssistantMessage,
    tool_results: list[ToolResultMessage],
) -> None:
    await _emit(
        emit,
        {
            "type": "turn_end",
            "message": assistant_message,
            "tool_results": tool_results,
        },
    )


async def _emit_aborted_tool_results(
    tool_calls: list[AgentToolCall],
    finalized_messages: Sequence[ToolResultMessage],
    emit: AgentEventSink,
) -> list[ToolResultMessage]:
    finalized_ids = {message.tool_call_id for message in finalized_messages}
    aborted: list[ToolResultMessage] = []
    for tool_call in tool_calls:
        if tool_call.id in finalized_ids:
            continue
        outcome = await _emit_tool_call_outcome(
            tool_call,
            AgentToolResult(
                content=[
                    TextPart(
                        type="text",
                        text="Tool call aborted before completion.",
                    )
                ],
                details={"code": "tool_call_aborted"},
            ),
            True,
            emit,
        )
        aborted.append(outcome.message)
    return aborted


@dataclass
class _ToolCallBatchOutcome:
    messages: list[ToolResultMessage]
    terminate: bool


@dataclass
class _FinalizedToolCallOutcome:
    message: ToolResultMessage
    terminate: bool


def _has_sequential_tool_call(
    current_context: AgentContext, tool_calls: list[AgentToolCall]
) -> bool:
    for tool_call in tool_calls:
        tool = _find_tool(current_context, tool_call.name)
        if tool is not None and tool.execution_mode == "sequential":
            return True
    return False


async def _execute_tool_calls_sequential(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[AgentToolCall],
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: object | None,
    finalized_messages: list[ToolResultMessage],
) -> _ToolCallBatchOutcome:
    finalized_results: list[_FinalizedToolCallOutcome] = []
    for tool_call in tool_calls:
        if _is_aborted(signal):
            return _ToolCallBatchOutcome(messages=[], terminate=True)
        await _emit(
            emit,
            {
                "type": "tool_execution_start",
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.name,
                "args": tool_call.arguments,
            },
        )
        preparation = await _prepare_tool_call(
            current_context, assistant_message, tool_call, config, signal=signal
        )
        if _is_aborted(signal):
            return _ToolCallBatchOutcome(messages=[], terminate=True)
        if preparation.kind == "immediate":
            finalized = await _emit_tool_call_outcome(
                preparation.tool_call,
                preparation.result,
                preparation.is_error,
                emit,
            )
            finalized_results.append(finalized)
            finalized_messages.append(finalized.message)
            continue
        execution = _create_execution_task(
            _execute_prepared_tool_call(preparation, emit, signal=signal), signal
        )
        executed = await _await_execution_task(execution, signal)
        if _is_aborted(signal) and not executed.completed_before_abort:
            return _ToolCallBatchOutcome(messages=[], terminate=True)
        finalized = await _finalize_executed_tool_call(
            current_context,
            assistant_message,
            preparation,
            executed,
            config,
            emit,
            signal=signal,
        )
        finalized_results.append(finalized)
        finalized_messages.append(finalized.message)
    return _ToolCallBatchOutcome(
        messages=[result.message for result in finalized_results],
        terminate=_should_terminate_after_tool_batch(finalized_results),
    )


async def _execute_tool_calls_parallel(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[AgentToolCall],
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: object | None,
    finalized_messages: list[ToolResultMessage],
) -> _ToolCallBatchOutcome:
    finalized_results: list[_FinalizedToolCallOutcome] = []
    runnable_calls: list[_PreparedToolCall] = []

    for tool_call in tool_calls:
        if _is_aborted(signal):
            return _ToolCallBatchOutcome(messages=[], terminate=True)
        await _emit(
            emit,
            {
                "type": "tool_execution_start",
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.name,
                "args": tool_call.arguments,
            },
        )
        preparation = await _prepare_tool_call(
            current_context, assistant_message, tool_call, config, signal=signal
        )
        if _is_aborted(signal):
            return _ToolCallBatchOutcome(messages=[], terminate=True)
        if preparation.kind == "immediate":
            finalized = await _emit_tool_call_outcome(
                preparation.tool_call,
                preparation.result,
                preparation.is_error,
                emit,
            )
            finalized_results.append(finalized)
            finalized_messages.append(finalized.message)
        else:
            runnable_calls.append(preparation)

    running_calls = [
        (
            prepared,
            _create_execution_task(
                _execute_prepared_tool_call(prepared, emit, signal=signal),
                signal,
            ),
        )
        for prepared in runnable_calls
    ]
    try:
        for prepared, execution in running_calls:
            executed = await _await_execution_task(execution, signal)
            if _is_aborted(signal):
                await _finalize_completed_tool_tasks(
                    current_context,
                    assistant_message,
                    running_calls,
                    finalized_results,
                    finalized_messages,
                    config,
                    emit,
                    signal=signal,
                )
                return _ToolCallBatchOutcome(
                    messages=list(finalized_messages),
                    terminate=True,
                )
            finalized = await _finalize_executed_tool_call(
                current_context,
                assistant_message,
                prepared,
                executed,
                config,
                emit,
                signal=signal,
            )
            finalized_results.append(finalized)
            finalized_messages.append(finalized.message)
    except _ExecutionAborted:
        await _finalize_completed_tool_tasks(
            current_context,
            assistant_message,
            running_calls,
            finalized_results,
            finalized_messages,
            config,
            emit,
            signal=signal,
        )
        return _ToolCallBatchOutcome(
            messages=list(finalized_messages),
            terminate=True,
        )
    except asyncio.CancelledError:
        await _cancel_pending_tool_tasks(running_calls)
        raise
    return _ToolCallBatchOutcome(
        messages=[result.message for result in finalized_results],
        terminate=_should_terminate_after_tool_batch(finalized_results),
    )


def _should_terminate_after_tool_batch(
    results: list[_FinalizedToolCallOutcome],
) -> bool:
    return bool(results) and all(result.terminate for result in results)


async def _emit_aborted_turn(
    current_context: AgentContext,
    new_messages: list[AgentMessage],
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    error_message: str,
) -> None:
    message = _create_aborted_assistant_message(config, error_message=error_message)
    current_context.messages.append(message)
    new_messages.append(message)
    await _emit(emit, {"type": "message_start", "message": message})
    await _emit(emit, {"type": "message_end", "message": message})
    await _emit(emit, {"type": "turn_end", "message": message, "tool_results": []})
    await _emit(emit, {"type": "agent_end", "messages": new_messages})


def _create_aborted_assistant_message(
    config: AgentLoopConfig, *, error_message: str
) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="")],
        api=config.model.endpoint_id,
        provider=config.model.provider_id,
        endpoint=config.model.endpoint_id,
        model=config.model.id,
        response_id=None,
        usage=_empty_usage(),
        stop_reason="aborted",
        error_message=error_message,
        timestamp=time.time() * 1000,
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


async def _cancel_pending_tool_tasks(
    running_calls: list[
        tuple["_PreparedToolCall", asyncio.Task["_ExecutedToolCallOutcome"]]
    ],
) -> None:
    tasks = [task for _prepared, task in running_calls]
    pending = [task for task in tasks if not task.done()]
    for task in pending:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _finalize_completed_tool_tasks(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    running_calls: list[
        tuple["_PreparedToolCall", asyncio.Task["_ExecutedToolCallOutcome"]]
    ],
    finalized_results: list[_FinalizedToolCallOutcome],
    finalized_messages: list[ToolResultMessage],
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: object | None,
) -> None:
    tasks = [task for _prepared, task in running_calls]
    for task in tasks:
        if not task.done():
            task.cancel()
    drained = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
    finalized_ids = {message.tool_call_id for message in finalized_messages}
    for (prepared, _task), executed in zip(running_calls, drained, strict=True):
        if prepared.tool_call.id in finalized_ids:
            continue
        if not isinstance(executed, _ExecutedToolCallOutcome):
            continue
        if _is_aborted(signal) and not executed.completed_before_abort:
            continue
        finalized = await _finalize_executed_tool_call(
            current_context,
            assistant_message,
            prepared,
            executed,
            config,
            emit,
            signal=signal,
        )
        finalized_results.append(finalized)
        finalized_messages.append(finalized.message)
        finalized_ids.add(finalized.message.tool_call_id)


def _create_execution_task(
    operation: Coroutine[Any, Any, ExecutionResultT],
    signal: object | None,
) -> asyncio.Task[ExecutionResultT]:
    task = asyncio.create_task(operation)
    register = getattr(signal, "_register_execution_task", None)
    if callable(register):
        register(task)
    elif _is_aborted(signal):
        task.cancel()
    return task


async def _await_execution_task(
    task: asyncio.Task[ExecutionResultT],
    signal: object | None,
) -> ExecutionResultT:
    try:
        return await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        coordinator_cancelled = bool(current is not None and current.cancelling())
        if _is_aborted(signal) and task.cancelled() and not coordinator_cancelled:
            raise _ExecutionAborted from None
        raise
    finally:
        unregister = getattr(signal, "_unregister_execution_task", None)
        if callable(unregister):
            unregister(task)


async def _run_execution(
    operation: Coroutine[Any, Any, ExecutionResultT],
    signal: object | None,
) -> ExecutionResultT:
    return await _await_execution_task(
        _create_execution_task(operation, signal),
        signal,
    )


def _is_aborted(signal: object | None) -> bool:
    return bool(signal is not None and getattr(signal, "aborted", False))


def _report_tool_problem(
    code: str,
    tool_call: AgentToolCall,
    *,
    message: str,
    exc: BaseException | None = None,
    recoverable: bool = True,
    details: Mapping[str, object] | None = None,
) -> None:
    problem_details: dict[str, object] = {
        "tool_call_id": tool_call.id,
        "tool_name": tool_call.name,
    }
    if exc is not None:
        problem_details["error_type"] = type(exc).__name__
    if details is not None:
        problem_details.update(details)
    log.problem(
        code,
        source="tool",
        message=message,
        recoverable=recoverable,
        exc=exc,
        details=problem_details,
    )


def _report_provider_problem(
    code: str,
    model: Any,
    *,
    message: str,
    exc: BaseException,
    recoverable: bool = True,
) -> None:
    log.problem(
        code,
        source="provider",
        message=message,
        recoverable=recoverable,
        exc=exc,
        details={
            "provider_id": _safe_model_attr(model, "provider_id"),
            "endpoint_id": _safe_model_attr(model, "endpoint_id"),
            "model_id": _safe_model_attr(model, "id"),
        },
    )


def _safe_model_attr(model: Any, name: str) -> str:
    try:
        value = getattr(model, name)
    except Exception:
        return ""
    return value if isinstance(value, str) else str(value)


def _is_user_abort_error(error: BaseException, signal: object | None) -> bool:
    return _is_aborted(signal) and str(error) == "Request aborted by user"


@dataclass
class _PreparedToolCall:
    kind: str
    tool_call: AgentToolCall
    tool: AgentTool[Any]
    args: Any


@dataclass
class _ImmediateToolCallOutcome:
    kind: str
    tool_call: AgentToolCall
    result: AgentToolResult[Any]
    is_error: bool


@dataclass
class _ExecutedToolCallOutcome:
    result: AgentToolResult[Any]
    is_error: bool
    duration_ms: int
    completed_before_abort: bool


async def _prepare_tool_call(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_call: AgentToolCall,
    config: AgentLoopConfig,
    *,
    signal: object | None,
) -> _PreparedToolCall | _ImmediateToolCallOutcome:
    tool = _find_tool(current_context, tool_call.name)
    if tool is None:
        _report_tool_problem(
            "tool_not_found",
            tool_call,
            message=f"Tool {tool_call.name} not found",
        )
        return _ImmediateToolCallOutcome(
            kind="immediate",
            tool_call=tool_call,
            result=_create_error_tool_result(f"Tool {tool_call.name} not found"),
            is_error=True,
        )

    problem_reported = False

    def report_once(
        code: str, reported_tool_call: AgentToolCall, error: BaseException
    ) -> None:
        nonlocal problem_reported
        _report_tool_problem(
            code,
            reported_tool_call,
            message=str(error) or error.__class__.__name__,
            exc=error,
        )
        problem_reported = True

    try:
        prepared_arguments = (
            tool.prepare_arguments(tool_call.arguments)
            if getattr(tool, "prepare_arguments", None)
            else tool_call.arguments
        )
        validation_tool_call = (
            tool_call
            if prepared_arguments is tool_call.arguments
            else ToolCall(
                type="toolCall",
                id=tool_call.id,
                name=tool_call.name,
                arguments=prepared_arguments,
                thought_signature=tool_call.thought_signature,
            )
        )
        event_tool_call = tool_call
        try:
            validated_args = validate_tool_arguments(
                _project_tool_for_llm(tool), validation_tool_call
            )
        except Exception as error:
            report_once("tool_validation_failed", validation_tool_call, error)
            raise
        if config.before_tool_call is not None:
            before_result = await config.before_tool_call(
                BeforeToolCallContext(
                    assistant_message=assistant_message,
                    tool_call=tool_call,
                    args=validated_args,
                    context=current_context,
                ),
                signal,
            )
            if before_result is not None:
                rewritten_tool_name = (
                    before_result.tool_name or validation_tool_call.name
                )
                rewritten_arguments = (
                    before_result.arguments
                    if before_result.arguments is not None
                    else validated_args
                )
                if (
                    rewritten_tool_name != validation_tool_call.name
                    or rewritten_arguments != validated_args
                ):
                    rewritten_tool = _find_tool(current_context, rewritten_tool_name)
                    if rewritten_tool is None:
                        rewritten_call = ToolCall(
                            type="toolCall",
                            id=validation_tool_call.id,
                            name=rewritten_tool_name,
                            arguments=rewritten_arguments,
                            thought_signature=validation_tool_call.thought_signature,
                        )
                        _report_tool_problem(
                            "tool_not_found",
                            rewritten_call,
                            message=f"Tool {rewritten_tool_name} not found",
                        )
                        return _ImmediateToolCallOutcome(
                            kind="immediate",
                            tool_call=rewritten_call,
                            result=_create_error_tool_result(
                                f"Tool {rewritten_tool_name} not found"
                            ),
                            is_error=True,
                        )
                    rewritten_prepared_arguments = (
                        rewritten_tool.prepare_arguments(rewritten_arguments)
                        if getattr(rewritten_tool, "prepare_arguments", None)
                        else rewritten_arguments
                    )
                    validation_tool_call = ToolCall(
                        type="toolCall",
                        id=validation_tool_call.id,
                        name=rewritten_tool_name,
                        arguments=rewritten_prepared_arguments,
                        thought_signature=validation_tool_call.thought_signature,
                    )
                    event_tool_call = ToolCall(
                        type="toolCall",
                        id=event_tool_call.id,
                        name=rewritten_tool_name,
                        arguments=rewritten_arguments,
                        thought_signature=event_tool_call.thought_signature,
                    )
                    tool = rewritten_tool
                    try:
                        validated_args = validate_tool_arguments(
                            _project_tool_for_llm(tool), validation_tool_call
                        )
                    except Exception as error:
                        report_once(
                            "tool_validation_failed", validation_tool_call, error
                        )
                        raise
                if before_result.block:
                    return _ImmediateToolCallOutcome(
                        kind="immediate",
                        tool_call=event_tool_call,
                        result=_create_error_tool_result(
                            before_result.reason or "Tool execution was blocked"
                        ),
                        is_error=True,
                    )
        return _PreparedToolCall(
            kind="prepared", tool_call=event_tool_call, tool=tool, args=validated_args
        )
    except Exception as error:
        if not problem_reported:
            _report_tool_problem(
                "tool_preparation_failed",
                tool_call,
                message=str(error) or error.__class__.__name__,
                exc=error,
            )
        return _ImmediateToolCallOutcome(
            kind="immediate",
            tool_call=tool_call,
            result=_create_error_tool_result(str(error), error),
            is_error=True,
        )


async def _execute_prepared_tool_call(
    prepared: _PreparedToolCall,
    emit: AgentEventSink,
    *,
    signal: object | None,
) -> _ExecutedToolCallOutcome:
    started_at = time.perf_counter()
    try:
        update_events: list[asyncio.Task[None]] = []

        def on_update(partial_result: AgentToolResult[Any]) -> asyncio.Task[None]:
            try:
                event_result = partial_result.for_event()
            except Exception as error:
                projection_error = _as_projection_error(error, target="event")
                _report_projection_problem(
                    "tool_output_update_projection_failed",
                    prepared.tool_call,
                    projection_error,
                    result=partial_result,
                )
                update_event = asyncio.create_task(_discard_tool_update())
            else:
                update_event = asyncio.create_task(
                    _emit_projected_tool_update(
                        emit,
                        prepared.tool_call,
                        event_result,
                    )
                )
            update_events.append(update_event)
            return update_event

        result = await prepared.tool.execute(
            prepared.tool_call.id,
            prepared.args,
            signal,
            on_update,
        )
        for update in update_events:
            await update
        return _ExecutedToolCallOutcome(
            result=result,
            is_error=False,
            duration_ms=_elapsed_ms(started_at),
            completed_before_abort=not _is_aborted(signal),
        )
    except Exception as error:
        duration_ms = _elapsed_ms(started_at)
        _report_tool_problem(
            "tool_execution_failed",
            prepared.tool_call,
            message=str(error) or error.__class__.__name__,
            exc=error,
            details={"duration_ms": duration_ms},
        )
        return _ExecutedToolCallOutcome(
            result=_create_error_tool_result(str(error), error),
            is_error=True,
            duration_ms=duration_ms,
            completed_before_abort=not _is_aborted(signal),
        )


async def _finalize_executed_tool_call(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    prepared: _PreparedToolCall,
    executed: _ExecutedToolCallOutcome,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    *,
    signal: object | None,
) -> _FinalizedToolCallOutcome:
    result = executed.result
    is_error = executed.is_error

    if config.after_tool_call is not None:
        result, is_error, hook_details = _prepare_hook_projection(
            prepared.tool_call,
            result,
            is_error,
        )
        projection_result = result
        try:
            after_result = await config.after_tool_call(
                AfterToolCallContext(
                    assistant_message=assistant_message,
                    tool_call=prepared.tool_call,
                    args=prepared.args,
                    result=result,
                    is_error=is_error,
                    context=current_context,
                    hook_details=hook_details,
                ),
                signal,
            )
            if after_result is not None:
                details_provided = after_result.details_provided
                candidate = AgentToolResult(
                    content=after_result.content
                    if after_result.content is not None
                    else result.content,
                    details=after_result.details
                    if details_provided
                    else result.details,
                    terminate=after_result.terminate
                    if after_result.terminate is not None
                    else result.terminate,
                    projector=(
                        after_result.projector
                        if after_result.projector is not None
                        else (
                            result.projector
                            if not details_provided
                            else STRICT_JSON_TOOL_OUTPUT_PROJECTOR
                        )
                    ),
                )
                projection_result = candidate
                if details_provided or after_result.projector is not None:
                    candidate.hook_details()
                result = candidate
                if after_result.is_error is not None:
                    is_error = after_result.is_error
        except ToolOutputProjectionError as error:
            _report_projection_problem(
                "tool_output_projection_failed",
                prepared.tool_call,
                error,
                result=projection_result,
            )
            result = _projection_error_tool_result(
                error,
                terminate=projection_result.terminate,
            )
            is_error = True
        except Exception as error:
            _report_tool_problem(
                "tool_after_hook_failed",
                prepared.tool_call,
                message=str(error) or error.__class__.__name__,
                exc=error,
            )
            result = _create_error_tool_result(
                str(error),
                error,
                terminate=result.terminate,
            )
            is_error = True

    return await _emit_tool_call_outcome(
        prepared.tool_call,
        result,
        is_error,
        emit,
        duration_ms=executed.duration_ms,
    )


def _create_error_tool_result(
    message: str,
    error: BaseException | None = None,
    *,
    terminate: object = False,
) -> AgentToolResult[Any]:
    return AgentToolResult(
        content=[TextPart(type="text", text=message)],
        details=_error_tool_result_details(error),
        terminate=_safe_tool_result_terminate(terminate),
    )


async def _emit_projected_tool_update(
    emit: AgentEventSink,
    tool_call: AgentToolCall,
    partial_result: AgentToolResult[Any],
) -> None:
    await _emit(
        emit,
        {
            "type": "tool_execution_update",
            "tool_call_id": tool_call.id,
            "tool_name": tool_call.name,
            "args": tool_call.arguments,
            "partial_result": partial_result,
        },
    )


async def _discard_tool_update() -> None:
    return None


def _prepare_hook_projection(
    tool_call: AgentToolCall,
    result: AgentToolResult[Any],
    is_error: bool,
) -> tuple[AgentToolResult[Any], bool, JSONValue]:
    try:
        return result, is_error, result.hook_details()
    except Exception as error:
        projection_error = _as_projection_error(error, target="hook")
        _report_projection_problem(
            "tool_output_projection_failed",
            tool_call,
            projection_error,
            result=result,
        )
        replacement = _projection_error_tool_result(
            projection_error,
            terminate=result.terminate,
        )
        return replacement, True, replacement.hook_details()


def _ensure_final_tool_output_projections(
    tool_call: AgentToolCall,
    result: AgentToolResult[Any],
    is_error: bool,
) -> tuple[
    AgentToolResult[Any],
    AgentToolResult[Any],
    AgentToolResult[JSONValue],
    bool,
]:
    if type(is_error) is not bool:
        projection_error = ToolOutputProjectionError(
            "event",
            "Tool output is_error must be a boolean",
            path="tool_output.is_error",
            value_type=type(is_error).__name__,
        )
        _report_projection_problem(
            "tool_output_projection_failed",
            tool_call,
            projection_error,
            result=result,
        )
        replacement = _projection_error_tool_result(
            projection_error,
            terminate=result.terminate,
        )
        return (
            replacement,
            replacement.for_event(),
            replacement.for_presentation(),
            True,
        )
    projections: dict[str, AgentToolResult[JSONValue]] = {}
    for target, project in (
        ("transcript", result.for_presentation),
        ("event", result.for_event),
    ):
        try:
            projections[target] = project()
        except Exception as error:
            projection_error = _as_projection_error(error, target=target)
            _report_projection_problem(
                "tool_output_projection_failed",
                tool_call,
                projection_error,
                result=result,
            )
            replacement = _projection_error_tool_result(
                projection_error,
                terminate=result.terminate,
            )
            return (
                replacement,
                replacement.for_event(),
                replacement.for_presentation(),
                True,
            )
    return result, projections["event"], projections["transcript"], is_error


def _as_projection_error(
    error: Exception,
    *,
    target: str,
) -> ToolOutputProjectionError:
    if isinstance(error, ToolOutputProjectionError):
        return ToolOutputProjectionError(
            error.target,
            str(error),
            path=error.path,
            value_type=error.value_type,
        )
    return ToolOutputProjectionError(
        target,
        f"Tool output {target} projection raised {type(error).__name__}",
        path="tool_output.details",
        value_type=type(error).__name__,
    )


def _report_projection_problem(
    code: str,
    tool_call: AgentToolCall,
    error: ToolOutputProjectionError,
    *,
    result: AgentToolResult[Any],
) -> None:
    details: dict[str, object] = {
        "projection_target": error.target,
        "projection_path": error.path,
        "value_type": error.value_type,
    }
    with suppress(Exception):
        details["projection_preview"] = result.log_preview()
    _report_tool_problem(
        code,
        tool_call,
        message=str(error),
        exc=error,
        details=details,
    )


def _projection_error_tool_result(
    error: ToolOutputProjectionError,
    *,
    terminate: object = False,
) -> AgentToolResult[dict[str, JSONValue]]:
    return AgentToolResult(
        content=[
            TextPart(
                type="text",
                text=(
                    "Tool output could not be projected to "
                    f"{error.target} JSON at {error.path}."
                ),
            )
        ],
        details={
            "code": "tool_output_projection_failed",
            "target": error.target,
            "path": error.path,
            "valueType": error.value_type,
        },
        terminate=_safe_tool_result_terminate(terminate),
    )


def _safe_tool_result_terminate(value: object) -> bool:
    return value if type(value) is bool else False


def _error_tool_result_details(error: BaseException | None) -> dict[str, Any]:
    if error is None:
        return {}
    details = getattr(error, "tool_result_details", None)
    if isinstance(details, Mapping):
        return dict(details)
    return {}


async def _emit_tool_call_outcome(
    tool_call: AgentToolCall,
    result: AgentToolResult[Any],
    is_error: bool,
    emit: AgentEventSink,
    *,
    duration_ms: int | None = None,
) -> _FinalizedToolCallOutcome:
    result, event_result, presentation_result, is_error = (
        _ensure_final_tool_output_projections(
            tool_call,
            result,
            is_error,
        )
    )
    event: dict[str, Any] = {
        "type": "tool_execution_end",
        "tool_call_id": tool_call.id,
        "tool_name": tool_call.name,
        "result": event_result,
        "is_error": is_error,
    }
    if duration_ms is not None:
        event["duration_ms"] = duration_ms
    tool_result_message = ToolResultMessage(
        role="toolResult",
        tool_call_id=tool_call.id,
        tool_name=tool_call.name,
        content=presentation_result.content,
        details=presentation_result.details,
        is_error=is_error,
        timestamp=time.time() * 1000,
        terminate=result.terminate,
    )
    await _emit(
        emit,
        event,
    )
    await _emit(emit, {"type": "message_start", "message": tool_result_message})
    await _emit(emit, {"type": "message_end", "message": tool_result_message})
    return _FinalizedToolCallOutcome(
        message=tool_result_message, terminate=result.terminate
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _find_tool(current_context: AgentContext, tool_name: str) -> AgentTool[Any] | None:
    return next(
        (
            candidate
            for candidate in current_context.tools or []
            if candidate.name == tool_name
        ),
        None,
    )


async def _emit(emit: AgentEventSink, event: AgentEvent) -> None:
    result = emit(event)
    if inspect.isawaitable(result):
        await result


async def _resolve(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _project_tool_for_llm(tool: AgentTool[Any]) -> Tool:
    return Tool(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters,
    )


def _project_tools_for_llm(tools: list[AgentTool[Any]] | None) -> list[Tool] | None:
    if tools is None:
        return None
    return [_project_tool_for_llm(tool) for tool in tools]


async def _maybe_call(fn, *, default):
    if fn is None:
        return default
    return await _resolve(fn())


__all__ = [
    "agent_loop",
    "agent_loop_continue",
    "run_agent_loop",
    "run_agent_loop_continue",
]
