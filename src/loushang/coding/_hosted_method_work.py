"""One retained Method invocation on the original Coding Session/Work runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.appservice.execution_contract import ExecutionOutcomeV1, ExecutionStatusV1
from loushang.appservice.execution_guard import ExecutionControlV1
from loushang.harnesswork.integrations.session import (
    SessionWorkRuntime,
    _RetainedSessionPlan,
)
from loushang.harnesswork.types import WorkRun

from ._hosted_execution_work import CodingExecutionWorkV1
from ._hosted_method_config import CodingHostedMethodV1
from .session.agent_session import AgentSession

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class _StepFailed(RuntimeError):
    pass


class MethodInvocation(_RetainedSessionPlan):
    session: AgentSession

    def __init__(
        self, session: AgentSession, runtime: SessionWorkRuntime, method: CodingHostedMethodV1,
        execution_id: str, text: str, cancel_requested: Callable[[], bool],
    ) -> None:
        self.session = session
        self.runtime = runtime
        self.method = method
        self.execution_id = execution_id
        self.text = text
        self.cancel_requested = cancel_requested
        self.cancelled = False
        self.not_submitted = False
        self.submit_started = False
        self.recording_unavailable = False
        self.task: asyncio.Task[WorkRun] | None = None
        self.step: CodingExecutionWorkV1 | None = None
        self.control: ExecutionControlV1 | None = None

    async def run(self, control: ExecutionControlV1) -> ExecutionOutcomeV1:
        self.control = control
        try:
            self.checkpoint()
            turns = self.method.prepare(self.text, Path(self.session.session_manager.get_cwd()))
        except asyncio.CancelledError:
            self.not_submitted = True
            self.cancelled = True
            raise
        except (ValueError, TypeError):
            self.not_submitted = True
            return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, "method_preparation_failed")
        return await self._run_plan(turns, self._plan_outcome)

    def _plan_outcome(self, status: str) -> ExecutionOutcomeV1:
        if status == "completed":
            return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
        if status == "recording_unavailable":
            return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, "work_recording_unavailable")
        return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, "method_work_failed")

    async def settle(self) -> None:
        await self._settle_plan()
        if self.step is not None:
            await self.step.settle()
            self.step = None
        await self.session.settle_execution(interrupted=self.cancelled)
        self.control = None

class MethodPrompt:
    """Prompt-port adaptation only; execution and cancellation remain Work-owned."""

    def __init__(self, session: AgentSession, current: Callable[[], MethodInvocation]) -> None:
        self.session = session
        self.current = current

    def subscribe_runtime_events(self, listener):  # type: ignore[no-untyped-def]
        return self.session.subscribe_runtime_events(listener)

    @property
    def work_execution_backend(self) -> object | None:
        return self.session.work_execution_backend

    def bind_work_execution_backend(self, backend, *, busy, settle=None):
        self.session.bind_work_execution_backend(backend, busy=busy, settle=settle)

    def before_work_accept(self) -> None:
        self.session.before_work_accept()

    def abort(self) -> None:
        self.session.abort()

    async def wait_for_idle(self) -> None:
        await self.session.wait_for_idle()

    async def prompt(
        self, text: str, *, images: Sequence[object] | None = None,
        streaming_behavior: str | None = None, source: str | None = None,
    ) -> None:
        if images or streaming_behavior:
            raise ValueError("hosted Method only accepts prepared text steps")
        current = self.current()
        current.checkpoint()
        assert current.control is not None
        step = CodingExecutionWorkV1(self.session, text, lambda: current.cancelled or current.cancel_requested())
        current.step = step
        outcome = await step.run(current.control)
        # Retain the original step through failed settlement; retry only settles.
        await step.settle()
        current.step = None
        if outcome.status is ExecutionStatusV1.INTERRUPTED:
            current.cancelled = True
            raise asyncio.CancelledError
        if outcome.status is not ExecutionStatusV1.SUCCEEDED:
            raise _StepFailed("method_step_failed")
