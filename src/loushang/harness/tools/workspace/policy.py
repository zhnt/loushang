from __future__ import annotations

import inspect
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from loushang.harness.approval import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResolver,
    approval_actor_id,
    ensure_approval_action_id,
    find_approval_grant,
    resolve_approval,
)
from loushang.harness.effects import ToolEffect
from loushang.harness.policy import (
    PolicyDecision,
    PolicyEvaluationError,
    PolicyEvaluator,
    ToolPolicySubject,
    build_tool_policy_subject,
    evaluate_policy,
    executable_search_path_from_env,
    normalize_command_subject,
)
from loushang.harness.policy_grants import (
    propose_policy_amendments,
    propose_session_approval_grant,
)

from .audit import snapshot_audit_event

ToolPolicyEvaluator = PolicyEvaluator


class PolicyEnforcementError(PermissionError):
    def __init__(self, message: str, *, tool_result_details: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.tool_result_details = dict(tool_result_details)


@dataclass(frozen=True, slots=True)
class ToolPolicyAuthorization:
    decision: PolicyDecision
    approval: ApprovalDecision | None = None
    approval_action_id: str | None = None


async def enforce_tool_policy(
    policy_engine: ToolPolicyEvaluator | None,
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    cwd: str | None = None,
    policy_subject: ToolPolicySubject | None = None,
    effects: tuple[ToolEffect, ...] = (),
    approval_resolver: ApprovalResolver | None = None,
    tool_call_id: str | None = None,
    audit_sink: Any = None,
    audit_context: Mapping[str, object] | None = None,
    execution_environment: object | None = None,
) -> ToolPolicyAuthorization:
    if policy_engine is None:
        decision = PolicyDecision.allow()
        if audit_context is not None:
            await _emit_policy_audit_event(
                audit_sink,
                {
                    "type": "tool_policy_evaluated",
                    **_policy_audit_details(
                        tool_name=tool_name,
                        decision=decision,
                        approval_required=False,
                        tool_call_id=tool_call_id,
                        audit_context=audit_context,
                    ),
                },
            )
        return ToolPolicyAuthorization(decision)
    execution_subject = build_tool_policy_subject(
        tool_name=tool_name,
        arguments=arguments,
        cwd=cwd,
        effects=effects,
    )
    environment_snapshot = _snapshot_execution_environment(execution_environment)
    _validate_execution_arguments(execution_subject)
    if policy_subject is not None:
        _validate_policy_subject_matches_execution(
            policy_subject,
            execution_subject,
            execution_environment=environment_snapshot,
        )
    subject = policy_subject or execution_subject
    tool_name = subject.tool_name
    arguments = subject.arguments
    cwd = subject.cwd
    decision = await _evaluate_tool_policy(
        policy_engine,
        tool_name=tool_name,
        arguments=arguments,
        cwd=cwd,
        subject=subject,
    )
    await _emit_policy_audit_event(
        audit_sink,
        {
            "type": "tool_policy_evaluated",
            **_policy_audit_details(
                tool_name=tool_name,
                decision=decision,
                approval_required=decision.disposition == "ask",
                tool_call_id=tool_call_id,
                audit_context=audit_context,
            ),
        },
    )
    if decision.disposition == "allow":
        return ToolPolicyAuthorization(decision)
    if decision.disposition == "deny":
        message = decision.reason or f"Tool {tool_name} denied by policy"
        raise PolicyEnforcementError(
            message,
            tool_result_details=_policy_error_details(
                tool_name=tool_name,
                arguments=arguments,
                cwd=cwd,
                decision=decision,
                approval_required=False,
            ),
        )
    if decision.disposition == "ask":
        fingerprint = (
            audit_context.get("action_fingerprint")
            if audit_context is not None
            else None
        )
        request = ensure_approval_action_id(
            ApprovalRequest(
                tool_name=tool_name,
                arguments=arguments,
                cwd=cwd,
                reason=decision.reason,
                policy_code=decision.code,
                policy_decision=decision,
                actor_id=approval_actor_id(approval_resolver),
                action_fingerprint=(
                    fingerprint if isinstance(fingerprint, str) else None
                ),
                session_grant=propose_session_approval_grant(
                    subject,
                    policy_code=decision.code,
                ),
                policy_amendments=propose_policy_amendments(
                    subject,
                    policy_code=decision.code,
                ),
            )
        )
        action_id = request.action_id
        assert action_id is not None
        granted = await find_approval_grant(approval_resolver, request)
        if granted is not None:
            await _emit_policy_audit_event(
                audit_sink,
                {
                    "type": "tool_approval_resolved",
                    **_approval_audit_details(
                        tool_name=tool_name,
                        decision=decision,
                        action_id=action_id,
                        tool_call_id=tool_call_id,
                        approval=granted,
                        approval_source=(
                            "policy_rule"
                            if granted.policy_rule_id is not None
                            else "session_grant"
                        ),
                        audit_context=audit_context,
                    ),
                },
            )
            return ToolPolicyAuthorization(
                decision,
                approval=granted,
                approval_action_id=action_id,
            )
        await _emit_policy_audit_event(
            audit_sink,
            {
                "type": "tool_approval_requested",
                **_approval_audit_details(
                    tool_name=tool_name,
                    decision=decision,
                    action_id=action_id,
                    tool_call_id=tool_call_id,
                    audit_context=audit_context,
                ),
            },
        )
        approval = await resolve_approval(
            approval_resolver,
            request,
        )
        await _emit_policy_audit_event(
            audit_sink,
            {
                "type": "tool_approval_resolved",
                **_approval_audit_details(
                    tool_name=tool_name,
                    decision=decision,
                    action_id=action_id,
                    tool_call_id=tool_call_id,
                    approval=approval,
                    approval_source="reviewer",
                    audit_context=audit_context,
                ),
            },
        )
        if approval.disposition == "allow":
            return ToolPolicyAuthorization(
                decision,
                approval=approval,
                approval_action_id=action_id,
            )
        message = (
            approval.reason or decision.reason or f"Tool {tool_name} requires approval"
        )
        raise PolicyEnforcementError(
            message,
            tool_result_details=_policy_error_details(
                tool_name=tool_name,
                arguments=arguments,
                cwd=cwd,
                decision=decision,
                approval_required=True,
                approval=approval,
                approval_reason=message,
                approval_action_id=request.action_id,
            ),
        )


async def _evaluate_tool_policy(
    policy_engine: ToolPolicyEvaluator,
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    cwd: str | None,
    subject: ToolPolicySubject,
) -> PolicyDecision:
    del tool_name, arguments, cwd
    decision = await evaluate_policy(
        cast(PolicyEvaluator, policy_engine),
        subject,
    )
    return decision if decision is not None else PolicyDecision.allow()


def _validate_execution_arguments(execution: ToolPolicySubject) -> None:
    if execution.tool_name != "bash" or "cwd" not in execution.arguments:
        return
    argument_cwd = execution.arguments["cwd"]
    if argument_cwd is not None and not isinstance(argument_cwd, str):
        raise PolicyEvaluationError(
            "Bash execution argument cwd must be a string or None"
        )
    if argument_cwd != execution.cwd:
        raise PolicyEvaluationError(
            "Bash execution argument cwd does not match the execution cwd"
        )


def _validate_policy_subject_matches_execution(
    subject: ToolPolicySubject,
    execution: ToolPolicySubject,
    *,
    execution_environment: tuple[tuple[str, str], ...] | None,
) -> None:
    mismatches = []
    if subject.tool_name != execution.tool_name:
        mismatches.append("tool_name")
    if subject.arguments != execution.arguments:
        mismatches.append("arguments")
    if subject.cwd != execution.cwd:
        mismatches.append("cwd")
    if subject.paths != execution.paths:
        mismatches.append("paths")
    if subject.effects != execution.effects:
        mismatches.append("effects")
    argument_command = execution.arguments.get("command")
    if argument_command is None:
        if subject.command is not None:
            mismatches.append("command")
    elif subject.command is None:
        mismatches.append("command")
    else:
        stdin = execution.arguments.get("stdin")
        normalized_stdin = stdin if isinstance(stdin, str) else None
        normalization_environment = (
            execution_environment
            if execution_environment is not None
            else execution.arguments.get("env", ())
        )
        executable_search_path = executable_search_path_from_env(
            normalization_environment,
            default=os.defpath if execution_environment is not None else None,
        )
        expected_command = None
        command_matches_argument = True
        if isinstance(argument_command, str):
            expected_command = normalize_command_subject(
                subject.command.command,
                cwd=execution.cwd,
                assume_shell=True,
                stdin=normalized_stdin,
                executable_search_path=executable_search_path,
                environment_overrides=normalization_environment,
                environment_is_complete=execution_environment is not None,
            )
            command_matches_argument = (
                expected_command.shell_payload == argument_command
            )
        elif isinstance(argument_command, (list, tuple)) and all(
            isinstance(part, str) for part in argument_command
        ):
            expected_command = normalize_command_subject(
                tuple(argument_command),
                cwd=execution.cwd,
                stdin=normalized_stdin,
                executable_search_path=executable_search_path,
                environment_overrides=normalization_environment,
                environment_is_complete=execution_environment is not None,
            )
        if subject.command != expected_command or not command_matches_argument:
            mismatches.append("command")
    if mismatches:
        raise PolicyEvaluationError(
            "Policy subject does not match execution fields: " + ", ".join(mismatches)
        )


def _snapshot_execution_environment(
    environment: object | None,
) -> tuple[tuple[str, str], ...] | None:
    if environment is None:
        return None
    values = environment.items() if isinstance(environment, Mapping) else environment
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise TypeError("execution_environment must contain 2-item string pairs")
    snapshot: list[tuple[str, str]] = []
    for item in values:
        if isinstance(item, str) or not isinstance(item, (list, tuple)):
            raise TypeError("execution_environment must contain 2-item string pairs")
        pair = tuple(item)
        if len(pair) != 2 or not all(isinstance(part, str) for part in pair):
            raise TypeError("execution_environment must contain 2-item string pairs")
        snapshot.append((pair[0], pair[1]))
    return tuple(snapshot)


def _policy_error_details(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    cwd: str | None,
    decision: PolicyDecision,
    approval_required: bool,
    approval: ApprovalDecision | None = None,
    approval_reason: str | None = None,
    approval_action_id: str | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "tool_name": tool_name,
        "policy_disposition": decision.disposition,
        "approval_required": approval_required,
        "argument_keys": sorted(str(key) for key in arguments.keys()),
    }
    if cwd is not None:
        details["cwd"] = cwd
    if decision.code is not None:
        details["policy_code"] = decision.code
    if decision.reason is not None:
        details["policy_reason"] = decision.reason
    if approval is not None:
        details["approval_decision"] = approval.disposition
    if approval_reason is not None:
        details["approval_reason"] = approval_reason
    if approval_action_id is not None:
        details["approval_action_id"] = approval_action_id
    for key in ("path", "file_path", "command"):
        value = arguments.get(key)
        if isinstance(value, str):
            details[key] = value
        elif (
            key == "command"
            and isinstance(value, (list, tuple))
            and all(isinstance(part, str) for part in value)
        ):
            details[key] = tuple(value)
    return details


def _policy_audit_details(
    *,
    tool_name: str,
    decision: PolicyDecision,
    approval_required: bool,
    tool_call_id: str | None,
    audit_context: Mapping[str, object] | None,
) -> dict[str, Any]:
    details: dict[str, Any] = dict(audit_context or ())
    details.update(
        {
            "tool_name": tool_name,
            "policy_disposition": decision.disposition,
            "approval_required": approval_required,
        }
    )
    if decision.code is not None:
        details["policy_code"] = decision.code
    if tool_call_id is not None:
        details["tool_call_id"] = tool_call_id
    return details


def _approval_audit_details(
    *,
    tool_name: str,
    decision: PolicyDecision,
    action_id: str,
    tool_call_id: str | None,
    approval: ApprovalDecision | None = None,
    approval_source: str | None = None,
    audit_context: Mapping[str, object] | None,
) -> dict[str, Any]:
    details: dict[str, Any] = dict(audit_context or ())
    details.update({"tool_name": tool_name, "action_id": action_id})
    if tool_call_id is not None:
        details["tool_call_id"] = tool_call_id
    if decision.code is not None:
        details["policy_code"] = decision.code
    if approval is not None:
        details["approval_decision"] = approval.disposition
        details["approval_scope"] = approval.scope
        if approval.grant_id is not None:
            details["approval_grant_id"] = approval.grant_id
        if approval.policy_rule_id is not None:
            details["approval_policy_rule_id"] = approval.policy_rule_id
            details["approval_policy_scope"] = approval.policy_scope
    if approval_source is not None:
        details["approval_source"] = approval_source
    return details


async def _emit_policy_audit_event(audit_sink: Any, event: Mapping[str, Any]) -> None:
    if audit_sink is None:
        return
    result = audit_sink(snapshot_audit_event(event))
    if inspect.isawaitable(result):
        await result
