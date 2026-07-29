from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeVar, cast

from loushang.harness.approval import ApprovalResolver, approval_actor_id
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
    resolve_effective_execution_profile,
)
from loushang.harness.effects import (
    FilesystemEffect,
    ToolEffect,
    effect_snapshot,
)
from loushang.harness.policy import ToolPolicySubject
from loushang.harness.tools.execution import (
    AuthorizedToolAction,
    AuthorizedToolContext,
    AuthorizedToolHandler,
    PreparedToolAction,
    ToolExecutionHost,
)

from .audit import (
    build_action_audit_details,
    execution_failure_outcome,
    execution_profile_audit_summary,
    snapshot_audit_event,
)
from .policy import ToolPolicyEvaluator, enforce_tool_policy

T = TypeVar("T")
WorkspaceActionExecutor = Callable[
    [AuthorizedToolAction],
    T | Awaitable[T],
]
WorkspaceActionObservation = Callable[
    [AuthorizedToolAction],
    object | Awaitable[object],
]

@dataclass(frozen=True, slots=True)
class WorkspaceToolAuthorizationGateway:
    """Session-owned Policy/Approval gateway for protected tool actions."""

    policy_evaluator: ToolPolicyEvaluator
    approval_resolver: ApprovalResolver | None = None
    execution_environment: object | None = None

    async def execute(
        self,
        prepared: PreparedToolAction,
        handler: AuthorizedToolHandler,
        context: AuthorizedToolContext,
    ) -> Any:
        return await _execute_authorized_tool_action(
            self.policy_evaluator,
            tool_name=prepared.tool_name,
            arguments=prepared.authorization_arguments,
            execution_arguments=prepared.execution_arguments,
            effects=prepared.effects,
            executor=lambda action: handler(action, context),
            cwd=prepared.cwd,
            policy_subject=prepared.policy_subject,
            approval_resolver=self.approval_resolver,
            tool_call_id=context.tool_call_id,
            audit_sink=context.event_sink,
            execution_environment=(
                prepared.execution_environment
                if prepared.execution_environment is not None
                else self.execution_environment
            ),
            execution_profile_ceiling=getattr(
                context.exec_service,
                "execution_profile",
                None,
            ),
        )


def create_workspace_tool_execution_host(
    *,
    policy_evaluator: ToolPolicyEvaluator,
    approval_resolver: ApprovalResolver | None = None,
    execution_environment: object | None = None,
) -> ToolExecutionHost:
    """Compose the one live Workspace Gateway owned by an execution scope."""

    return ToolExecutionHost(
        WorkspaceToolAuthorizationGateway(
            policy_evaluator=policy_evaluator,
            approval_resolver=approval_resolver,
            execution_environment=execution_environment,
        )
    )


async def _authorize_workspace_tool_action(
    policy_engine: ToolPolicyEvaluator | None,
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    execution_arguments: Mapping[str, Any] | None = None,
    effects: tuple[ToolEffect, ...] = (),
    cwd: str | None = None,
    policy_subject: ToolPolicySubject | None = None,
    approval_resolver: ApprovalResolver | None = None,
    tool_call_id: str | None = None,
    audit_sink: Any = None,
    execution_environment: object | None = None,
    execution_profile_ceiling: EffectiveExecutionProfile | None = None,
) -> AuthorizedToolAction:
    """Freeze one action before routing it through Policy and Approval."""

    frozen_arguments = _freeze_mapping(arguments)
    frozen_execution_arguments = _freeze_mapping(
        execution_arguments if execution_arguments is not None else arguments
    )
    audit_details = _freeze_mapping(
        build_action_audit_details(
            tool_name=tool_name,
            arguments=frozen_arguments,
            cwd=cwd,
            policy_subject=policy_subject,
        )
    )
    action = AuthorizedToolAction(
        tool_name=tool_name,
        authorization_arguments=frozen_arguments,
        execution_arguments=frozen_execution_arguments,
        cwd=cwd,
        fingerprint=_fingerprint(
            tool_name,
            frozen_arguments,
            cwd,
            effects=effects,
        ),
        effects=effects,
        actor_id=approval_actor_id(approval_resolver),
        audit_details=audit_details,
    )
    audit_context = _action_audit_context(
        action,
        tool_call_id=tool_call_id,
    )
    await _emit_audit_event(
        audit_sink,
        {"type": "tool_action_frozen", **audit_context},
    )
    authorization = await enforce_tool_policy(
        policy_engine,
        tool_name=action.tool_name,
        arguments=action.authorization_arguments,
        cwd=action.cwd,
        policy_subject=policy_subject,
        effects=effects,
        approval_resolver=approval_resolver,
        tool_call_id=tool_call_id,
        audit_sink=audit_sink,
        audit_context=audit_context,
        execution_environment=execution_environment,
    )
    effective = (
        resolve_effective_execution_profile(
            ceiling=execution_profile_ceiling,
            decision=authorization.decision,
            approval=authorization.approval,
            approval_action_id=authorization.approval_action_id,
        )
        if execution_profile_ceiling is not None
        else None
    )
    return AuthorizedToolAction(
        tool_name=action.tool_name,
        authorization_arguments=action.authorization_arguments,
        execution_arguments=action.execution_arguments,
        cwd=action.cwd,
        fingerprint=action.fingerprint,
        effects=action.effects,
        actor_id=action.actor_id,
        execution_profile=effective,
        policy_code=authorization.decision.code,
        approval_action_id=authorization.approval_action_id,
        audit_details=action.audit_details,
    )


