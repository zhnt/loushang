"""Coding permission-expansion confirmation through the native Approval owner.

This is one prerequisite of current Resume admission. It does not compute the
actor's current policy or settle activation effects, and grants no Tool scope.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loushang.foundation.json import dump_json_value
from loushang.harness.approval import (
    ApprovalConfirmation,
    ApprovalGrantProposal,
    ApprovalRequest,
    InteractiveApprovalResolver,
    ensure_approval_action_id,
)
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    execution_profile_expansion_codes,
)
from loushang.harness.permissions import PermissionProfilePolicyEvaluator
from loushang.harness.policy.engine import PolicyEngine

from .resume_activation_attempt import CodingActivationAttemptV1

if TYPE_CHECKING:
    from .hosted_execution import HostedResumeSubjectControl, HostedResumeSubjectScope
    from .runtime.agent_session_runtime import AgentSessionRuntime

_EXPANSION = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")
NativeResumePolicy = PolicyEngine | PermissionProfilePolicyEvaluator


def _policy_fingerprint(policy: NativeResumePolicy) -> str:
    if type(policy) not in {PolicyEngine, PermissionProfilePolicyEvaluator}:
        raise TypeError("Coding Resume requires the original native Policy observation entry")
    return policy.configuration_fingerprint()


def _execution_scope(profile: EffectiveExecutionProfile) -> tuple[dict[str, object], str]:
    execution_profile_expansion_codes(profile, None)  # Native type/root budget.
    document: dict[str, object] = {
        "readableRoots": sorted(str(root) for root in profile.readable_roots),
        "writableRoots": sorted(str(root) for root in profile.writable_roots),
        "deniedRoots": sorted(str(root) for root in profile.denied_roots),
        "network": profile.network,
        "policyCode": profile.policy_code,
        "approvalActionId": profile.approval_action_id,
    }
    encoded = dump_json_value(
        document, name="Coding Resume execution scope", ensure_ascii=True, sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 16 * 1024:
        raise ValueError("Coding Resume execution scope exceeds its byte budget")
    return document, hashlib.sha256(b"loushang.coding.resume-execution-scope/v1\0" + encoded).hexdigest()


def coding_resume_permission_request(
    attempt: CodingActivationAttemptV1, *, actor_id: str,
    expansion_codes: tuple[str, ...], action_id: str | None = None,
    execution_profile: EffectiveExecutionProfile | None = None,
    baseline_execution_profile: EffectiveExecutionProfile | None = None,
    policy_evaluator: NativeResumePolicy | None = None,
    hosted_subject_scope: HostedResumeSubjectScope | None = None,
    hosted_subject_control: HostedResumeSubjectControl | None = None,
    embedded_subject_root: AgentSessionRuntime | None = None,
) -> ApprovalRequest:
    """Bind owner-observed expansion to this exact subject, target and candidate.

    Expansion classification and current subject/policy verification belong to
    their original owners. Unknown authority must be represented explicitly,
    rather than treating configuration or historical receipts as confirmation.
    """

    if not isinstance(attempt, CodingActivationAttemptV1):
        raise TypeError("Coding Resume confirmation requires an activation attempt")
    if embedded_subject_root is not None:
        from .runtime.agent_session_runtime import AgentSessionRuntime

        if type(embedded_subject_root) is not AgentSessionRuntime:
            raise TypeError("Coding Embedded Resume requires its original native Root")
        if hosted_subject_scope is not None or hosted_subject_control is not None:
            raise ValueError("Coding Resume subject must have one original ingress")
        if actor_id != "root":
            raise PermissionError("Coding Embedded Resume requires its original Root actor")
        embedded_subject_root.require_current_embedded_resume_subject(attempt)
    if hosted_subject_scope is not None or hosted_subject_control is not None:
        from .hosted_execution import _require_current_coding_hosted_resume_subject

        _require_current_coding_hosted_resume_subject(attempt, hosted_subject_scope, hosted_subject_control)
    if (
        type(expansion_codes) is not tuple or not 1 <= len(expansion_codes) <= 16
        or any(type(code) is not str or _EXPANSION.fullmatch(code) is None for code in expansion_codes)
        or expansion_codes != tuple(sorted(set(expansion_codes)))
    ):
        raise ValueError("Coding Resume permission expansion codes are invalid")
    if execution_profile is None and baseline_execution_profile is not None:
        raise ValueError("Coding Resume baseline requires a current execution scope")
    if execution_profile is not None:
        expansion_codes = tuple(sorted(set(expansion_codes) | set(
            execution_profile_expansion_codes(execution_profile, baseline_execution_profile),
        )))
        if len(expansion_codes) > 16:
            raise ValueError("Coding Resume permission expansion codes exceed their budget")
    arguments: dict[str, object] = {**attempt.to_data(), "permissionExpansion": list(expansion_codes)}
    if hosted_subject_scope is not None:
        arguments["subjectOwner"] = "appservice.controller/v1"
    if embedded_subject_root is not None:
        arguments["subjectOwner"] = "coding.embedded-root/v1"
    if policy_evaluator is not None:
        arguments["policyConfigurationFingerprint"] = _policy_fingerprint(policy_evaluator)
    if execution_profile is not None:
        scope, fingerprint = _execution_scope(execution_profile)
        arguments["executionScope"] = scope  # Reviewable in the native Approval surface.
        arguments["executionProfileFingerprint"] = fingerprint
        arguments["baselineExecutionProfileFingerprint"] = (
            _execution_scope(baseline_execution_profile)[1]
            if baseline_execution_profile is not None else None
        )
    encoded = dump_json_value(
        arguments, name="Coding Resume permission confirmation",
        ensure_ascii=True, sort_keys=True,
    ).encode("utf-8")
    fingerprint = hashlib.sha256(
        b"loushang.coding.resume-permission-confirmation/v1\0" + encoded,
    ).hexdigest()
    return ensure_approval_action_id(ApprovalRequest(
        tool_name="resume", actor_id=actor_id, action_id=action_id,
        action_fingerprint=fingerprint, arguments=arguments,
        policy_code="resume_permission_expansion",
        reason="Confirm the current permissions for this resumed session: " + ", ".join(expansion_codes),
        session_grant=ApprovalGrantProposal(
            capability="coding.resume.permission-expansion",
            constraints=(("confirmationFingerprint", fingerprint),),
            summary="Use these permissions for this exact Resume candidate",
        ),
    ))


@dataclass(frozen=True, slots=True)
class CodingResumePermissionConfirmation:
    """Borrow an exact native confirmation; never persist it as authority."""

    attempt: CodingActivationAttemptV1
    actor_id: str
    expansion_codes: tuple[str, ...]
    owner: InteractiveApprovalResolver
    confirmation: ApprovalConfirmation
    execution_profile: EffectiveExecutionProfile | None = None
    baseline_execution_profile: EffectiveExecutionProfile | None = None
    policy_evaluator: NativeResumePolicy | None = None
    hosted_subject_scope: HostedResumeSubjectScope | None = None
    hosted_subject_control: HostedResumeSubjectControl | None = None
    embedded_subject_root: AgentSessionRuntime | None = None

    def require_current(
        self, attempt: CodingActivationAttemptV1,
        *, current_execution_profile: EffectiveExecutionProfile | None = None,
        current_policy_evaluator: NativeResumePolicy | None = None,
    ) -> None:
        if attempt != self.attempt:
            raise PermissionError("Coding Resume permission confirmation target changed")
        if self.embedded_subject_root is not None:
            self.embedded_subject_root.require_current_embedded_resume_subject(attempt, approval_owner=self.owner)
        if self.hosted_subject_scope is not None or self.hosted_subject_control is not None:
            from .hosted_execution import _require_current_coding_hosted_resume_subject

            _require_current_coding_hosted_resume_subject(
                attempt, self.hosted_subject_scope, self.hosted_subject_control,
            )
        if (
            current_execution_profile is not None
            and type(current_execution_profile) is not EffectiveExecutionProfile
        ) or (
            self.execution_profile is not None
            and type(self.execution_profile) is not EffectiveExecutionProfile
        ):
            raise PermissionError("Coding Resume execution scope is not a native profile")
        if current_execution_profile != self.execution_profile:
            raise PermissionError("Coding Resume current execution scope is missing or changed")
        if (current_policy_evaluator is None) != (self.policy_evaluator is None):
            raise PermissionError("Coding Resume current Policy is missing or unbound")
        if (
            current_policy_evaluator is not None and self.policy_evaluator is not None
            and _policy_fingerprint(current_policy_evaluator) != _policy_fingerprint(self.policy_evaluator)
        ):
            raise PermissionError("Coding Resume current Policy configuration changed")
        expected = coding_resume_permission_request(
            attempt, actor_id=self.actor_id, expansion_codes=self.expansion_codes,
            action_id=self.confirmation.request.action_id,
            execution_profile=self.execution_profile,
            baseline_execution_profile=self.baseline_execution_profile,
            policy_evaluator=self.policy_evaluator,
            hosted_subject_scope=self.hosted_subject_scope,
            hosted_subject_control=self.hosted_subject_control,
            embedded_subject_root=self.embedded_subject_root,
        )
        self.owner.require_current_confirmation(self.confirmation, request=expected)
