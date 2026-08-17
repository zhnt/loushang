from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loushang.harness.events import RuntimeEvent
from loushang.harness.scenario.assertions import (
    evaluate_expectations,
    evaluate_workflow_expectations,
)
from loushang.harness.scenario.events import EventPattern, WorkflowEvent, find_event
from loushang.harness.scenario.protocols import CommandRunner, WorkflowAdapter
from loushang.harness.scenario.schema import (
    AbortStep,
    CheckResult,
    ExpectStep,
    FollowUpStep,
    PromptStep,
    SteerStep,
    WaitForStep,
    WaitStep,
    Workflow,
    WorkflowResult,
    WorkflowStep,
    WorkflowStepResult,
)


class AgentSessionWorkflowAdapter:
    def __init__(self, session: Any) -> None:
        self.session = session
        self._events: list[WorkflowEvent] = []
        self._condition = asyncio.Condition()
        self._active_prompt_task: asyncio.Task[str] | None = None
        self._abort_requested = False
        subscribe_runtime_events = getattr(session, "subscribe_runtime_events", None)
        if callable(subscribe_runtime_events):
            self._unsubscribe = subscribe_runtime_events(self._record_runtime_event)
        else:
            subscribe = getattr(session, "subscribe", None)
            self._unsubscribe = (
                subscribe(self._record_session_event) if callable(subscribe) else None
            )

    async def prompt(self, prompt: str, *, hold: bool = False) -> str:
        if hold:
            if self._active_prompt_task is not None:
                raise RuntimeError("workflow prompt is already active")
            await self._emit(WorkflowEvent(type="run.started", text=prompt))
            self._abort_requested = False
            self._active_prompt_task = asyncio.create_task(
                self._run_held_prompt(prompt)
            )
            return ""
        return await self.run_prompt(prompt)

    async def run_prompt(self, prompt: str) -> str:
        return await self._run_session_prompt(prompt, emit_start=True)

    async def _run_session_prompt(self, prompt: str, *, emit_start: bool) -> str:
        before_count = len(_session_messages(self.session))
        before_event_count = len(self._events)
        if emit_start:
            await self._emit(WorkflowEvent(type="run.started", text=prompt))
        await self.session.prompt(prompt)
        assistant_text = _assistant_text_after(self.session, before_count=before_count)
        if assistant_text and not _has_assistant_message_event(
            self._events[before_event_count:]
        ):
            await self._emit(
                WorkflowEvent(type="assistant.message", text=assistant_text)
            )
        if not self._abort_requested:
            await self._emit(WorkflowEvent(type="run.ended", text=prompt))
        return assistant_text

    async def steer(self, text: str) -> None:
        await self._queue_text(text, action="steer", event_type="queue.steer_added")

    async def follow_up(self, text: str) -> None:
        await self._queue_text(
            text, action="follow_up", event_type="queue.follow_up_added"
        )

    async def abort(self) -> None:
        self._abort_requested = True
        abort = getattr(self.session, "abort", None)
        if callable(abort):
            result = abort()
            if inspect.isawaitable(result):
                await result
        clear_queue = getattr(self.session, "clear_queue", None)
        if callable(clear_queue):
            result = clear_queue()
            if inspect.isawaitable(result):
                await result
        if self._active_prompt_task is not None:
            await self._active_prompt_task

    async def wait_for(self, pattern: EventPattern, timeout_s: float) -> WorkflowEvent:
        existing = find_event(self.events(), pattern)
        if existing is not None:
            return existing

        async def wait_until_found() -> WorkflowEvent:
            async with self._condition:
                while True:
                    matched = find_event(self.events(), pattern)
                    if matched is not None:
                        return matched
                    await self._condition.wait()

        return await asyncio.wait_for(wait_until_found(), timeout=timeout_s)

    def events(self) -> tuple[WorkflowEvent, ...]:
        return tuple(self._events)

    def queue_state(self) -> object:
        return SimpleNamespace(
            steering=tuple(_call_text_list(self.session, "get_steering_messages")),
            follow_up=tuple(_call_text_list(self.session, "get_follow_up_messages")),
        )

    def session_state(self) -> object:
        getter = getattr(self.session, "get_session_state", None)
        if callable(getter):
            return getter()
        steering = tuple(_call_text_list(self.session, "get_steering_messages"))
        follow_up = tuple(_call_text_list(self.session, "get_follow_up_messages"))
        return {
            "queue": {
                "steering": steering,
                "followUp": follow_up,
            },
            "pendingMessageCount": len(steering) + len(follow_up),
        }

    def session_stats(self) -> object:
        getter = getattr(self.session, "get_session_stats", None)
        if not callable(getter):
            return None
        return getter()

    def context_usage(self) -> object:
        getter = getattr(self.session, "get_context_usage", None)
        if not callable(getter):
            return None
        return getter()

    async def _run_held_prompt(self, prompt: str) -> str:
        try:
            text = await self._run_session_prompt(prompt, emit_start=False)
        except Exception:
            if not self._abort_requested:
                raise
            text = ""
        finally:
            if self._abort_requested:
                await self._emit(WorkflowEvent(type="run.aborted", text=prompt))
            self._active_prompt_task = None
            self._abort_requested = False
        return text

    async def _queue_text(self, text: str, *, action: str, event_type: str) -> None:
        method = _streaming_prompt_method(
            self.session,
            streaming_behavior="steer" if action == "steer" else "followUp",
        )
        if method is None:
            method = getattr(self.session, action, None)
        if not callable(method):
            raise RuntimeError(f"workflow session does not support {action}")
        result = method(text)
        if inspect.isawaitable(result):
            await result
        await self._emit(WorkflowEvent(type=event_type, text=text))

    async def _record_session_event(self, event: dict) -> None:
        if event.get("type") != "message_end":
            return
        message = event.get("message")
        if _safe_getattr(message, "role", None) == "assistant":
            text = _message_text(message)
            if text:
                await self._emit(WorkflowEvent(type="assistant.message", text=text))

    async def _record_runtime_event(self, event: RuntimeEvent[object]) -> None:
        if event.kind != "agent.message_end" or not isinstance(event.payload, Mapping):
            return
        await self._record_session_event(dict(event.payload))

    async def _emit(self, event: WorkflowEvent) -> None:
        async with self._condition:
            self._events.append(event)
            self._condition.notify_all()


