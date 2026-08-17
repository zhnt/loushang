from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from loushang.harnesswork.event_log import EventLogBackend, EventLogEntry, EventPosition
from loushang.harnesswork.ports import (
    WorkDomainCancellation,
    WorkDomainExecutionResolver,
    WorkDomainExecutor,
    WorkExecutionBinding,
    WorkExecutionContext,
)
from loushang.harnesswork.types import (
    DeliveryHint,
    WorkCancellationOutcome,
    WorkEvent,
    WorkEventFact,
    WorkOperation,
    WorkRun,
    WorkRunSpec,
    WorkStepSpec,
)

_LIFECYCLE_EVENT_KINDS = frozenset(
    {
        "WorkRunStarted",
        "WorkRunCancelling",
        "WorkRunCompleted",
        "WorkRunFailed",
        "WorkRunCancelled",
        "WorkPlanStarted",
        "WorkPlanCompleted",
        "WorkPlanFailed",
        "WorkPlanCancelled",
        "WorkStepStarted",
        "WorkStepCompleted",
        "WorkStepFailed",
        "WorkStepCancelled",
    }
)
class WorkRuntimeError(RuntimeError):
    pass


class UnknownWorkRunError(WorkRuntimeError):
    pass


class DuplicateWorkOperationError(WorkRuntimeError):
    pass


class WorkRunTerminalError(WorkRuntimeError):
    pass


class WorkLifecycleOwnershipError(WorkRuntimeError):
    pass


class WorkCancellationFailedError(WorkRuntimeError):
    pass


class WorkCancellationTimeoutError(WorkCancellationFailedError):
    pass


@dataclass
class _RunState:
    operation: WorkOperation
    spec: WorkRunSpec
    run: WorkRun
    executor: WorkDomainExecutor
    cancellation: WorkDomainCancellation | None
    sequence: int = 0
    task: asyncio.Task[None] | None = None
    cancellation_task: asyncio.Task[WorkCancellationOutcome] | None = None
    cancellation_outcome: WorkCancellationOutcome | None = None
    error: BaseException | None = None
    terminal: bool = False
    current_step: WorkStepSpec | None = None
    current_step_index: int | None = None
    step_active: bool = False


@dataclass(frozen=True)
class _ExecutionContext(WorkExecutionContext):
    runtime: WorkRuntime
    state: _RunState

    @property
    def run_id(self) -> str:
        return self.state.run.run_id

    @property
    def step_id(self) -> str | None:
        step = self.state.current_step
        return step.step_id if step is not None else None

    @property
    def step_index(self) -> int | None:
        return self.state.current_step_index

    @property
    def step_payload(self) -> Mapping[str, object]:
        step = self.state.current_step
        return step.payload if step is not None else {}

    def publish(self, fact: WorkEventFact) -> WorkEvent:
        return self.runtime._publish_domain_fact(self.state, fact)


WorkEventListener = Callable[[WorkEvent], None]


