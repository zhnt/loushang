"""Scoped access to the optional Product Goal view; no domain executor."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from loushang.appserver.execution.model import (
    MAX_GOAL_BATCHES,
    ExecutionContentEventV1,
    ExecutionGoalBatchV1,
    ExecutionGoalCancellationStatusV1,
    ExecutionGoalProgressV1,
    ExecutionGoalStatusV1,
    ExecutionGoalValidityV1,
    ExecutionGoalWorkStatusV1,
    ExecutionInterruptDispositionV1,
    ExecutionInterruptResultV1,
    ExecutionRecordV1,
    ExecutionSessionSnapshotV1,
    ExecutionUpdateV1,
)
from loushang.appserver.goal import (
    GoalBatchObservationV1,
    GoalCapabilityV1,
    GoalHandleV1,
    GoalObservationV1,
    GoalQueryV1,
    GoalServiceError,
    GoalSubmissionV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionSnapshotRequestV1,
)

from .execution_ports import HostedExecutionPortV1

if TYPE_CHECKING:
    from .execution_registry import ExecutionBindingV1
    from .execution_service import ScopedExecutionClientV1
    from .runtime import _SessionOwner


class HostedGoalPortV1(HostedExecutionPortV1, Protocol):
    @property
    def goal_capability(self) -> GoalCapabilityV1: ...

    async def query_goal(self, execution_id: str) -> GoalObservationV1: ...


@runtime_checkable
class HostedGoalProgressPortV1(Protocol):
    """Optional extension of the same Product port, never a replacement owner."""

    async def progress_goal(self, execution_id: str) -> GoalObservationV1: ...


class ScopedGoalClientV1:
    """Borrow the original scope/registry; a handle is observation, not authority."""

    def __init__(self, execution: ScopedExecutionClientV1) -> None:
        self._execution = execution

    @property
    def service_instance_id(self) -> str:
        return self._execution.service_instance_id

    async def _resolve(
        self, control: SessionSnapshotRequestV1, instance: str,
    ) -> tuple[_SessionOwner, ExecutionBindingV1, HostedGoalPortV1, GoalCapabilityV1]:
        original = self._execution
        session, binding = await original._resolve(control, instance)
        config = original._scope._service._execution_config
        if config is None or config.select_goal_port is None:
            raise GoalServiceError("unsupported")
        port = config.select_goal_port(session._port)
        # Query and execution must refer to the same owned Product, not a sidecar.
        if port is None or port is not binding.port:
            raise GoalServiceError("unsupported")
        capability = port.goal_capability
        if type(capability) is not GoalCapabilityV1:
            raise TypeError("invalid Goal capability")
        if capability.supports_progress and not isinstance(port, HostedGoalProgressPortV1):
            raise TypeError("Goal progress capability requires its Product extension")
        original._check(control, session)
        # A fixed Goal is spent on admission, even if interrupted before Product entry.
        if capability.accepting and (binding.view.active is not None or binding.view.latest_terminal is not None):
            capability = replace(capability, accepting=False)
        return session, binding, port, capability

    async def capability(self, control: SessionSnapshotRequestV1, instance: str) -> GoalCapabilityV1:
        return (await self._resolve(control, instance))[3]

    async def start(
        self, control: SessionSnapshotRequestV1, instance: str, submission_id: str,
    ) -> GoalSubmissionV1:
        session, binding, _, capability = await self._resolve(control, instance)
        original = self._execution
        if not capability.accepting and original._registry.find(session.identity, submission_id) is None:
            raise GoalServiceError("unavailable")
        # No await between authority/owner validation and native admission.
        with original._scope.resume_subject_scope(control, submission_id=submission_id):
            record = original._registry.submit(binding, capability.profile, submission_id)
        return GoalSubmissionV1(
            GoalHandleV1(instance, capability.goal_binding, record.state.execution_id), record,
        )

    async def find(
        self, control: SessionSnapshotRequestV1, instance: str, submission_id: str,
    ) -> GoalSubmissionV1 | None:
        session, _, _, capability = await self._resolve(control, instance)
        record = self._execution._registry.find(session.identity, submission_id)
        if record is None:
            return None
        return GoalSubmissionV1(
            GoalHandleV1(instance, capability.goal_binding, record.state.execution_id), record,
        )

    async def _target(
        self, control: SessionSnapshotRequestV1, handle: GoalHandleV1,
    ) -> tuple[_SessionOwner, ExecutionBindingV1, HostedGoalPortV1, ExecutionRecordV1]:
        if type(handle) is not GoalHandleV1:
            raise GoalServiceError("invalid_handle")
        session, binding, port, capability = await self._resolve(control, handle.service_instance_id)
        record = self._execution._registry.get(session.identity, handle.execution_id)
        if capability.goal_binding != handle.goal_binding:
            raise GoalServiceError("binding_changed")
        return session, binding, port, record

    async def query(self, control: SessionSnapshotRequestV1, handle: GoalHandleV1) -> GoalQueryV1:
        session, _, port, record = await self._target(control, handle)
        observation = await port.query_goal(handle.execution_id)
        self._execution._check(control, session)
        if type(observation) is not GoalObservationV1:
            raise TypeError("invalid Goal observation")
        record = self._execution._registry.get(session.identity, handle.execution_id)
        return GoalQueryV1(handle, record, observation)

    async def interrupt(
        self, control: SessionSnapshotRequestV1, handle: GoalHandleV1,
    ) -> ExecutionInterruptResultV1:
        _, binding, _, _ = await self._target(control, handle)
        record = self._execution._registry.interrupt(binding, handle.execution_id)
        return ExecutionInterruptResultV1(
            record, ExecutionInterruptDispositionV1.ALREADY_TERMINAL
            if record.state.status.terminal else ExecutionInterruptDispositionV1.REQUESTED,
        )

    async def progress(self, control: SessionSnapshotRequestV1, handle: GoalHandleV1) -> GoalQueryV1:
        """Observe recorded progress without revalidating business completion."""
        _, _, port, _ = await self._target(control, handle)
        if not port.goal_capability.supports_progress:
            raise GoalServiceError("unsupported")
        if not isinstance(port, HostedGoalProgressPortV1):
            raise TypeError("invalid Goal progress port")
        observation = await port.progress_goal(handle.execution_id)
        _, _, current, record = await self._target(control, handle)
        if current is not port or not current.goal_capability.supports_progress:
            raise GoalServiceError("binding_changed")
        if type(observation) is not GoalObservationV1 or observation.validity not in {"not_checked", "unknown"}:
            raise TypeError("invalid Goal progress observation")
        return GoalQueryV1(handle, record, observation)

    async def wait(self, control: SessionSnapshotRequestV1, handle: GoalHandleV1) -> GoalQueryV1:
        _, binding, _, record = await self._target(control, handle)
        await self._execution._registry.wait(binding, record)
        # Delivery after an await requires fresh authority, not the old handle.
        return await self.query(control, handle)

    async def retry_settlement(
        self, control: SessionSnapshotRequestV1, handle: GoalHandleV1,
    ) -> GoalQueryV1:
        _, binding, _, _ = await self._target(control, handle)
        await self._execution._registry.retry_settlement(binding, handle.execution_id)
        return await self.query(control, handle)


class ScopedGoalExecutionObserverV1:
    """Execution delivery and narrow Goal controls borrowed from the existing scope."""

    def __init__(self, goal: ScopedGoalClientV1) -> None:
        self._goal = goal

    @property
    def service_instance_id(self) -> str:
        return self._goal.service_instance_id

    async def snapshot_execution_session(
        self, control: SessionSnapshotRequestV1, instance: str,
    ) -> ExecutionSessionSnapshotV1:
        snapshot = await self._goal._execution.snapshot_execution_session(control, instance)
        try:
            capability = await self._goal.capability(control, instance)
        except GoalServiceError:
            return snapshot
        return replace(
            snapshot, supports_goal_progress=capability.supports_progress,
            supports_goal_start=capability.accepting,
        )

    async def read_execution_events(
        self, control: SessionSnapshotRequestV1, instance: str,
    ) -> tuple[ExecutionContentEventV1 | ExecutionUpdateV1, ...]:
        return await self._goal._execution.read_execution_events(control, instance)

    async def goal_start(
        self, control: SessionSnapshotRequestV1, instance: str, submission_id: str,
    ) -> ExecutionRecordV1:
        try:
            return (await self._goal.start(control, instance, submission_id)).execution
        except GoalServiceError:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None

    async def goal_find(
        self, control: SessionSnapshotRequestV1, instance: str, submission_id: str,
    ) -> ExecutionRecordV1 | None:
        try:
            found = await self._goal.find(control, instance, submission_id)
        except GoalServiceError:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
        return None if found is None else found.execution

    async def goal_interrupt(
        self, control: SessionSnapshotRequestV1, instance: str, execution_id: str,
    ) -> ExecutionInterruptResultV1:
        try:
            return await self._goal.interrupt(control, await self._handle(control, instance, execution_id))
        except GoalServiceError:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None

    async def _handle(self, control: SessionSnapshotRequestV1, instance: str, execution_id: str) -> GoalHandleV1:
        capability = await self._goal.capability(control, instance)
        return GoalHandleV1(instance, capability.goal_binding, execution_id)

    async def goal_progress(
        self, control: SessionSnapshotRequestV1, instance: str, execution_id: str,
    ) -> ExecutionGoalProgressV1:
        try:
            observed = await self._goal.progress(control, await self._handle(control, instance, execution_id))
        except GoalServiceError:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
        view = observed.observation
        # Product strings are checked by the wire value before publication.
        return ExecutionGoalProgressV1(
            execution_id, view.presence, view.goal_id,
            cast(ExecutionGoalStatusV1 | None, view.status),
            view.reason_code, cast(ExecutionGoalValidityV1, view.validity),
            view.execution_unresolved, view.advances, view.model_calls, len(view.batches),
            tuple(_batch_summary(batch) for batch in view.batches[-MAX_GOAL_BATCHES:]),
        )


def _batch_summary(batch: GoalBatchObservationV1) -> ExecutionGoalBatchV1:
    return ExecutionGoalBatchV1(
        batch_id=batch.batch_id,
        work_status=cast(ExecutionGoalWorkStatusV1, batch.work.status) if batch.work else None,
        recording_available=batch.recording is not None,
        cancellation_status=cast(ExecutionGoalCancellationStatusV1, batch.cancellation.status)
        if batch.cancellation else None,
        observation_unavailable=bool(batch.errors),
    )