async def run_workflow(
    workflow: Workflow,
    *,
    adapter: WorkflowAdapter,
    cwd: str | Path,
    default_step_timeout_s: float | None = 300.0,
    on_step_start: object | None = None,
    command_runner: CommandRunner | None = None,
) -> WorkflowResult:
    root = Path(cwd).resolve()
    step_results: list[WorkflowStepResult] = []
    total = len(workflow.steps)
    for index, step in enumerate(workflow.steps, start=1):
        _emit_step_start(on_step_start, index=index, total=total, step=step)
        try:
            assistant_text = await _run_step(
                adapter,
                step,
                default_step_timeout_s=default_step_timeout_s,
            )
        except TimeoutError:
            await _abort_adapter(adapter)
            step_results.append(
                WorkflowStepResult(
                    index=index,
                    prompt=_step_label(step),
                    error=_timeout_error_message(step, default_step_timeout_s),
                    checks=(
                        CheckResult(
                            label="prompt completed", ok=False, detail="timed out"
                        ),
                    ),
                )
            )
            break
        except asyncio.CancelledError:
            await _abort_adapter(adapter)
            raise
        except Exception as error:
            step_results.append(
                WorkflowStepResult(
                    index=index,
                    prompt=_step_label(step),
                    error=str(error) or error.__class__.__name__,
                    checks=(
                        CheckResult(
                            label="prompt completed", ok=False, detail=str(error)
                        ),
                    ),
                )
            )
            break
        checks = await _evaluate_step_checks(
            step,
            adapter=adapter,
            assistant_text=assistant_text,
            cwd=root,
            command_runner=command_runner,
        )
        step_results.append(
            WorkflowStepResult(
                index=index,
                prompt=_step_label(step),
                assistant_text=assistant_text,
                checks=checks,
            )
        )
    return WorkflowResult(
        name=workflow.name,
        step_results=tuple(step_results),
        events=_adapter_events(adapter),
    )


