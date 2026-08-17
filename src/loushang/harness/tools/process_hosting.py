"""Execution-scope-bound authorization adapter for hosted process starts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, cast

from loushang.harness.approval import ApprovalResolver, approval_actor_id
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
)
from loushang.harness.effects import ProcessEffect
from loushang.harness.policy import PolicyEvaluator
from loushang.harness.tools.execution import (
    AuthorizedToolAction,
    AuthorizedToolContext,
    PreparedToolAction,
)
from loushang.harness.tools.workspace.authorization import (
    WorkspaceToolAuthorizationGateway,
)
from loushang.harness.workspace.process.host import ProcessHost
from loushang.harness.workspace.process.local import (
    ProcessContainmentPlan,
    ProcessContainmentPlanner,
)
from loushang.harness.workspace.process.types import ProcessHandle, ProcessLaunchRequest

_PROCESS_START_ACTION = "process.host.start"
ProcessAuditSink = Callable[
    [Mapping[str, object]],
    Awaitable[None] | None,
]


@dataclass(frozen=True, slots=True)
class ProcessExecutionScope:
    """Immutable non-model authority bound to one process launcher."""

    policy_evaluator: PolicyEvaluator | None = field(default=None, repr=False)
    approval_resolver: ApprovalResolver | None = field(default=None, repr=False)
    audit_sink: ProcessAuditSink | None = field(default=None, repr=False)
    execution_profile_ceiling: EffectiveExecutionProfile | None = None

    def __post_init__(self) -> None:
        if self.audit_sink is not None and not callable(self.audit_sink):
            raise TypeError("process execution scope audit sink must be callable")
        if self.execution_profile_ceiling is not None and not isinstance(
            self.execution_profile_ceiling,
            EffectiveExecutionProfile,
        ):
            raise TypeError(
                "process execution scope ceiling must be an EffectiveExecutionProfile"
            )

    @property
    def actor_id(self) -> str:
        return approval_actor_id(self.approval_resolver)


class HostedProcessContainmentPort(Protocol):
    async def plan(
        self,
        request: ProcessLaunchRequest,
        *,
        execution_profile: EffectiveExecutionProfile | None,
    ) -> ProcessContainmentPlan: ...


@dataclass(frozen=True, slots=True)
class _ExecutionProfileCarrier:
    execution_profile: EffectiveExecutionProfile | None


class ScopeBoundProcessLauncher:
    """Authorize one exact spawn, then delegate ownership to ProcessHost."""

    def __init__(
        self,
        *,
        scope: ProcessExecutionScope,
        host: ProcessHost,
        containment: HostedProcessContainmentPort,
    ) -> None:
        if not isinstance(scope, ProcessExecutionScope):
            raise TypeError("process launcher requires ProcessExecutionScope")
        self._scope = scope
        self._host = host
        self._containment = containment
        self._gateway = WorkspaceToolAuthorizationGateway(
            policy_evaluator=scope.policy_evaluator,
            approval_resolver=scope.approval_resolver,
        )

    @property
    def scope_actor_id(self) -> str:
        return self._scope.actor_id

    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ProcessHandle:
        if not isinstance(request, ProcessLaunchRequest):
            raise TypeError("process launcher requires ProcessLaunchRequest")
        if not isinstance(correlation_id, str) or not correlation_id:
            raise ValueError("process launch correlation_id must be non-empty")
        _raise_if_aborted(signal)
        launch_fingerprint = _process_launch_fingerprint(request)
        authorization_arguments: Mapping[str, Any] = MappingProxyType(
            {
                "command": request.command,
                "launch_fingerprint": launch_fingerprint,
            }
        )
        prepared = PreparedToolAction(
            tool_name=_PROCESS_START_ACTION,
            authorization_arguments=authorization_arguments,
            execution_arguments=authorization_arguments,
            cwd=request.cwd,
            effects=(ProcessEffect(request.command),),
            execution_environment=request.effective_environment,
        )
        context = AuthorizedToolContext(
            tool_call_id=correlation_id,
            signal=signal,
            event_sink=self._scope.audit_sink,
            exec_service=_ExecutionProfileCarrier(
                self._scope.execution_profile_ceiling
            ),
        )

        async def launch(
            action: AuthorizedToolAction,
            _context: AuthorizedToolContext,
        ) -> ProcessHandle:
            del _context
            _raise_if_aborted(signal)
            if action.actor_id != self._scope.actor_id:
                raise ExecutionAuthorizationError(
                    "process launch actor changed before execution"
                )
            if _process_launch_fingerprint(request) != launch_fingerprint:
                raise ExecutionAuthorizationError(
                    "process launch material changed before execution"
                )
            _validate_process_cwd(request, action.execution_profile)

            async def plan(
                frozen_request: ProcessLaunchRequest,
            ) -> ProcessContainmentPlan:
                return await self._containment.plan(
                    frozen_request,
                    execution_profile=action.execution_profile,
                )

            return await self._host.start(
                request,
                containment_planner=cast(ProcessContainmentPlanner, plan),
            )

        return await self._gateway.execute(prepared, launch, context)


def _process_launch_fingerprint(request: ProcessLaunchRequest) -> str:
    payload = json.dumps(
        {
            "command": request.command,
            "cwd": request.cwd,
            "effective_environment": sorted(request.effective_environment),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _validate_process_cwd(
    request: ProcessLaunchRequest,
    profile: EffectiveExecutionProfile | None,
) -> None:
    if profile is None:
        return
    cwd = Path(request.cwd)
    if any(cwd == root or cwd.is_relative_to(root) for root in profile.denied_roots):
        raise ExecutionAuthorizationError(
            f"process cwd is denied by execution profile: {cwd}"
        )
    if not any(
        cwd == root or cwd.is_relative_to(root) for root in profile.readable_roots
    ):
        raise ExecutionAuthorizationError(
            f"process cwd is outside the authorized readable roots: {cwd}"
        )


def _raise_if_aborted(signal: object | None) -> None:
    if signal is not None and getattr(signal, "aborted", False):
        raise RuntimeError("Operation aborted")


__all__ = ["ProcessExecutionScope"]
