"""Scoped access to the optional Product Method/Work view; no domain executor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from loushang.appserver.execution.model import (
    ExecutionInterruptDispositionV1,
    ExecutionInterruptResultV1,
    ExecutionRecordV1,
)
from loushang.appserver.method_work import (
    MethodWorkCapabilityV1,
    MethodWorkError,
    MethodWorkHandleV1,
    MethodWorkObservationV1,
    MethodWorkQueryV1,
    MethodWorkSubmissionV1,
)
from loushang.appserver.protocol import SessionSnapshotRequestV1

from .execution_ports import HostedExecutionPortV1

if TYPE_CHECKING:
    from .execution_registry import ExecutionBindingV1
    from .execution_service import ScopedExecutionClientV1
    from .runtime import _SessionOwner


class HostedMethodWorkPortV1(HostedExecutionPortV1, Protocol):
    @property
    def method_work_capability(self) -> MethodWorkCapabilityV1: ...

    def query_method_work(self, execution_id: str) -> MethodWorkObservationV1: ...


class ScopedMethodWorkClientV1:
    """Borrow the original scope/registry; a handle is observation, not authority."""

    def __init__(self, execution: ScopedExecutionClientV1) -> None:
        self._execution = execution

    @property
    def service_instance_id(self) -> str:
        return self._execution.service_instance_id

    async def _resolve(
        self, control: SessionSnapshotRequestV1, instance: str,
    ) -> tuple[_SessionOwner, ExecutionBindingV1, HostedMethodWorkPortV1, MethodWorkCapabilityV1]:
        original = self._execution
        session, binding = await original._resolve(control, instance)
        config = original._scope._service._execution_config
        if config is None or config.select_work_port is None:
            raise MethodWorkError("unsupported")
        port = config.select_work_port(session._port)
        # Query and execution must refer to the same owned Product, not a sidecar.
        if port is None or port is not binding.port:
            raise MethodWorkError("unsupported")
        capability = port.method_work_capability
        if type(capability) is not MethodWorkCapabilityV1:
            raise TypeError("invalid Method capability")
        original._check(control, session)
        return session, binding, port, capability

    async def capability(self, control: SessionSnapshotRequestV1, instance: str) -> MethodWorkCapabilityV1:
        return (await self._resolve(control, instance))[3]

    async def submit(
        self, control: SessionSnapshotRequestV1, instance: str, submission_id: str, text: str,
    ) -> MethodWorkSubmissionV1:
        session, binding, _, capability = await self._resolve(control, instance)
        original = self._execution
        if not capability.accepting and original._registry.find(session.identity, submission_id) is None:
            raise MethodWorkError("unavailable")
        # No await between authority/owner validation and native admission.
        with original._scope.resume_subject_scope(control, submission_id=submission_id):
            record = original._registry.submit(binding, text, submission_id)
        return MethodWorkSubmissionV1(
            MethodWorkHandleV1(instance, capability.work_binding, record.state.execution_id), record,
        )

    async def find(
        self, control: SessionSnapshotRequestV1, instance: str, submission_id: str,
    ) -> MethodWorkSubmissionV1 | None:
        session, _, _, capability = await self._resolve(control, instance)
        record = self._execution._registry.find(session.identity, submission_id)
        if record is None:
            return None
        return MethodWorkSubmissionV1(
            MethodWorkHandleV1(instance, capability.work_binding, record.state.execution_id), record,
        )

    async def _target(
        self, control: SessionSnapshotRequestV1, handle: MethodWorkHandleV1,
    ) -> tuple[_SessionOwner, ExecutionBindingV1, HostedMethodWorkPortV1, ExecutionRecordV1]:
        if type(handle) is not MethodWorkHandleV1:
            raise MethodWorkError("invalid_handle")
        session, binding, port, capability = await self._resolve(control, handle.service_instance_id)
        record = self._execution._registry.get(session.identity, handle.execution_id)
        if capability.work_binding != handle.work_binding:
            raise MethodWorkError("binding_changed")
        return session, binding, port, record

    async def query(self, control: SessionSnapshotRequestV1, handle: MethodWorkHandleV1) -> MethodWorkQueryV1:
        session, _, port, record = await self._target(control, handle)
        observation = port.query_method_work(handle.execution_id)
        self._execution._check(control, session)
        if type(observation) is not MethodWorkObservationV1:
            raise TypeError("invalid Method Work observation")
        return MethodWorkQueryV1(handle, record, observation)

    async def interrupt(
        self, control: SessionSnapshotRequestV1, handle: MethodWorkHandleV1,
    ) -> ExecutionInterruptResultV1:
        _, binding, _, _ = await self._target(control, handle)
        record = self._execution._registry.interrupt(binding, handle.execution_id)
        return ExecutionInterruptResultV1(
            record, ExecutionInterruptDispositionV1.ALREADY_TERMINAL
            if record.state.status.terminal else ExecutionInterruptDispositionV1.REQUESTED,
        )

    async def wait(self, control: SessionSnapshotRequestV1, handle: MethodWorkHandleV1) -> MethodWorkQueryV1:
        _, binding, _, record = await self._target(control, handle)
        await self._execution._registry.wait(binding, record)
        # Delivery after an await requires fresh authority, not the old handle.
        return await self.query(control, handle)

    async def retry_settlement(
        self, control: SessionSnapshotRequestV1, handle: MethodWorkHandleV1,
    ) -> MethodWorkQueryV1:
        _, binding, _, _ = await self._target(control, handle)
        await self._execution._registry.retry_settlement(binding, handle.execution_id)
        return await self.query(control, handle)