async def _evaluate_step_checks(
    step: WorkflowStep,
    *,
    adapter: WorkflowAdapter,
    assistant_text: str,
    cwd: Path,
    command_runner: CommandRunner | None,
) -> tuple[CheckResult, ...]:
    if isinstance(step, PromptStep):
        return await evaluate_expectations(
            step.expect,
            assistant_text=assistant_text,
            cwd=cwd,
            command_runner=command_runner,
        )
    if isinstance(step, ExpectStep):
        return evaluate_workflow_expectations(
            step.expect,
            events=_adapter_events(adapter),
            queue_state=_adapter_queue_state(adapter),
            session_state=_adapter_session_state(adapter),
            session_stats=_adapter_session_stats(adapter),
            context_usage=_adapter_context_usage(adapter),
        )
    return ()


def _adapter_events(adapter: WorkflowAdapter):
    events = getattr(adapter, "events", None)
    if not callable(events):
        return ()
    value = events()
    return tuple(value) if isinstance(value, tuple | list) else ()


def _adapter_queue_state(adapter: WorkflowAdapter) -> object | None:
    queue_state = getattr(adapter, "queue_state", None)
    if not callable(queue_state):
        return None
    return queue_state()


def _adapter_session_state(adapter: WorkflowAdapter) -> object | None:
    session_state = getattr(adapter, "session_state", None)
    if not callable(session_state):
        return None
    return session_state()


def _adapter_session_stats(adapter: WorkflowAdapter) -> object | None:
    session_stats = getattr(adapter, "session_stats", None)
    if not callable(session_stats):
        return None
    return session_stats()


def _adapter_context_usage(adapter: WorkflowAdapter) -> object | None:
    context_usage = getattr(adapter, "context_usage", None)
    if not callable(context_usage):
        return None
    return context_usage()


async def _run_step(
    adapter: WorkflowAdapter,
    step: WorkflowStep,
    *,
    default_step_timeout_s: float | None,
) -> str:
    if isinstance(step, PromptStep):
        timeout_s = (
            step.timeout_s if step.timeout_s is not None else default_step_timeout_s
        )
        return await _run_prompt_step_with_timeout(adapter, step, timeout_s=timeout_s)
    if isinstance(step, WaitForStep):
        await _wait_for_event(adapter, step)
        return ""
    if isinstance(step, WaitStep):
        await asyncio.sleep(step.duration_s)
        return ""
    if isinstance(step, SteerStep):
        await _call_adapter_action(adapter, "steer", step.text)
        return ""
    if isinstance(step, FollowUpStep):
        await _call_adapter_action(adapter, "follow_up", step.text)
        return ""
    if isinstance(step, AbortStep):
        await _abort_adapter(adapter)
        return ""
    if isinstance(step, ExpectStep):
        return ""
    raise TypeError(f"Unsupported workflow step: {step!r}")


async def _run_prompt_step_with_timeout(
    adapter: WorkflowAdapter,
    step: PromptStep,
    *,
    timeout_s: float | None,
) -> str:
    if timeout_s is None:
        return await _run_prompt_step(adapter, step)
    return await asyncio.wait_for(_run_prompt_step(adapter, step), timeout=timeout_s)


async def _run_prompt_step(adapter: WorkflowAdapter, step: PromptStep) -> str:
    prompt = getattr(adapter, "prompt", None)
    if callable(prompt):
        result = prompt(step.prompt, hold=step.hold)
        if inspect.isawaitable(result):
            result = await result
        return result if isinstance(result, str) else ""
    return await adapter.run_prompt(step.prompt)


async def _wait_for_event(adapter: WorkflowAdapter, step: WaitForStep) -> None:
    wait_for = getattr(adapter, "wait_for", None)
    if not callable(wait_for):
        raise RuntimeError("workflow adapter does not support wait_for")
    result = wait_for(EventPattern(event=step.event), step.timeout_s)
    if inspect.isawaitable(result):
        await result