async def _execute_authorized_tool_action(
    policy_engine: ToolPolicyEvaluator | None,
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    execution_arguments: Mapping[str, Any] | None = None,
    effects: tuple[ToolEffect, ...] = (),
    executor: WorkspaceActionExecutor[T],
    on_authorized: WorkspaceActionObservation | None = None,
    cwd: str | None = None,
    policy_subject: ToolPolicySubject | None = None,
    approval_resolver: ApprovalResolver | None = None,
    tool_call_id: str | None = None,
    audit_sink: Any = None,
    execution_environment: object | None = None,
    execution_profile_ceiling: EffectiveExecutionProfile | None = None,
) -> T:
    """Authorize and execute one frozen action through the same gateway.

    ``on_authorized`` is an observation-only presentation hook. Tool effects
    belong exclusively in ``executor``.
    """

    action = await _authorize_workspace_tool_action(
        policy_engine,
        tool_name=tool_name,
        arguments=arguments,
        execution_arguments=execution_arguments,
        effects=effects,
        cwd=cwd,
        policy_subject=policy_subject,
        approval_resolver=approval_resolver,
        tool_call_id=tool_call_id,
        audit_sink=audit_sink,
        execution_environment=execution_environment,
        execution_profile_ceiling=execution_profile_ceiling,
    )
    try:
        _revalidate_authorized_action(action)
        if on_authorized is not None:
            hook_result = on_authorized(action)
            if inspect.isawaitable(hook_result):
                await hook_result
        _revalidate_authorized_action(action)
    except BaseException as error:
        await _emit_audit_event(
            audit_sink,
            {
                "type": "tool_execution_failed",
                **_execution_audit_details(
                    action,
                    tool_call_id=tool_call_id,
                    outcome=execution_failure_outcome(error),
                    phase="pre_execution",
                ),
            },
        )
        raise
    await _emit_audit_event(
        audit_sink,
        {
            "type": "tool_execution_started",
            **_execution_audit_details(
                action,
                tool_call_id=tool_call_id,
                outcome="running",
                phase="execution",
            ),
        },
    )
    try:
        result = await _execute_authorized_workspace_tool_action(
            action,
            executor=executor,
        )
    except BaseException as error:
        try:
            await _emit_audit_event(
                audit_sink,
                {
                    "type": "tool_execution_failed",
                    **_execution_audit_details(
                        action,
                        tool_call_id=tool_call_id,
                        outcome=execution_failure_outcome(error),
                        phase="execution",
                    ),
                },
            )
        except BaseException as audit_error:
            error.add_note(f"terminal audit emission failed: {audit_error}")
        raise
    await _emit_audit_event(
        audit_sink,
        {
            "type": "tool_execution_completed",
            **_execution_audit_details(
                action,
                tool_call_id=tool_call_id,
                outcome="completed",
                phase="execution",
            ),
        },
    )
    return result


async def _execute_authorized_workspace_tool_action(
    action: AuthorizedToolAction,
    *,
    executor: WorkspaceActionExecutor[T],
) -> T:
    """Revalidate one immutable action immediately before invoking its executor."""

    _revalidate_authorized_action(action)
    result = executor(action)
    if inspect.isawaitable(result):
        return await cast(Awaitable[T], result)
    return result


