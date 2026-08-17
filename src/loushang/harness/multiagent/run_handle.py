"""Single-owner asynchronous run handle for one open agent incarnation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Literal, Protocol

from .control import MultiAgentControl
from .types import (
    AgentInputMessage,
    AgentRecord,
    AgentRef,
    AgentTransition,
    MultiAgentError,
    TerminalStatus,
)
from .workspace import WorkspaceLeaseSnapshot

RoundMode = Literal["prompt", "continue"]
MonotonicClock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class SubagentRoundResult:
    """Product-neutral terminal result from one prepared child run."""

    status: TerminalStatus
    final_message: str
    summary: str | None = None
    latest_input_tokens: int | None = None
    output_tokens: int = 0
    tool_uses: int = 0
    duration_ms: int | None = None
    workspace_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    change_set_ref: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"completed", "failed", "interrupted"}:
            raise ValueError(f"invalid subagent round status: {self.status}")
        if self.latest_input_tokens is not None and (
            type(self.latest_input_tokens) is not int or self.latest_input_tokens < 0
        ):
            raise ValueError("latest_input_tokens must be non-negative")
        if type(self.output_tokens) is not int or self.output_tokens < 0:
            raise ValueError("output_tokens must be non-negative")
        if type(self.tool_uses) is not int or self.tool_uses < 0:
            raise ValueError("tool_uses must be non-negative")
        if self.duration_ms is not None and (
            type(self.duration_ms) is not int or self.duration_ms < 0
        ):
            raise ValueError("duration_ms must be non-negative")
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))


@dataclass(frozen=True, slots=True)
class SubagentDisposeResult:
    """Explicit resources and errors produced while disposing one child."""

    released_workspace: WorkspaceLeaseSnapshot | None = None
    dispose_error: Exception | None = None


class SubagentRoundDriver(Protocol):
    """Narrow adapter over an existing Product session/HostRuntime.

    ``run_round`` must not report terminal while a follow-up accepted by
    ``deliver`` for that round remains unconsumed.  A session adapter may
    satisfy this by draining its existing follow-up queue before returning;
    the handle never creates a second queue.
    """

    def deliver(self, message: AgentInputMessage) -> None: ...

    async def run_round(
        self,
        *,
        round_id: int,
        mode: RoundMode,
    ) -> SubagentRoundResult: ...

    def abort(self) -> None: ...

    async def dispose(self) -> SubagentDisposeResult: ...


@dataclass(frozen=True, slots=True)
class HandleDeliveryOutcome:
    recipient_ref: AgentRef
    round_id: int
    triggered_new_round: bool


@dataclass(frozen=True, slots=True)
class HandleCloseResult:
    record: AgentRecord
    dispose_error: Exception | None = None


class SubagentRunHandle:
    """Own every round task, abort, wait, and dispose for one AgentRef."""

    def __init__(
        self,
        *,
        ref: AgentRef,
        control: MultiAgentControl,
        driver: SubagentRoundDriver,
        monotonic_clock: MonotonicClock = monotonic,
    ) -> None:
        record = control.registry.get(ref)
        if record is None:
            raise MultiAgentError(
                "stale_agent_ref",
                f"cannot create a handle for a non-open agent: {ref}",
            )
        self.ref = ref
        self._control = control
        self._driver = driver
        self._monotonic_clock = monotonic_clock
        self._state_lock = asyncio.Lock()
        self._active_task: asyncio.Task[AgentTransition] | None = None
        self._close_task: asyncio.Task[HandleCloseResult] | None = None
        self._abort_requested_rounds: set[int] = set()

    @property
    def is_running(self) -> bool:
        task = self._active_task
        return task is not None and not task.done()

    @property
    def is_closing(self) -> bool:
        return self._close_task is not None

    async def deliver(self, message: AgentInputMessage) -> HandleDeliveryOutcome:
        """Queue one message and start a tracked round only when currently idle."""

        async with self._state_lock:
            current = self._require_deliverable(message)
            self._driver.deliver(message)
            task = self._active_task
            if task is not None and not task.done():
                return HandleDeliveryOutcome(
                    recipient_ref=self.ref,
                    round_id=current.round_id,
                    triggered_new_round=False,
                )
            if current.status == "running":
                raise RuntimeError(f"agent {self.ref} is running without an owned task")

            transition = self._control.begin_round(self.ref)
            if not transition.applied or transition.record is None:
                raise RuntimeError(
                    f"cannot begin a new round for {self.ref}: {transition.reason}"
                )
            round_id = transition.record.round_id
            mode: RoundMode = "prompt" if round_id == 1 else "continue"
            task = asyncio.create_task(
                self._run_owned_round(round_id=round_id, mode=mode),
                name=f"subagent:{self.ref}:round-{round_id}",
            )
            self._active_task = task
            return HandleDeliveryOutcome(
                recipient_ref=self.ref,
                round_id=round_id,
                triggered_new_round=True,
            )

    async def enqueue(self, message: AgentInputMessage) -> HandleDeliveryOutcome:
        """Queue input without starting a new round.

        Completion notices use this path by default: they become visible to
        the parent's existing input queue without unexpectedly starting a
        second orchestration turn.
        """

        async with self._state_lock:
            current = self._require_deliverable(message)
            self._driver.deliver(message)
            return HandleDeliveryOutcome(
                recipient_ref=self.ref,
                round_id=current.round_id,
                triggered_new_round=False,
            )

    async def await_terminal(
        self,
        *,
        timeout: float | None = None,
    ) -> AgentRecord:
        """Await the current owned round without cancelling it on timeout."""

        async with self._state_lock:
            task = self._active_task
            self._current_record()
        if task is not None and not task.done():
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        return self._current_record()

    async def interrupt(self) -> AgentRecord:
        """Abort and await the current round while leaving the agent open."""

        async with self._state_lock:
            task = self._active_task
            current = self._current_record()
            if task is None or task.done():
                return current
            round_id = current.round_id
            self._abort_requested_rounds.add(round_id)
            try:
                self._driver.abort()
            except Exception:
                self._abort_requested_rounds.discard(round_id)
                raise

        await asyncio.shield(task)
        return self._current_record()

    async def close(self) -> HandleCloseResult:
        """Start one shielded close operation and share it across callers."""

        async with self._state_lock:
            if self._close_task is None:
                self._close_task = asyncio.create_task(
                    self._close_owned(),
                    name=f"subagent:{self.ref}:close",
                )
            task = self._close_task
        return await asyncio.shield(task)

    async def _run_owned_round(
        self,
        *,
        round_id: int,
        mode: RoundMode,
    ) -> AgentTransition:
        started_at = self._monotonic_clock()
        result: SubagentRoundResult
        try:
            result = await self._driver.run_round(round_id=round_id, mode=mode)
        except asyncio.CancelledError:
            requested = round_id in self._abort_requested_rounds
            current = self._current_record()
            result = SubagentRoundResult(
                status="interrupted" if requested else "failed",
                final_message=(
                    "Agent run interrupted."
                    if requested
                    else "Agent run task was cancelled unexpectedly."
                ),
                workspace_ref=current.workspace_ref,
                artifact_refs=current.artifact_refs,
                change_set_ref=current.change_set_ref,
            )
        except Exception as error:
            current = self._current_record()
            result = SubagentRoundResult(
                status="failed",
                final_message=str(error) or type(error).__name__,
                workspace_ref=current.workspace_ref,
                artifact_refs=current.artifact_refs,
                change_set_ref=current.change_set_ref,
            )

        if round_id in self._abort_requested_rounds and result.status != "interrupted":
            result = SubagentRoundResult(
                status="interrupted",
                final_message="Agent run interrupted.",
                summary=result.summary,
                latest_input_tokens=result.latest_input_tokens,
                output_tokens=result.output_tokens,
                tool_uses=result.tool_uses,
                duration_ms=result.duration_ms,
                workspace_ref=result.workspace_ref,
                artifact_refs=result.artifact_refs,
                change_set_ref=result.change_set_ref,
            )

        if result.summary is None:
            self._control.record_progress(
                self.ref,
                round_id=round_id,
                latest_input_tokens=result.latest_input_tokens,
                output_tokens_delta=result.output_tokens,
                tool_uses_delta=result.tool_uses,
            )
        else:
            self._control.record_progress(
                self.ref,
                round_id=round_id,
                latest_input_tokens=result.latest_input_tokens,
                output_tokens_delta=result.output_tokens,
                tool_uses_delta=result.tool_uses,
                summary=result.summary,
            )
        duration_ms = (
            result.duration_ms
            if result.duration_ms is not None
            else max(0, int((self._monotonic_clock() - started_at) * 1000))
        )
        transition = self._control.finish_round(
            self.ref,
            round_id=round_id,
            status=result.status,
            final_message=result.final_message,
            duration_ms=duration_ms,
            summary=result.summary,
            workspace_ref=result.workspace_ref,
            artifact_refs=result.artifact_refs,
            change_set_ref=result.change_set_ref,
        )
        async with self._state_lock:
            self._abort_requested_rounds.discard(round_id)
            if self._active_task is asyncio.current_task():
                self._active_task = None
        return transition

    async def _close_owned(self) -> HandleCloseResult:
        dispose_error: Exception | None = None
        dispose_result = SubagentDisposeResult()
        try:
            await self.interrupt()
        except Exception as error:
            dispose_error = error
        async with self._state_lock:
            active_task = self._active_task
        if active_task is not None and not active_task.done():
            # A failed abort does not grant permission to dispose resources
            # still owned by a live round.
            await asyncio.shield(active_task)
        try:
            dispose_result = await self._driver.dispose()
            if not isinstance(dispose_result, SubagentDisposeResult):
                raise TypeError(
                    "SubagentRoundDriver.dispose() must return SubagentDisposeResult"
                )
        except Exception as error:
            if dispose_error is None:
                dispose_error = error
        if dispose_result.dispose_error is not None and dispose_error is None:
            dispose_error = dispose_result.dispose_error
        if dispose_result.released_workspace is not None:
            self._control.record_workspace_snapshot(
                self.ref,
                dispose_result.released_workspace,
            )
        transition = self._control.commit_closed(self.ref)
        record = transition.record
        if record is None:
            current = self._control.registry.current(
                self.ref.path,
                include_closed=True,
            )
            if current is None or current.ref != self.ref:
                raise MultiAgentError(
                    "stale_agent_ref",
                    f"agent changed before close completed: {self.ref}",
                )
            record = current
        return HandleCloseResult(record=record, dispose_error=dispose_error)

    def _current_record(self) -> AgentRecord:
        record = self._control.registry.get(self.ref, include_closed=True)
        if record is None:
            raise MultiAgentError(
                "stale_agent_ref", f"agent reference is stale: {self.ref}"
            )
        return record

    def _require_deliverable(self, message: AgentInputMessage) -> AgentRecord:
        if message.recipient_ref != self.ref:
            raise MultiAgentError(
                "agent_message_misdirected",
                f"message targets {message.recipient_ref}, not {self.ref}",
            )
        if self._close_task is not None:
            raise MultiAgentError(
                "agent_not_addressable",
                f"agent is closing or closed: {self.ref.path}",
            )
        current = self._control.registry.get(self.ref, include_closed=True)
        if current is None:
            raise MultiAgentError(
                "stale_agent_ref", f"agent reference is stale: {self.ref}"
            )
        if current.status == "closed":
            raise MultiAgentError(
                "agent_not_addressable", f"agent is closed: {self.ref.path}"
            )
        return current


__all__ = [
    "HandleCloseResult",
    "HandleDeliveryOutcome",
    "MonotonicClock",
    "RoundMode",
    "SubagentDisposeResult",
    "SubagentRoundDriver",
    "SubagentRoundResult",
    "SubagentRunHandle",
]