async def _call_adapter_action(
    adapter: WorkflowAdapter, action: str, text: str
) -> None:
    method = getattr(adapter, action, None)
    if not callable(method):
        raise RuntimeError(f"workflow adapter does not support {action}")
    result = method(text)
    if inspect.isawaitable(result):
        await result


async def _run_prompt_with_timeout(
    adapter: WorkflowAdapter,
    prompt: str,
    *,
    timeout_s: float | None,
) -> str:
    if timeout_s is None:
        return await adapter.run_prompt(prompt)
    return await asyncio.wait_for(adapter.run_prompt(prompt), timeout=timeout_s)


async def _abort_adapter(adapter: WorkflowAdapter) -> None:
    abort = getattr(adapter, "abort", None)
    if not callable(abort):
        return
    result = abort()
    if inspect.isawaitable(result):
        await result


def _emit_step_start(
    callback: object | None, *, index: int, total: int, step: WorkflowStep
) -> None:
    if not callable(callback):
        return
    callback(index, total, step)


def _step_label(step: WorkflowStep) -> str:
    if isinstance(step, PromptStep):
        return step.prompt
    if isinstance(step, WaitForStep):
        return f"wait_for {step.event}"
    if isinstance(step, WaitStep):
        return f"wait {step.duration_s:g}s"
    if isinstance(step, SteerStep | FollowUpStep):
        return step.text
    return step.kind


def _timeout_error_message(
    step: WorkflowStep, default_step_timeout_s: float | None
) -> str:
    timeout_s: float | None
    if isinstance(step, PromptStep):
        timeout_s = (
            step.timeout_s if step.timeout_s is not None else default_step_timeout_s
        )
    elif isinstance(step, WaitForStep):
        timeout_s = step.timeout_s
    else:
        timeout_s = default_step_timeout_s
    if timeout_s is None:
        return "timed out"
    return f"timed out after {timeout_s:g}s"


def _assistant_text_after(session: Any, *, before_count: int) -> str:
    messages = _session_messages(session)
    recent = messages[before_count:] if before_count <= len(messages) else messages
    text = _latest_assistant_text(recent)
    if text:
        return text
    return _latest_assistant_text(messages)


def _has_assistant_message_event(events: list[WorkflowEvent]) -> bool:
    return any(event.type == "assistant.message" for event in events)


def _latest_assistant_text(messages: list[object]) -> str:
    for message in reversed(messages):
        if _safe_getattr(message, "role", None) != "assistant":
            continue
        content = _safe_getattr(message, "content", None)
        return _content_text(content)
    return ""


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list | tuple):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
            continue
        text = _safe_getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _message_text(message: object) -> str:
    return _content_text(_safe_getattr(message, "content", None))


def _streaming_prompt_method(session: Any, *, streaming_behavior: str):
    prompt = getattr(session, "prompt", None)
    if not callable(prompt) or not _supports_keyword(prompt, "streaming_behavior"):
        return None

    async def _call(text: str) -> Any:
        return await _maybe_await(prompt(text, streaming_behavior=streaming_behavior))

    return _call


def _supports_keyword(callable_obj: object, keyword: str) -> bool:
    if not callable(callable_obj):
        return False
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == keyword and parameter.kind in {
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }:
            return True
    return False


async def _maybe_await(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


def _call_text_list(target: Any, method_name: str) -> tuple[str, ...]:
    method = getattr(target, method_name, None)
    if not callable(method):
        return ()
    value = method()
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    return ()


def _session_messages(session: Any) -> list[object]:
    context_getter = getattr(session, "get_session_context", None)
    if callable(context_getter):
        try:
            context = context_getter()
        except Exception:
            context = None
        messages = _safe_getattr(context, "messages", None)
        if isinstance(messages, list):
            return list(messages)
    messages = _safe_getattr(session, "messages", None)
    if isinstance(messages, list):
        return list(messages)
    agent_state = _safe_getattr(_safe_getattr(session, "agent", None), "state", None)
    messages = _safe_getattr(agent_state, "messages", None)
    if isinstance(messages, list):
        return list(messages)
    return []


def _safe_getattr(target: Any, name: str, default: object) -> object:
    try:
        return getattr(target, name, default)
    except Exception:
        return default
