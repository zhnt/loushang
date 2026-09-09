"""Explicit execution composition and scoped semantic client capability."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loushang.appserver.execution.model import (
    ExecutionInterruptDispositionV1,
    ExecutionInterruptResultV1,
    ExecutionSessionSnapshotV1,
    ExecutionSessionViewV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionSnapshotRequestV1,
)

from .execution_contract import _identifier
from .execution_ports import HostedExecutionPortV1
from .execution_registry import (
    ExecutionBindingV1,
    ExecutionLimitsV1,
    ExecutionRecordV1,
    ExecutionRegistryV1,
)
from .execution_snapshot import (
    ExecutionDeliveryV1,
    ExecutionSnapshotBufferV1,
    capture_execution_snapshot,
)
from .ports import HostedSessionPortV1

if TYPE_CHECKING:
    from .client_scope import AppClientScopeV1
    from .runtime import _SessionOwner


@dataclass(frozen=True, slots=True)
class HostedExecutionServiceBindingV1:
    application_id: str
    service_instance_id: str
    select_port: Callable[[HostedSessionPortV1], HostedExecutionPortV1 | None]
    limits: ExecutionLimitsV1 = ExecutionLimitsV1()

    def __post_init__(self) -> None:
        _identifier(self.application_id)
        _identifier(self.service_instance_id)
        if not callable(self.select_port) or type(self.limits) is not ExecutionLimitsV1:
            raise TypeError("invalid execution service binding")


@dataclass(slots=True)
class _Stream:
    buffer: ExecutionSnapshotBufferV1
    unsubscribe_content: Callable[[], None]
    unsubscribe_metadata: Callable[[], None]
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.buffer.invalidate()
        try:
            self.unsubscribe_content()
        finally:
            self.unsubscribe_metadata()


class ScopedExecutionClientV1:
    """Borrowed capability; every operation proves current controller authority.

    A snapshot replaces this member's bounded two-stream subscription. Losing
    the client scope discards delivery, while the registry keeps execution.
    """

    def __init__(self, scope: AppClientScopeV1, registry: ExecutionRegistryV1) -> None:
        self._scope, self._registry = scope, registry
        self._streams: dict[tuple[str, str], _Stream] = {}

    @property
    def service_instance_id(self) -> str:
        self._scope._require_open()
        return self._registry.service_instance_id

    def _check(self, control: SessionSnapshotRequestV1, session: _SessionOwner) -> None:
        self._scope._require_current_session(control, session)

    async def _resolve(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> tuple[_SessionOwner, ExecutionBindingV1]:
        scope = self._scope
        scope._service._require_request(control, SessionSnapshotRequestV1)
        session = await scope._session(
            control.attachment_id, control.controller_generation, control.member_id
        )
        self._check(control, session)
        self._registry.require_instance(expected_instance_id)
        binding = scope._service._execution_binding(session)
        self._check(control, session)
        return session, binding

    async def submit_execution(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        submission_id: str, text: str,
    ) -> ExecutionRecordV1:
        _, binding = await self._resolve(control, expected_instance_id)
        # Duplicate lookup precedes every capacity check. No communication slot
        # is reserved and no await separates this authority cut from admission.
        return self._registry.submit(binding, text, submission_id)

    async def get_execution(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        execution_id: str,
    ) -> ExecutionRecordV1:
        session, _ = await self._resolve(control, expected_instance_id)
        return self._registry.get(session.identity, execution_id)

    async def find_execution_by_submission(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        submission_id: str,
    ) -> ExecutionRecordV1 | None:
        session, _ = await self._resolve(control, expected_instance_id)
        return self._registry.find(session.identity, submission_id)

    async def interrupt_execution(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        execution_id: str,
    ) -> ExecutionInterruptResultV1:
        _, binding = await self._resolve(control, expected_instance_id)
        record = self._registry.interrupt(binding, execution_id)
        return ExecutionInterruptResultV1(
            record, ExecutionInterruptDispositionV1.ALREADY_TERMINAL if record.state.status.terminal
            else ExecutionInterruptDispositionV1.REQUESTED,
        )

    async def snapshot_execution_session(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> ExecutionSessionSnapshotV1:
        session, binding = await self._resolve(control, expected_instance_id)
        key = control.attachment_id, control.member_id
        prior = self._streams.pop(key, None)
        if prior is not None:
            prior.close()
        if len(self._streams) >= 64:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        buffer = ExecutionSnapshotBufferV1(binding.view.binding, session.identity)
        unsubscribe_content = binding.port.subscribe_execution_content(buffer.push)
        try:
            unsubscribe_metadata = binding.subscribe(buffer.push)
        except BaseException:
            unsubscribe_content()
            raise
        stream = _Stream(buffer, unsubscribe_content, unsubscribe_metadata)
        self._streams[key] = stream

        def read_view():
            self._check(control, session)
            if self._streams.get(key) is not stream:
                raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)
            return binding.view

        try:
            snapshot = await capture_execution_snapshot(binding.port, read_view, buffer)
            self._consume_legacy_copy(control, buffer)
            view = snapshot.executions
            return ExecutionSessionSnapshotV1(
                self.service_instance_id, snapshot.source,
                ExecutionSessionViewV1(
                    view.identity, view.revision, view.quiescent, view.active, view.latest_terminal
                ),
            )
        except BaseException:
            if self._streams.get(key) is stream:
                self._streams.pop(key)
            stream.close()
            raise

    async def read_execution_events(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> tuple[ExecutionDeliveryV1, ...]:
        session, binding = await self._resolve(control, expected_instance_id)
        self._check(control, session)
        stream = self._streams.get((control.attachment_id, control.member_id))
        if stream is None:
            raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
        stream.buffer.require_current(binding.view)
        events = stream.buffer.read()
        self._consume_legacy_copy(control, stream.buffer)
        return events

    def _consume_legacy_copy(
        self, control: SessionSnapshotRequestV1, buffer: ExecutionSnapshotBufferV1,
    ) -> None:
        # Both envelopes carry the same Product content. Consuming the optional
        # projection also consumes its covered legacy copy, preventing an unused
        # legacy queue from revoking an otherwise healthy execution attachment.
        _, attachment = self._scope._service._attachments[control.attachment_id]
        for event in attachment._drain_raw():
            if event.member_id != control.member_id or event.event.cursor > buffer.content_cursor:
                attachment._put(event)

    def detach(self, attachment_id: str | None = None) -> None:
        for key, stream in tuple(self._streams.items()):
            if attachment_id is None or key[0] == attachment_id:
                self._streams.pop(key)
                stream.close()
