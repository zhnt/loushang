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
from loushang.harness.effects import (
    FilesystemEffect,
    NetworkEffect,
    ProcessEffect,
    PublicationEffect,
    ToolEffect,
    effect_snapshot,
)
from loushang.harness.policy import (
    PolicyDecision,
    PolicyEvaluator,
    PolicySubject,
    evaluate_policy,
)
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
_PROCESS_OWNER_AUTHORITY = object()
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
    require_approval: bool = False

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
        if type(self.require_approval) is not bool:
            raise TypeError("process execution scope require_approval must be a bool")

    @property
    def actor_id(self) -> str:
        return approval_actor_id(self.approval_resolver)


class HostedProcessContainmentPort(Protocol):
    @property
    def requirement(self) -> str: ...

    async def plan(
        self,
        request: ProcessLaunchRequest,
        *,
        execution_profile: EffectiveExecutionProfile | None,
    ) -> ProcessContainmentPlan: ...


@dataclass(frozen=True, slots=True)
class _ExecutionProfileCarrier:
    execution_profile: EffectiveExecutionProfile | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _ManagedProcessLaunchRequest(ProcessLaunchRequest):
    declared_effects: tuple[ToolEffect, ...] = ()
    authorization_metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({}),
        repr=False,
    )
    pre_start_validator: Callable[[], None] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        super(_ManagedProcessLaunchRequest, self).__post_init__()
        effects = tuple(self.declared_effects)
        if any(
            not isinstance(
                effect,
                FilesystemEffect
                | NetworkEffect
                | ProcessEffect
                | PublicationEffect,
            )
            for effect in effects
        ):
            raise TypeError("managed process effects must contain ToolEffect values")
        if not isinstance(self.authorization_metadata, Mapping) or any(
            not isinstance(key, str) for key in self.authorization_metadata
        ):
            raise TypeError("managed process metadata must be a string-key mapping")
        if not callable(self.pre_start_validator):
            raise TypeError("managed process pre-start validator must be callable")
        object.__setattr__(self, "declared_effects", effects)
        object.__setattr__(
            self,
            "authorization_metadata",
            MappingProxyType(dict(self.authorization_metadata)),
        )


def _managed_process_launch_request(
    *,
    command: tuple[str, ...],
    cwd: str,
    effective_environment: tuple[tuple[str, str], ...],
    declared_effects: tuple[ToolEffect, ...],
    authorization_metadata: Mapping[str, object],
    pre_start_validator: Callable[[], None],
) -> ProcessLaunchRequest:
    """Build the private Approval envelope without widening the public request."""

    return _ManagedProcessLaunchRequest(
        command=command,
        cwd=cwd,
        effective_environment=effective_environment,
        declared_effects=declared_effects,
        authorization_metadata=authorization_metadata,
        pre_start_validator=pre_start_validator,
        stream_stderr=True,
    )


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
        self._managed_owner_authority: object | None = None
        self._gateway = WorkspaceToolAuthorizationGateway(
            policy_evaluator=(
                _MandatoryProcessApprovalPolicy(scope.policy_evaluator)
                if scope.require_approval
                else scope.policy_evaluator
            ),
            approval_resolver=scope.approval_resolver,
        )

    @property
    def approval_required(self) -> bool:
        return self._scope.require_approval

    @property
    def containment_requirement(self) -> str:
        return getattr(self._containment, "requirement", "best_effort")

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
        if isinstance(request, _ManagedProcessLaunchRequest):
            raise TypeError("managed process requests require the owner-only start path")
        return await self._start_authorized(
            request,
            correlation_id=correlation_id,
            signal=signal,
        )

    async def _start_managed(
        self,
        request: ProcessLaunchRequest,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ProcessHandle:
        if self._managed_owner_authority is not _PROCESS_OWNER_AUTHORITY:
            raise ExecutionAuthorizationError(
                "managed process start requires a Process-owner-minted launcher"
            )
        if type(request) is not _ManagedProcessLaunchRequest:
            raise TypeError("managed process start requires an owner-minted request")
        if not self._scope.require_approval:
            raise ExecutionAuthorizationError(
                "managed process start requires mandatory Approval"
            )
        if self.containment_requirement != "required":
            raise ExecutionAuthorizationError(
                "managed process start requires required containment"
            )
        return await self._start_authorized(
            request,
            correlation_id=correlation_id,
            signal=signal,
        )

    async def _start_authorized(
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
                "metadata": _authorization_metadata(request),
            }
        )
        prepared = PreparedToolAction(
            tool_name=_PROCESS_START_ACTION,
            authorization_arguments=authorization_arguments,
            execution_arguments=authorization_arguments,
            cwd=request.cwd,
            effects=(ProcessEffect(request.command), *_declared_effects(request)),
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
            validator = _pre_start_validator(request)

            async def plan(
                frozen_request: ProcessLaunchRequest,
            ) -> ProcessContainmentPlan:
                containment_plan = await self._containment.plan(
                    frozen_request,
                    execution_profile=action.execution_profile,
                )
                # Approval and containment planning may be arbitrarily slow.  Keep
                # mutable host-runtime evidence fresh at the final owner boundary,
                # immediately before ProcessHost hands the plan to its spawner.
                if validator is not None:
                    validator()
                return containment_plan

            return await self._host.start(
                request,
                containment_planner=cast(ProcessContainmentPlanner, plan),
            )

        return await self._gateway.execute(prepared, launch, context)


def _bind_process_owner_launcher(
    *,
    scope: ProcessExecutionScope,
    host: ProcessHost,
    containment: HostedProcessContainmentPort,
) -> ScopeBoundProcessLauncher:
    """Mint the managed-start authority only at the Sandbox/Process owner seam."""

    if type(host) is not ProcessHost:
        raise TypeError("managed process owner requires the exact ProcessHost")
    launcher = ScopeBoundProcessLauncher(
        scope=scope,
        host=host,
        containment=containment,
    )
    launcher._managed_owner_authority = _PROCESS_OWNER_AUTHORITY
    return launcher


def _process_launch_fingerprint(request: ProcessLaunchRequest) -> str:
    payload = json.dumps(
        {
            "command": request.command,
            "cwd": request.cwd,
            "effective_environment": sorted(request.effective_environment),
            "declared_effects": [
                effect_snapshot(effect) for effect in _declared_effects(request)
            ],
            "authorization_metadata": dict(_authorization_metadata(request)),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _declared_effects(request: ProcessLaunchRequest) -> tuple[ToolEffect, ...]:
    if isinstance(request, _ManagedProcessLaunchRequest):
        return request.declared_effects
    return ()


def _authorization_metadata(request: ProcessLaunchRequest) -> Mapping[str, object]:
    if isinstance(request, _ManagedProcessLaunchRequest):
        return request.authorization_metadata
    return MappingProxyType({})


def _pre_start_validator(
    request: ProcessLaunchRequest,
) -> Callable[[], None] | None:
    if isinstance(request, _ManagedProcessLaunchRequest):
        return request.pre_start_validator
    return None


@dataclass(frozen=True, slots=True)
class _MandatoryProcessApprovalPolicy:
    delegate: PolicyEvaluator | None

    async def evaluate(self, subject: PolicySubject, /) -> PolicyDecision:
        decision = (
            None
            if self.delegate is None
            else await evaluate_policy(self.delegate, subject)
        )
        if decision is not None and decision.disposition == "deny":
            return decision
        if decision is not None and decision.disposition == "ask":
            return decision
        return PolicyDecision.ask(
            "Managed process execution requires explicit approval",
            code="managed_process_requires_approval",
        )


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
