"""Product-neutral lifecycle host for one-shot plain prompt runs."""

from __future__ import annotations

import inspect
import time
import traceback
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TextIO, TypeVar

FailureStateT = TypeVar("FailureStateT")
TurnT = TypeVar("TurnT")
Cleanup = Callable[[], None]


def _no_cleanup() -> None:
    return None


@dataclass(frozen=True, slots=True)
class PlainPromptHostPorts(Generic[FailureStateT]):
    """Prepared product effects consumed by the one-shot prompt host.

    Session, model, raw event, work metadata, and failure interpretation stay
    behind these callbacks. ``submit`` returns only after the Product-owned
    turn operation has settled; the shared host does not independently wait
    on the Session. The shared host only owns ordering and exit state.
    """

    prepare: Callable[[], Awaitable[object]]
    subscribe: Callable[[], Cleanup]
    submit: Callable[[str, int, int], Awaitable[None]]
    capture_failure_state: Callable[[], FailureStateT]
    resolve_failure: Callable[[FailureStateT], str | None]
    render_user: Callable[[str], None]
    render_worked: Callable[[float], None]
    render_error: Callable[[str], None]
    dispose: Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PreparedPlainPromptRun(Generic[FailureStateT]):
    """Prepared prompt sequence and product ports for one terminal run."""

    prompts: tuple[str, ...]
    ports: PlainPromptHostPorts[FailureStateT]
    stderr: TextIO
    verbose: bool = False
    dispose: bool = True
    now: Callable[[], float] = time.monotonic