class WorkRuntime:
    """Accept operations and own their complete observable Work lifecycle."""

    def __init__(
        self,
        *,
        event_log: EventLogBackend,
        executor: WorkDomainExecutor | None = None,
        cancellation: WorkDomainCancellation | None = None,
        resolver: WorkDomainExecutionResolver | None = None,
        cancellation_timeout: float | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if (executor is None) == (resolver is None):
            raise ValueError("provide exactly one of executor or resolver")
        if resolver is not None and cancellation is not None:
            raise ValueError("resolver owns the per-operation cancellation capability")
        if cancellation_timeout is not None and cancellation_timeout <= 0:
            raise ValueError("cancellation_timeout must be positive")
        self._executor = executor
        self._cancellation = cancellation
        self._resolver = resolver
        self._cancellation_timeout = cancellation_timeout
        self._event_log = event_log
        self._clock = clock
        self._replay_checkpoint = event_log.checkpoint()
        from loushang.harnesswork.run_projection import project_work_runs

        historical_runs = project_work_runs(
            event_log.query(), mark_incomplete_orphaned=True
        )
        self._historical_runs = {run.run_id: run for run in historical_runs}
        self._historical_operation_runs = {
            run.operation_id: run.run_id for run in historical_runs
        }
        self._states: dict[str, _RunState] = {}
        self._operation_runs: dict[str, str] = {}
        self._event_listeners: list[WorkEventListener] = []

    async def accept(
        self,
        operation: WorkOperation,
        *,
        spec: WorkRunSpec | None = None,
    ) -> WorkRun:
        if self.get_run_for_operation(operation.operation_id) is not None:
            raise DuplicateWorkOperationError(
                f"operation already accepted: {operation.operation_id}"
            )
        resolved_spec = spec or WorkRunSpec()
        _validate_spec(resolved_spec)
        binding = self._resolve_execution(operation, resolved_spec)
        run_id = resolved_spec.run_id or f"run-{uuid4().hex}"
        if self._find_run(run_id) is not None:
            raise DuplicateWorkOperationError(f"run already exists: {run_id}")
        steps = _steps(resolved_spec)
        first_step_id = steps[0].step_id if steps else None
        run = WorkRun(
            run_id=run_id,
            operation_id=operation.operation_id,
            session_id=operation.session_id or "",
            domain=operation.domain,
            status="accepted",
            method_id=resolved_spec.method_id,
            plan_id=resolved_spec.plan_id,
            current_step_id=first_step_id,
        )
        state = _RunState(
            operation=operation,
            spec=resolved_spec,
            run=run,
            executor=binding.executor,
            cancellation=binding.cancellation,
        )
        self._append_operation(state)
        self._states[run_id] = state
        self._operation_runs[operation.operation_id] = run_id
        state.task = asyncio.create_task(
            self._execute(state), name=f"work-runtime:{run_id}"
        )
        return run

    async def wait(self, run_id: str) -> WorkRun:
        state = self._state(run_id)
        task = state.task
        if task is None:
            raise WorkRuntimeError(f"run has no execution task: {run_id}")
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await self.cancel(run_id)
            raise
        if state.error is not None:
            if isinstance(state.error, asyncio.CancelledError):
                raise asyncio.CancelledError(*state.error.args)
            raise state.error
        return state.run

    async def cancel(self, run_id: str) -> WorkRun:
        state = self._state(run_id)
        if state.terminal:
            return state.run
        if state.run.status == "accepted":
            self._start(state)
            self._activate_first_step(state)
        if state.run.status == "running":
            self._begin_cancelling(state)

        if state.cancellation is not None:
            if state.cancellation_task is None:
                state.cancellation_task = asyncio.create_task(
                    self._drive_domain_cancellation(state),
                    name=f"work-cancel:{run_id}",
                )
            outcome = await self._await_cancellation_outcome(state)
        else:
            outcome = WorkCancellationOutcome.unsupported()
            state.cancellation_outcome = outcome

        task = state.task
        if task is not None and not task.done():
            if outcome.status != "settled":
                task.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await self._await_execution_after_cancellation(task)
            except TimeoutError:
                timeout_error = WorkCancellationTimeoutError(
                    f"run {run_id} did not settle after cancellation"
                )
                outcome = WorkCancellationOutcome.failed(timeout_error)
                state.cancellation_outcome = outcome
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if not state.terminal:
            self._finish_cancellation_outcome(state, outcome)
        if outcome.status == "failed":
            raise _cancellation_error(outcome)
        return state.run

    def get_run(self, run_id: str) -> WorkRun:
        run = self._find_run(run_id)
        if run is None:
            raise UnknownWorkRunError(f"unknown work run: {run_id}")
        return run

    def get_run_for_operation(self, operation_id: str) -> WorkRun | None:
        run_id = self._operation_runs.get(operation_id)
        if run_id is not None:
            return self._states[run_id].run
        historical_run_id = self._historical_operation_runs.get(operation_id)
        if historical_run_id is not None:
            return self._historical_runs[historical_run_id]
        from loushang.harnesswork.run_projection import project_work_runs

        runs = project_work_runs(
            self._event_log.query(operation_id=operation_id),
            mark_incomplete_orphaned=True,
        )
        if not runs:
            return None
        run = runs[0]
        self._historical_runs[run.run_id] = run
        self._historical_operation_runs[run.operation_id] = run.run_id
        return run

    def active_runs(self, *, session_id: str | None = None) -> tuple[WorkRun, ...]:
        return tuple(
            state.run
            for state in self._states.values()
            if not state.terminal
            and (session_id is None or state.run.session_id == session_id)
        )

    def query_runs(
        self, *, run_id: str | None = None, session_id: str | None = None
    ) -> tuple[WorkRun, ...]:
        from loushang.harnesswork.run_projection import project_work_runs

        runs = project_work_runs(
            self._event_log.query(run_id=run_id, session_id=session_id)
        )
        return tuple(
            self._states[run.run_id].run
            if run.run_id in self._states
            else self._historical_runs.get(run.run_id, run)
            for run in runs
        )

    @property
    def replay_checkpoint(self) -> EventPosition:
        """High-water mark whose incomplete runs were classified as orphaned."""

        return self._replay_checkpoint

    def query(
        self,
        *,
        operation_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        after: EventPosition | None = None,
        limit: int | None = None,
    ) -> list[EventLogEntry]:
        return self._event_log.query(
            operation_id=operation_id,
            run_id=run_id,
            session_id=session_id,
            after=after,
            limit=limit,
        )

    def subscribe(
        self,
        *,
        operation_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        after: EventPosition | None = None,
    ) -> AsyncIterator[EventLogEntry]:
        return self._event_log.subscribe(
            operation_id=operation_id,
            run_id=run_id,
            session_id=session_id,
            after=after,
        )

    def subscribe_events(self, listener: WorkEventListener) -> Callable[[], None]:
        self._event_listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._event_listeners:
                self._event_listeners.remove(listener)

        return unsubscribe

    async def dispose(self) -> None:
        """Cancel and settle every active run owned by this runtime."""

        for run in tuple(self.active_runs()):
            with suppress(BaseException):
                await self.cancel(run.run_id)

    def _resolve_execution(
        self, operation: WorkOperation, spec: WorkRunSpec
    ) -> WorkExecutionBinding:
        if self._resolver is not None:
            return self._resolver.resolve(operation, spec)
        executor = self._executor
        if executor is None:  # Guarded by the constructor; keeps narrowing explicit.
            raise WorkRuntimeError("Work runtime has no domain executor")
        return WorkExecutionBinding(
            executor=executor,
            cancellation=self._cancellation,
        )

    async def _execute(self, state: _RunState) -> None:
        try:
            if state.run.status == "accepted":
                self._start(state)
            steps = _steps(state.spec)
            if not steps:
                await state.executor.execute(
                    state.operation,
                    _ExecutionContext(runtime=self, state=state),
                )
            else:
                for index, step in enumerate(steps):
                    if state.run.status == "cancelling":
                        raise asyncio.CancelledError()
                    self._start_step(state, step, index)
                    await state.executor.execute(
                        state.operation,
                        _ExecutionContext(runtime=self, state=state),
                    )
                    self._complete_step(state)
        except asyncio.CancelledError as error:
            if not state.terminal:
                if state.run.status == "accepted":
                    self._start(state)
                    self._activate_first_step(state)
                if state.run.status == "running":
                    self._begin_cancelling(state)
                outcome = await self._settled_cancellation_outcome(state)
                self._finish_cancellation_outcome(state, outcome, cancelled=error)
        except Exception as error:
            if not state.terminal:
                if state.run.status == "cancelling":
                    outcome = await self._settled_cancellation_outcome(state)
                    self._finish_cancellation_outcome(state, outcome)
                else:
                    self._finish_failed(state, error)
        else:
            if not state.terminal:
                if state.run.status == "cancelling":
                    outcome = await self._settled_cancellation_outcome(state)
                    self._finish_cancellation_outcome(state, outcome)
                else:
                    self._finish_completed(state)

    async def _drive_domain_cancellation(
        self, state: _RunState
    ) -> WorkCancellationOutcome:
        cancellation = state.cancellation
        if cancellation is None:
            return WorkCancellationOutcome.unsupported()
        try:
            outcome = await cancellation.cancel_and_wait(
                state.operation,
                _ExecutionContext(runtime=self, state=state),
            )
        except BaseException as error:
            outcome = WorkCancellationOutcome.failed(error)
        if not isinstance(outcome, WorkCancellationOutcome):
            outcome = WorkCancellationOutcome.failed(
                WorkCancellationFailedError(
                    "domain cancellation must return WorkCancellationOutcome"
                )
            )
        state.cancellation_outcome = outcome
        return outcome

    async def _await_cancellation_outcome(
        self, state: _RunState
    ) -> WorkCancellationOutcome:
        task = state.cancellation_task
        if task is None:
            outcome = WorkCancellationOutcome.unsupported()
        try:
            if task is None:
                pass
            elif self._cancellation_timeout is None:
                outcome = await asyncio.shield(task)
            else:
                outcome = await asyncio.wait_for(
                    asyncio.shield(task), timeout=self._cancellation_timeout
                )
        except TimeoutError:
            if task is not None:
                task.cancel()
                with suppress(BaseException):
                    await task
            outcome = WorkCancellationOutcome.failed(
                WorkCancellationTimeoutError(
                    f"domain cancellation timed out for run {state.run.run_id}"
                )
            )
        state.cancellation_outcome = outcome
        return outcome

    async def _settled_cancellation_outcome(
        self, state: _RunState
    ) -> WorkCancellationOutcome:
        if state.cancellation_outcome is not None:
            return state.cancellation_outcome
        return await self._await_cancellation_outcome(state)

    async def _await_execution_after_cancellation(
        self, task: asyncio.Task[None]
    ) -> None:
        if self._cancellation_timeout is None:
            await task
            return
        await asyncio.wait_for(
            asyncio.shield(task), timeout=self._cancellation_timeout
        )

    def _finish_cancellation_outcome(
        self,
        state: _RunState,
        outcome: WorkCancellationOutcome,
        *,
        cancelled: asyncio.CancelledError | None = None,
    ) -> None:
        if state.terminal:
            return
        if outcome.status == "failed":
            self._finish_failed(state, _cancellation_error(outcome))
            return
        self._finish_cancelled(state, cancelled or asyncio.CancelledError())

    def _start(self, state: _RunState) -> None:
        if state.run.status != "accepted":
            return
        state.run = replace(state.run, status="running")
        self._publish_lifecycle(
            state, kind="WorkRunStarted", payload=state.spec.run_event_payload
        )
        if state.spec.plan_id is not None:
            self._publish_lifecycle(
                state,
                kind="WorkPlanStarted",
                payload=state.spec.scope_event_payload,
                delivery_hint="coalesce",
            )

    def _activate_first_step(self, state: _RunState) -> None:
        steps = _steps(state.spec)
        if steps and not state.step_active:
            self._start_step(state, steps[0], 0)

    def _start_step(
        self, state: _RunState, step: WorkStepSpec, index: int
    ) -> None:
        if state.step_active:
            if state.current_step == step and state.current_step_index == index:
                return
            raise WorkRuntimeError("cannot start a Work step before the prior step ends")
        state.current_step = step
        state.current_step_index = index
        state.step_active = True
        state.run = replace(state.run, current_step_id=step.step_id)
        self._publish_lifecycle(
            state,
            kind="WorkStepStarted",
            payload=_step_payload(state, step),
            delivery_hint="coalesce",
        )

    def _complete_step(self, state: _RunState) -> None:
        if not state.step_active or state.current_step is None:
            return
        self._publish_lifecycle(
            state,
            kind="WorkStepCompleted",
            payload=_step_payload(state, state.current_step),
            delivery_hint="coalesce",
        )
        state.step_active = False

    def _begin_cancelling(self, state: _RunState) -> None:
        if state.run.status != "running":
            return
        state.run = replace(state.run, status="cancelling")
        self._publish_lifecycle(
            state, kind="WorkRunCancelling", payload=state.spec.run_event_payload
        )

    def _finish_completed(self, state: _RunState) -> None:
        terminal_run = replace(state.run, status="completed")
        if state.spec.plan_id is not None:
            self._publish_lifecycle(
                state,
                kind="WorkPlanCompleted",
                payload=state.spec.scope_event_payload,
                delivery_hint="final_only",
            )
        state.run = terminal_run
        self._publish_terminal(
            state, kind="WorkRunCompleted", payload=state.spec.run_event_payload
        )

    def _finish_failed(self, state: _RunState, error: Exception) -> None:
        state.error = error
        failure_payload = {**self._current_scope_payload(state), "error": str(error)}
        terminal_run = replace(state.run, status="failed")
        if state.step_active:
            self._publish_lifecycle(state, kind="WorkStepFailed", payload=failure_payload)
            state.step_active = False
        if state.spec.plan_id is not None:
            self._publish_lifecycle(state, kind="WorkPlanFailed", payload=failure_payload)
        state.run = terminal_run
        self._publish_terminal(
            state, kind="WorkRunFailed", payload=state.spec.run_event_payload
        )

    def _finish_cancelled(
        self, state: _RunState, error: asyncio.CancelledError
    ) -> None:
        if state.terminal:
            return
        state.error = error
        terminal_run = replace(state.run, status="cancelled")
        if state.step_active:
            self._publish_lifecycle(
                state,
                kind="WorkStepCancelled",
                payload=self._current_scope_payload(state),
            )
            state.step_active = False
        if state.spec.plan_id is not None:
            self._publish_lifecycle(
                state,
                kind="WorkPlanCancelled",
                payload=self._current_scope_payload(state),
            )
        state.run = terminal_run
        self._publish_terminal(
            state, kind="WorkRunCancelled", payload=state.spec.run_event_payload
        )

    def _current_scope_payload(self, state: _RunState) -> dict[str, object]:
        if state.current_step is not None:
            return _step_payload(state, state.current_step)
        return dict(state.spec.scope_event_payload)

    def _publish_domain_fact(self, state: _RunState, fact: WorkEventFact) -> WorkEvent:
        if fact.kind in _LIFECYCLE_EVENT_KINDS:
            raise WorkLifecycleOwnershipError(
                f"domain executor cannot publish Work lifecycle event: {fact.kind}"
            )
        if state.terminal:
            raise WorkRunTerminalError(
                f"cannot publish event after terminal run: {state.run.run_id}"
            )
        return self._append_event(
            state,
            kind=fact.kind,
            payload=fact.payload,
            delivery_hint=fact.delivery_hint,
            source_event_ref=fact.source_event_ref,
        )

    def _publish_lifecycle(
        self,
        state: _RunState,
        *,
        kind: str,
        payload: Mapping[str, object],
        delivery_hint: DeliveryHint = "immediate",
    ) -> WorkEvent:
        if state.terminal:
            raise WorkRunTerminalError(
                f"cannot publish lifecycle after terminal run: {state.run.run_id}"
            )
        return self._append_event(
            state,
            kind=kind,
            payload=self._lifecycle_payload(state, payload),
            delivery_hint=delivery_hint,
        )

    def _publish_terminal(
        self, state: _RunState, *, kind: str, payload: Mapping[str, object]
    ) -> WorkEvent:
        if state.terminal:
            raise WorkRunTerminalError(
                f"terminal event already published: {state.run.run_id}"
            )
        event = self._append_event(
            state,
            kind=kind,
            payload=self._lifecycle_payload(state, payload),
            delivery_hint="immediate",
        )
        state.terminal = True
        return event

    def _append_operation(self, state: _RunState) -> EventPosition:
        operation = state.operation
        return self._event_log.append(
            EventLogEntry(
                entry_id=f"{state.run.run_id}-operation-0",
                entry_type="operation",
                operation_id=operation.operation_id,
                event_id=None,
                run_id=state.run.run_id,
                session_id=operation.session_id or "",
                sequence=0,
                payload={
                    "kind": operation.kind,
                    "domain": operation.domain,
                    "payload": dict(operation.payload),
                },
                created_at=self._clock(),
            )
        )

    def _append_event(
        self,
        state: _RunState,
        *,
        kind: str,
        payload: Mapping[str, object],
        delivery_hint: DeliveryHint,
        source_event_ref: str | None = None,
    ) -> WorkEvent:
        state.sequence += 1
        event = WorkEvent(
            event_id=f"{state.run.run_id}-event-{state.sequence}",
            kind=kind,
            run_id=state.run.run_id,
            session_id=state.run.session_id,
            domain=state.run.domain,
            operation_id=state.run.operation_id,
            sequence=state.sequence,
            created_at=self._clock(),
            delivery_hint=delivery_hint,
            payload=payload,
            source_event_ref=source_event_ref,
        )
        self._event_log.append(_event_log_entry(event))
        for listener in tuple(self._event_listeners):
            with suppress(Exception):
                listener(event)
        return event

    def _lifecycle_payload(
        self, state: _RunState, payload: Mapping[str, object]
    ) -> dict[str, object]:
        result = dict(payload)
        if state.run.method_id is not None:
            result["method_id"] = state.run.method_id
        if state.run.plan_id is not None:
            result["plan_id"] = state.run.plan_id
        if state.run.current_step_id is not None:
            result["step_id"] = state.run.current_step_id
        return result

    def _state(self, run_id: str) -> _RunState:
        try:
            return self._states[run_id]
        except KeyError as error:
            raise UnknownWorkRunError(f"unknown active work run: {run_id}") from error

    def _find_run(self, run_id: str) -> WorkRun | None:
        state = self._states.get(run_id)
        if state is not None:
            return state.run
        return self._historical_runs.get(run_id)


def _steps(spec: WorkRunSpec) -> tuple[WorkStepSpec, ...]:
    if spec.steps:
        return spec.steps
    if spec.step_id is None:
        return ()
    return (WorkStepSpec(step_id=spec.step_id, payload=spec.scope_event_payload),)


def _validate_spec(spec: WorkRunSpec) -> None:
    step_ids = [step.step_id for step in spec.steps]
    if any(not step_id for step_id in step_ids):
        raise ValueError("Work step_id must be non-empty")
    if len(set(step_ids)) != len(step_ids):
        raise ValueError("Work step_id values must be unique within a run")
    if spec.steps and spec.plan_id is None:
        raise ValueError("multi-step Work runs require plan_id")


def _step_payload(state: _RunState, step: WorkStepSpec) -> dict[str, object]:
    result = dict(state.spec.scope_event_payload)
    result.update(step.payload)
    if state.current_step_index is not None:
        result.setdefault("step_index", state.current_step_index)
    return result


def _event_log_entry(event: WorkEvent) -> EventLogEntry:
    return EventLogEntry(
        entry_id=f"{event.run_id}-entry-{event.sequence}",
        entry_type="event",
        operation_id=event.operation_id,
        event_id=event.event_id,
        run_id=event.run_id,
        session_id=event.session_id,
        sequence=event.sequence,
        payload={
            "kind": event.kind,
            "delivery_hint": event.delivery_hint,
            "payload": dict(event.payload),
            "source_event_ref": event.source_event_ref,
        },
        created_at=event.created_at,
    )


def _cancellation_error(outcome: WorkCancellationOutcome) -> Exception:
    error = outcome.error
    if isinstance(error, Exception):
        return error
    if error is not None:
        return WorkCancellationFailedError(
            f"domain cancellation failed: {type(error).__name__}: {error}"
        )
    return WorkCancellationFailedError("domain cancellation failed")


__all__ = [
    "DuplicateWorkOperationError",
    "UnknownWorkRunError",
    "WorkCancellationFailedError",
    "WorkCancellationTimeoutError",
    "WorkLifecycleOwnershipError",
    "WorkRunTerminalError",
    "WorkRuntime",
    "WorkRuntimeError",
]