def _revalidate_authorized_action(action: AuthorizedToolAction) -> None:
    if not isinstance(action, AuthorizedToolAction):
        raise TypeError("action must be an AuthorizedToolAction")
    fingerprint = _fingerprint(
        action.tool_name,
        action.authorization_arguments,
        action.cwd,
        effects=action.effects,
    )
    if fingerprint != action.fingerprint:
        raise ExecutionAuthorizationError(
            "authorized action changed before execution"
        )
    if action.execution_profile is not None:
        _validate_path_authority(
            action.tool_name,
            action.authorization_arguments,
            action.execution_profile,
            effects=action.effects,
        )


def _action_audit_context(
    action: AuthorizedToolAction,
    *,
    tool_call_id: str | None,
) -> dict[str, object]:
    details: dict[str, object] = {
        "tool_name": action.tool_name,
        "action_fingerprint": action.fingerprint,
        "actor_id": action.actor_id,
        **cast(dict[str, object], _json_value(action.audit_details)),
    }
    if tool_call_id is not None:
        details["tool_call_id"] = tool_call_id
    return details


def _execution_audit_details(
    action: AuthorizedToolAction,
    *,
    tool_call_id: str | None,
    outcome: str,
    phase: str,
) -> dict[str, object]:
    details = _action_audit_context(action, tool_call_id=tool_call_id)
    details.update({"outcome": outcome, "phase": phase})
    details["execution_profile"] = execution_profile_audit_summary(
        action.execution_profile
    )
    if action.policy_code is not None:
        details["policy_code"] = action.policy_code
    if action.approval_action_id is not None:
        details["approval_action_id"] = action.approval_action_id
    return details


async def _emit_audit_event(
    audit_sink: Any,
    event: Mapping[str, object],
) -> None:
    if audit_sink is None:
        return
    result = audit_sink(snapshot_audit_event(event))
    if inspect.isawaitable(result):
        await result


def _fingerprint(
    tool_name: str,
    arguments: Mapping[str, Any],
    cwd: str | None,
    *,
    effects: tuple[ToolEffect, ...] = (),
) -> str:
    payload_value: dict[str, object] = {
        "tool_name": tool_name,
        "arguments": _json_value(arguments),
        "cwd": cwd,
    }
    if effects:
        payload_value["effects"] = [
            effect_snapshot(effect) for effect in effects
        ]
    payload = json.dumps(
        payload_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            str(key): _freeze_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    )


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _validate_path_authority(
    tool_name: str,
    arguments: Mapping[str, Any],
    profile: EffectiveExecutionProfile,
    *,
    effects: tuple[ToolEffect, ...] = (),
) -> None:
    filesystem_effects = tuple(
        effect for effect in effects if isinstance(effect, FilesystemEffect)
    )
    if filesystem_effects:
        for effect in filesystem_effects:
            roots = (
                profile.readable_roots
                if effect.operation == "read"
                else profile.writable_roots
            )
            for path_value in effect.paths:
                _validate_one_path(path_value, roots=roots, profile=profile)
        return
    path_value = arguments.get("path")
    if not isinstance(path_value, str):
        return
    path = Path(path_value).resolve(strict=False)
    if any(path == root or path.is_relative_to(root) for root in profile.denied_roots):
        raise ExecutionAuthorizationError(f"path is denied by execution profile: {path}")
    roots = (
        profile.readable_roots
        if tool_name in {"read", "grep", "find", "ls"}
        else profile.writable_roots
        if tool_name in {"write", "edit"}
        else ()
    )
    if roots and any(path == root or path.is_relative_to(root) for root in roots):
        return
    if tool_name in {"read", "grep", "find", "ls", "write", "edit"}:
        raise ExecutionAuthorizationError(
            f"path is outside the authorized {tool_name} roots: {path}"
        )


def _validate_one_path(
    path_value: str,
    *,
    roots: tuple[Path, ...],
    profile: EffectiveExecutionProfile,
) -> None:
    path = Path(path_value).resolve(strict=False)
    if any(
        path == root or path.is_relative_to(root)
        for root in profile.denied_roots
    ):
        raise ExecutionAuthorizationError(
            f"path is denied by execution profile: {path}"
        )
    if roots and any(path == root or path.is_relative_to(root) for root in roots):
        return
    raise ExecutionAuthorizationError(
        f"path is outside the authorized roots: {path}"
    )


__all__ = [
    "WorkspaceToolAuthorizationGateway",
    "create_workspace_tool_execution_host",
]
