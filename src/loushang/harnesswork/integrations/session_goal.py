"""Goal-specific bridge into the original Session admission and Work resolver.

Domain planning, requirements and acceptance stay in their injected policies.
The Session scope owns task/cleanup mechanics; this bridge owns only the Goal
association with its one pending reservation and canonical prepared Work slot.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

from loushang.harness.session.execution_admission import (
    ExecutionReservation,
    SessionExecutionAdmission,
    SessionExecutionUnavailable,
)
from loushang.harness.session.execution_scope import SessionExecutionScope
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.contracts import (
    GoalAcceptancePolicy,
    GoalAssessment,
    GoalBasis,
    GoalFacts,
    NextWorkPolicy,
    PolicyStop,
    WorkCandidate,
)
from loushang.harnesswork.goal.controller import GoalController
from loushang.harnesswork.integrations.session import SessionWorkRuntime
from loushang.harnesswork.ports import WorkExecutionBinding
from loushang.harnesswork.types import WorkRecordingPolicy


class _AdmittedExecutor:
    def __init__(self, delegate, reservation: ExecutionReservation, cancellation=None):
        self._delegate, self._reservation = delegate, reservation
        self._cancellation = cancellation
        self._task: asyncio.Task | None = None
        self._done = asyncio.Event()
        self._done.set()
        self._error: BaseException | None = None

    async def execute(self, operation, context):
        if operation.operation_id != self._reservation.operation_id:
            raise GoalError("Session reservation and Work operation differ")
        if context.cancellation_requested:
            raise asyncio.CancelledError
        self._task, self._error = asyncio.current_task(), None
        self._done.clear()
        try:
            with self._reservation.executing():
                return await self._delegate.execute(operation, context)
        except BaseException as error:
            self._error = error
            raise
        finally:
            self._task = None
            self._done.set()

    async def cancel_and_wait(self, operation, context):
        outcome = await self._cancellation.cancel_and_wait(operation, context)
        if outcome.status == "settled":
            # Domain idle alone can precede execution (e.g. before a command
            # starts). Stop and join the original admitted invocation as well.
            # Its Work task catches cancellation and awaits this port, so join
            # the invocation boundary, never that entire Task.
            task = self._task
            if task is not None:
                task.cancel()
                await self._done.wait()
            if self._error is not None and not isinstance(self._error, asyncio.CancelledError):
                raise self._error
        return outcome


class SessionGoalCoordinator:
    def __init__(
        self, *, admission: SessionExecutionAdmission, scope: SessionExecutionScope,
        work: SessionWorkRuntime, next_work: NextWorkPolicy, acceptance: GoalAcceptancePolicy,
        binding: Callable[[WorkCandidate, ExecutionReservation], WorkExecutionBinding],
        release_configuration: Callable[[ExecutionReservation], None],
        allow_queued_input: Callable[[WorkCandidate], bool],
        recording_policy: WorkRecordingPolicy | None = None,
    ) -> None:
        self.admission, self.scope, self.work = admission, scope, work
        self.next_work, self.acceptance = next_work, acceptance
        self._binding, self._release_configuration = binding, release_configuration
        self._allow_queued_input = allow_queued_input
        self._recording_policy = recording_policy
        self.reservation: ExecutionReservation | None = None
        self._assessment: tuple[GoalAssessment, tuple[int, int]] | None = None

    async def advance(
        self, controller: GoalController, goal_id: str, *,
        advance: Callable[..., Awaitable], **command,
    ):
        # Original idempotent command reads remain available while other Session
        # input is active; they never acquire new execution authority.
        if command.get("command_id") in controller.history.commands:
            return await advance(goal_id, **command)

        async def invoke():
            try:
                self.reservation = self.admission.reserve_candidate()
            except SessionExecutionUnavailable as error:
                raise GoalError(str(error)) from error
            try:
                return await advance(goal_id, **command)
            finally:
                self.release()

        return await self.scope.invoke(invoke)

    def current_execution(self) -> ExecutionReservation:
        reservation = self.reservation
        if reservation is None:
            raise GoalError("Goal has no Session execution reservation")
        self.admission.check_execution(reservation)
        return reservation

    async def prepare(self, basis: GoalBasis, facts: GoalFacts) -> WorkCandidate | PolicyStop:
        reservation = self.reservation
        if reservation is None:
            raise GoalError("Goal preparation has no Session reservation")
        candidate = await self.next_work.prepare(basis, facts)
        if isinstance(candidate, PolicyStop):
            return candidate
        if self._recording_policy is not None:
            candidate = replace(candidate, spec=replace(candidate.spec, recording_policy=self._recording_policy))
        try:
            reservation.bind_operation(candidate.operation.operation_id)
        except SessionExecutionUnavailable:
            return PolicyStop("session_input_or_identity_changed")
        if self._allow_queued_input(candidate):
            reservation.allow_queued_input()
        binding = self._binding(candidate, reservation)
        executor = _AdmittedExecutor(binding.executor, reservation, binding.cancellation)
        self.work.prepare_binding(
            candidate.operation.operation_id,
            replace(binding, executor=executor,
                    cancellation=executor if binding.cancellation is not None else None),
            commit=reservation.commit,
        )
        return candidate

    def confirm_candidate(self, candidate: WorkCandidate) -> bool:
        if self.reservation is None or self.reservation.operation_id != candidate.operation.operation_id:
            return False
        try:
            self.admission.validate_reservation(self.reservation)
            valid = self.next_work.confirm_candidate(candidate)
            self.admission.validate_reservation(self.reservation)
            return valid
        except SessionExecutionUnavailable:
            return False

    def confirm_resume(self, basis: GoalBasis, facts: GoalFacts) -> bool | PolicyStop:
        try:
            reservation = self.admission.reserve_candidate()
        except SessionExecutionUnavailable:
            return PolicyStop("session_input_or_execution_pending")
        try:
            ready = self.next_work.confirm_resume(basis, facts)
            self.admission.validate_reservation(reservation, require_operation=False)
            return ready
        except SessionExecutionUnavailable:
            return PolicyStop("session_input_or_identity_changed")
        finally:
            reservation.release()

    async def assess(self, basis: GoalBasis, facts: GoalFacts) -> GoalAssessment:
        reservation = self.reservation
        if reservation is None:
            raise GoalError("Goal assessment has no Session reservation")
        self._assessment = None
        try:
            before = self.admission.observe_execution(reservation)
            assessment = await self.acceptance.assess(basis, facts)
            if self.admission.observe_execution(reservation) != before:
                raise SessionExecutionUnavailable("Session changed during assessment")
        except SessionExecutionUnavailable:
            return GoalAssessment(basis, "needs_user", "session_input_or_identity_changed")
        self._assessment = assessment, before
        return assessment

    def confirm_current(self, assessment: GoalAssessment) -> bool:
        if self.reservation is None or self._assessment is None or self._assessment[0] is not assessment:
            return False
        try:
            valid = self.acceptance.confirm_current(assessment)
            return valid and self.admission.observe_execution(self.reservation) == self._assessment[1]
        except SessionExecutionUnavailable:
            return False

    def release(self) -> None:
        reservation = self.reservation
        if reservation is None:
            return
        operation_id = reservation.operation_id
        if operation_id is not None:
            self.work.discard_binding(operation_id)
        if reservation.state in {"committed", "settling"}:
            run = self.work.work_runtime.get_run_for_operation(operation_id or "")
            if run is None or run.status not in {"completed", "failed", "cancelled"}:
                raise GoalError("Session execution admission remains unresolved")
            cancellation = self.work.work_runtime.get_cancellation(run.run_id)
            if cancellation.basis != "journal" or cancellation.status not in {"not_requested", "settled"}:
                raise GoalError("Session execution settlement remains unresolved")
            self._release_configuration(reservation)
            reservation.begin_settling()
        reservation.release()
        self.reservation = None
        self._assessment = None


class SessionGoalController(GoalController):
    """Keep the original public controller's advance inside its Session bridge.

    Control, storage and execution remain the inherited canonical implementation.
    Both the Product facade and callers retaining its controller use this one
    reservation path, including cached command reads.
    """

    def __init__(self, *, coordinator: SessionGoalCoordinator, **kwargs):
        super().__init__(**kwargs)
        self._session_coordinator = coordinator

    async def advance(self, goal_id: str, *, command_id: str, revision: int, epoch: int):
        return await self._session_coordinator.advance(
            self, goal_id, advance=super().advance, command_id=command_id,
            revision=revision, epoch=epoch,
        )


class SessionGoalPrompt:
    """Narrow prompt port: pass the accepted reservation explicitly."""

    def __init__(self, session, execution: Callable[[], ExecutionReservation], *,
                 before_prompt: Callable[[ExecutionReservation], Callable[[], None] | None],
                 stop: Callable[[], None]):
        self._session, self._execution = session, execution
        self._before_prompt, self._stop = before_prompt, stop
        self._interrupted = False

    def subscribe_runtime_events(self, listener):
        return self._session.subscribe_runtime_events(listener)

    async def prompt(self, text, *, images=None, streaming_behavior=None, source=None):
        if streaming_behavior is not None:
            raise GoalError("bound Work cannot start a separate steering turn")
        execution = self._execution()
        cleanup = self._before_prompt(execution)
        try:
            try:
                await self._session.prompt_in_execution(execution, text, images=list(images) if images else None, source=source)
            except BaseException:
                await self._session.settle_execution(interrupted=True)
                raise
            else:
                await self._session.settle_execution()
        finally:
            if cleanup is not None:
                cleanup()

    def abort(self):
        self._interrupted = True
        self._stop()
        return self._session.abort()

    async def wait_for_idle(self):
        await self._session.settle_execution(interrupted=self._interrupted)
        self._interrupted = False