PlainPlanTurnHook = Callable[[TurnT, int, int], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class PlainPromptPlanHostPorts(Generic[TurnT, FailureStateT]):
    """Prepared effects for a Work-owned fixed prompt plan."""

    prepare: Callable[[], Awaitable[object]]
    subscribe: Callable[[], Cleanup]
    submit_plan: Callable[
        [
            Sequence[TurnT],
            PlainPlanTurnHook[TurnT],
            PlainPlanTurnHook[TurnT],
        ],
        Awaitable[None],
    ]
    turn_text: Callable[[TurnT], str]
    capture_failure_state: Callable[[], FailureStateT]
    resolve_failure: Callable[[FailureStateT], str | None]
    render_user: Callable[[str], None]
    render_worked: Callable[[float], None]
    render_error: Callable[[str], None]
    dispose: Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PreparedPlainPromptPlanRun(Generic[TurnT, FailureStateT]):
    """Prepared fixed plan and product ports for one terminal run."""

    turns: tuple[TurnT, ...]
    ports: PlainPromptPlanHostPorts[TurnT, FailureStateT]
    stderr: TextIO
    verbose: bool = False
    dispose: bool = True
    now: Callable[[], float] = time.monotonic


class PlainPromptTurnFailure(RuntimeError):
    """Signal an already-rendered assistant failure from a plan hook."""


async def run_plain_prompt_host(
    run: PreparedPlainPromptRun[FailureStateT],
) -> int:
    """Run prepared turns, then unsubscribe and optionally dispose.

    This deliberately preserves the original error boundary: ordinary run and
    disposal exceptions become exit code 1, while unsubscribe errors still
    propagate and prevent disposal rather than being silently swallowed.
    """

    unsubscribe = _no_cleanup
    exit_code = 0
    try:
        await run.ports.prepare()
        unsubscribe = run.ports.subscribe()
        turn_count = len(run.prompts)
        for turn_index, prompt in enumerate(run.prompts):
            exit_code = await _run_plain_prompt_turn(
                run,
                prompt,
                turn_index=turn_index,
                turn_count=turn_count,
            )
            if exit_code != 0:
                break
    except Exception as error:
        _present_exception(run, error)
        exit_code = 1
    finally:
        unsubscribe()
        if run.dispose:
            try:
                await run.ports.dispose()
            except Exception as error:
                _present_exception(run, error)
                exit_code = 1
    return exit_code


async def run_plain_prompt_plan_host(
    run: PreparedPlainPromptPlanRun[TurnT, FailureStateT],
) -> int:
    """Run one Work-owned fixed plan through the plain prompt lifecycle."""

    started_at = 0.0
    failure_state: list[FailureStateT] = []

    async def before_turn(turn: TurnT, turn_index: int, turn_count: int) -> None:
        del turn_index, turn_count
        nonlocal started_at
        started_at = run.now()
        failure_state[:] = [run.ports.capture_failure_state()]
        run.ports.render_user(run.ports.turn_text(turn))

    async def after_turn(turn: TurnT, turn_index: int, turn_count: int) -> None:
        del turn, turn_index, turn_count
        if not failure_state:
            raise RuntimeError("plain prompt plan did not start the active turn")
        if run.ports.resolve_failure(failure_state[0]) is not None:
            raise PlainPromptTurnFailure
        run.ports.render_worked(run.now() - started_at)

    unsubscribe = _no_cleanup
    exit_code = 0
    try:
        await run.ports.prepare()
        unsubscribe = run.ports.subscribe()
        await run.ports.submit_plan(run.turns, before_turn, after_turn)
    except PlainPromptTurnFailure:
        exit_code = 1
    except Exception as error:
        _present_plan_exception(run, error)
        exit_code = 1
    finally:
        unsubscribe()
        if run.dispose:
            try:
                await run.ports.dispose()
            except Exception as error:
                _present_plan_exception(run, error)
                exit_code = 1
    return exit_code


def last_assistant_failure_message(session: object) -> str | None:
    """Return the latest terminal assistant failure, if one exists."""

    for message in reversed(session_messages(session)):
        if _safe_getattr(message, "role", None) != "assistant":
            continue
        stop_reason = _safe_getattr(
            message,
            "stop_reason",
            _safe_getattr(message, "stopReason", None),
        )
        if stop_reason not in {"error", "aborted"}:
            return None
        error_message = _safe_getattr(
            message,
            "error_message",
            _safe_getattr(message, "errorMessage", None),
        )
        return (
            error_message
            if isinstance(error_message, str) and error_message
            else f"Request {stop_reason}"
        )
    return None


def session_messages(session: object) -> list[object]:
    """Read messages through the standard session, facade, or Agent shapes."""

    context_getter = getattr(session, "get_session_context", None)
    if callable(context_getter):
        try:
            context = context_getter()
        except Exception:
            context = None
        messages = _safe_getattr(context, "messages", None)
        if isinstance(messages, list | tuple):
            return list(messages)
    messages = _safe_getattr(session, "messages", None)
    if isinstance(messages, list | tuple):
        return list(messages)
    agent_state = _safe_getattr(_safe_getattr(session, "agent", None), "state", None)
    messages = _safe_getattr(agent_state, "messages", None)
    if isinstance(messages, list | tuple):
        return list(messages)
    return []


def session_identity(session: object) -> str:
    """Resolve a stable session id from standard Product session shapes."""

    session_id = _safe_getattr(session, "session_id", None)
    if isinstance(session_id, str) and session_id:
        return session_id
    session_manager = getattr(session, "session_manager", None)
    get_header = getattr(session_manager, "get_header", None)
    if callable(get_header):
        try:
            header = get_header()
        except Exception:
            header = None
        conversation_id = _safe_getattr(header, "conversation_id", None)
        if isinstance(conversation_id, str) and conversation_id:
            return conversation_id
    return "session"


async def dispose_runtime_or_session(runtime: object, session: object) -> None:
    """Dispose a Product runtime, falling back to its session."""

    disposer = getattr(runtime, "dispose", None)
    if not callable(disposer):
        disposer = getattr(session, "dispose", None)
    if not callable(disposer):
        return
    result = disposer()
    if inspect.isawaitable(result):
        await result


async def _run_plain_prompt_turn(
    run: PreparedPlainPromptRun[FailureStateT],
    prompt: str,
    *,
    turn_index: int,
    turn_count: int,
) -> int:
    started_at = run.now()
    previous_failure = run.ports.capture_failure_state()
    run.ports.render_user(prompt)
    await run.ports.submit(prompt, turn_index, turn_count)
    if run.ports.resolve_failure(previous_failure) is not None:
        return 1
    run.ports.render_worked(run.now() - started_at)
    return 0


def _present_exception(
    run: PreparedPlainPromptRun[FailureStateT],
    error: Exception,
) -> None:
    run.ports.render_error(str(error) or error.__class__.__name__)
    if run.verbose:
        traceback.print_exception(
            type(error),
            error,
            error.__traceback__,
            file=run.stderr,
        )


def _present_plan_exception(
    run: PreparedPlainPromptPlanRun[TurnT, FailureStateT],
    error: Exception,
) -> None:
    run.ports.render_error(str(error) or error.__class__.__name__)
    if run.verbose:
        traceback.print_exception(
            type(error),
            error,
            error.__traceback__,
            file=run.stderr,
        )


def _safe_getattr(target: Any, name: str, default: object) -> object:
    try:
        return getattr(target, name, default)
    except Exception:
        return default


__all__ = [
    "PlainPromptHostPorts",
    "PlainPromptPlanHostPorts",
    "PlainPromptTurnFailure",
    "PreparedPlainPromptRun",
    "PreparedPlainPromptPlanRun",
    "dispose_runtime_or_session",
    "last_assistant_failure_message",
    "run_plain_prompt_host",
    "run_plain_prompt_plan_host",
    "session_identity",
    "session_messages",
]
