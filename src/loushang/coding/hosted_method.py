"""Opt-in application-local hosted Method execution on the AppHost-owned Session."""

from __future__ import annotations

from dataclasses import replace
from secrets import token_hex
from typing import cast

from loushang.appserver.method_work import (
    MethodWorkCapabilityV1,
    MethodWorkObservationV1,
)
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.appservice.execution_contract import ExecutionRequestV1, InterruptModeV1
from loushang.appservice.execution_registry import ExecutionLimitsV1
from loushang.appservice.execution_service import HostedExecutionServiceBindingV1
from loushang.harnesswork import InMemoryEventLogBackend
from loushang.harnesswork.integrations.session import SessionWorkRuntime
from loushang.harnesswork.types import WorkRecordingPolicy

from ._hosted_method_config import CodingHostedMethodV1 as CodingHostedMethodV1
from ._hosted_method_work import MethodInvocation, MethodPrompt
from ._hosted_work_observation import observe_work_run
from .adapters.harnesswork import create_coding_work_runtime
from .appservice_adapter import CodingHostedSessionBindingV1
from .hosted_execution import CodingHostedExecutionSessionV1
from .hosted_session import CodingRealHostedSessionV1
from .session.agent_session import AgentSession


class CodingHostedMethodSessionV1(CodingHostedExecutionSessionV1):
    def __init__(
        self, binding: CodingRealHostedSessionV1, method: CodingHostedMethodV1,
        *, owner: CodingHostedSessionBindingV1 | None = None,
    ) -> None:
        if type(binding) is not CodingRealHostedSessionV1 or type(method) is not CodingHostedMethodV1:
            raise TypeError("hosted Method requires a fresh real Coding binding and fixed selection")
        super().__init__(binding, owner=owner)
        self._method = method
        self._capability = MethodWorkCapabilityV1(token_hex(16), method.descriptor.id, method.digest, method.max_steps)
        self._latest: MethodInvocation | None = None
        self._work: SessionWorkRuntime | None = create_coding_work_runtime(
            session=MethodPrompt(cast(AgentSession, binding.control), self._current),
            event_log=InMemoryEventLogBackend(), session_id=lambda: self.identity.session_id,
            recording_policy=WorkRecordingPolicy(),
        )

    def _current(self) -> MethodInvocation:
        assert self._latest is not None
        return self._latest

    @property
    def method_work_capability(self) -> MethodWorkCapabilityV1:
        self._require_execution_open()
        return replace(self._capability, accepting=self._latest is None or not self._latest.recording_unavailable)

    def start_execution(self, request: ExecutionRequestV1) -> None:
        self._require_execution_open()
        if self._latest is not None and self._latest.recording_unavailable:
            # An invalid confirmation view is not repaired by clearing an
            # active run. Keep reads/cleanup but retire this owner's admission.
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        if not self._product_binding.execution_available:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        assert self._work is not None
        invocation = MethodInvocation(
            cast(AgentSession, self._product_binding.control), self._work, self._method,
            request.execution_id, request.text, lambda: self._guard.interrupt_requested,
        )
        self._guard.start(request, invocation)
        self._latest = invocation

    async def start_turn(self, text: str) -> None:
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    def steer_turn(self, text: str) -> None:
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    def follow_up_turn(self, text: str) -> None:
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    def interrupt_turn(self) -> bool:
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    def interrupt_execution(self, execution_id: str, mode: InterruptModeV1) -> bool:
        if mode is not InterruptModeV1.WHOLE_EXECUTION:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return super().interrupt_execution(execution_id, mode)

    def query_method_work(self, execution_id: str) -> MethodWorkObservationV1:
        self._require_execution_open()
        assert self._work is not None
        runtime = self._work.work_runtime
        try:
            run = runtime.get_run_for_operation(execution_id)
        except Exception:
            return MethodWorkObservationV1("unknown", errors=("work_observation_unavailable",))
        if run is None:
            latest, state = self._latest, self.execution_state
            if latest is not None and latest.execution_id == execution_id and latest.not_submitted:
                return MethodWorkObservationV1("not_submitted")
            if (state is not None and state.execution_id == execution_id and not state.status.terminal
                    and not state.interrupt_requested and latest is not None
                    and (latest.task is None or not latest.task.done())):
                return MethodWorkObservationV1("not_yet_observed")
            return MethodWorkObservationV1("unknown")
        return observe_work_run(runtime, run, max_steps=self._method.max_steps)

    async def _close_execution(self) -> None:
        state = self._guard.state
        if state is not None and not state.status.terminal:
            self._guard.interrupt(state.execution_id, InterruptModeV1.WHOLE_EXECUTION)
            await self._guard.retry_settlement(state.execution_id)
        if self._work is not None:
            await self._work.dispose()
        # Retain everything until the actual Session/lease has closed successfully.
        await super()._close_execution()
        if self._latest is not None:
            # Guard retains its latest invocation after close. Disconnect the
            # owned Work graph, not just the outer reference to that invocation.
            self._latest.task = None
            self._latest.step = None
            self._latest.runtime = None  # type: ignore[assignment]
        self._latest = None
        self._work = None


def create_coding_method_service_binding(
    application_id: str, *, service_instance_id: str | None = None,
    limits: ExecutionLimitsV1 = ExecutionLimitsV1(active=1, submissions=8),
) -> HostedExecutionServiceBindingV1:
    """Fixed-Method SDK profile; default prompt services are unaffected."""
    def select(port):  # type: ignore[no-untyped-def]
        return port if isinstance(port, CodingHostedMethodSessionV1) else None

    return HostedExecutionServiceBindingV1(
        application_id, service_instance_id or token_hex(16), select, limits, select,
    )
