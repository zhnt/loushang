"""One retained Method invocation on the original Coding Session/Work runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.appservice.execution_contract import ExecutionOutcomeV1, ExecutionStatusV1
from loushang.appservice.execution_guard import ExecutionControlV1
from loushang.harnesswork.integrations.session import (
    SessionWorkRuntime,
    SessionWorkTurn,
)
from loushang.harnesswork.recording import WorkRecordingUnavailable
from loushang.harnesswork.types import WorkRun

from ._hosted_execution_work import CodingExecutionWorkV1
from ._hosted_method_config import CodingHostedMethodV1
from .session.agent_session import AgentSession

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class _StepFailed(RuntimeError):
    pass


class MethodInvocation:
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

    def checkpoint(self) -> None:
        if self.cancelled or self.cancel_requested():
            raise asyncio.CancelledError

    def before_turn(self, turn: SessionWorkTurn, index: int, count: int) -> None:
        self.checkpoint()

    async def _submit(self, turns: tuple[SessionWorkTurn, ...]) -> WorkRun:
        self.checkpoint()
        self.submit_started = True
        return await self.runtime.submit_plan(
            turns, session_id=self.session.session_id, operation_id=self.execution_id,
            before_turn=self.before_turn,
        )

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
        operation = self._submit(turns)
        try:
            self.task = asyncio.create_task(operation)
        except BaseException:
            operation.close()
            self.not_submitted = True
            raise
        try:
            run = await asyncio.shield(self.task)
            record = self.runtime.work_runtime.get_recording(run.run_id)
            if run.status == record.run.status == "completed":
                return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
            return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, "method_work_failed")
        except asyncio.CancelledError:
            self.cancelled = True
            # Cancel the retained plan, not merely its shielded observer. Its
            # original Work.wait already bridges cancellation to Work.cancel.
            if not self.task.done():
                self.task.cancel()
            # Joining and any retryable debt belong to settle, never a replay.
            raise
        except WorkRecordingUnavailable:
            self.recording_unavailable = True
            return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, "work_recording_unavailable")
        except Exception:
            self._check_recording()
            return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, "method_work_failed")

    def _check_recording(self) -> None:
        if not self.submit_started:
            return
        try:
            run = self.runtime.work_runtime.get_run_for_operation(self.execution_id)
            if run is None:
                self.recording_unavailable = True
            else:
                self.runtime.work_runtime.get_recording(run.run_id)
        except Exception:
            self.recording_unavailable = True

    async def settle(self) -> None:
        task = self.task
        if task is not None:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.done():
                    raise
                self.cancelled = True
            except Exception:
                # Business failure is not by itself cleanup debt. The original
                # runtime and Session below still have to establish quiescence.
                pass
            if not self.submit_started:
                self.not_submitted = True
            run = self.runtime.work_runtime.get_run_for_operation(self.execution_id)
            if run is not None:
                # A failed terminal append may leave a completed-looking run
                # active. The runtime's ownership view, not that text, decides.
                if any(active.run_id == run.run_id for active in self.runtime.work_runtime.active_runs()):
                    try:
                        await self.runtime.work_runtime.cancel(run.run_id)
                    except Exception:
                        self._check_recording()
                        if not self.recording_unavailable:
                            raise
                try:
                    await self.runtime.work_runtime.wait(run.run_id)
                except asyncio.CancelledError:
                    self.cancelled = True
                except Exception:
                    # Work.wait has joined its retained executor before raising
                    # the recorded business/cancellation result.
                    pass
            self._check_recording()
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
