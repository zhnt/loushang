"""Coding permission-expansion confirmation through the native Approval owner.

This is one prerequisite of current Resume admission. It does not compute the
actor's current policy or settle activation effects, and grants no Tool scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from loushang.coding.resume.activation_attempt import CodingActivationAttemptV1
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
from loushang.harness.session._resume_continuation import resume_execution_scope
from loushang.harness.transcript._resume_records import canonical_binding_bytes

if TYPE_CHECKING:
    from loushang.coding.resume.subject import (
        HostedResumeSubjectControl,
        HostedResumeSubjectScope,
    )
    from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime

_RESUME_APPROVAL_LABEL = "Coding Resume"
_EMBEDDED_APPROVAL_LABEL = "Coding Embedded Resume"
_EMBEDDED_ACTOR = "root"
_EMBEDDED_SUBJECT_OWNER = "coding.embedded-root/v1"
_HOSTED_SUBJECT_OWNER = "appservice.controller/v1"
_EXPANSION = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z")
_MAX_EXPANSION_CODES = 16
_SCOPE_LIMIT_BYTES = 16 * 1024
_SCOPE_DOMAIN = b"loushang.coding.resume-execution-scope/v1\0"
_REQUEST_DOMAIN = b"loushang.coding.resume-permission-confirmation/v1\0"
_APPROVAL_TOOL = "resume"
_APPROVAL_POLICY = "resume_permission_expansion"
_APPROVAL_CAPABILITY = "coding.resume.permission-expansion"
_APPROVAL_PROMPT = "Confirm the current permissions for this resumed session: "
_APPROVAL_SUMMARY = "Use these permissions for this exact Resume candidate"
NativeResumePolicy = PolicyEngine | PermissionProfilePolicyEvaluator


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

    label = _RESUME_APPROVAL_LABEL
    if not isinstance(attempt, CodingActivationAttemptV1):
        raise TypeError(f"{label} confirmation requires an activation attempt")
    if embedded_subject_root is not None:
        from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime

        if type(embedded_subject_root) is not AgentSessionRuntime:
            raise TypeError(
                f"{_EMBEDDED_APPROVAL_LABEL} requires its original native Root"
            )
        if hosted_subject_scope is not None or hosted_subject_control is not None:
            raise ValueError(f"{label} subject must have one original ingress")
        if actor_id != _EMBEDDED_ACTOR:
            raise PermissionError(
                f"{_EMBEDDED_APPROVAL_LABEL} requires its original Root actor"
            )
        embedded_subject_root.require_current_embedded_resume_subject(attempt)
    _require_hosted_subject(
        attempt, hosted_subject_scope, hosted_subject_control
    )
    if (
        type(expansion_codes) is not tuple
        or not 1 <= len(expansion_codes) <= _MAX_EXPANSION_CODES
        or any(
            type(code) is not str or _EXPANSION.fullmatch(code) is None
            for code in expansion_codes
        )
        or expansion_codes != tuple(sorted(set(expansion_codes)))
    ):
        raise ValueError(f"{label} permission expansion codes are invalid")
    if execution_profile is None and baseline_execution_profile is not None:
        raise ValueError(f"{label} baseline requires a current execution scope")
    if execution_profile is not None:
        observed = execution_profile_expansion_codes(
            execution_profile, baseline_execution_profile
        )
        expansion_codes = tuple(sorted({*expansion_codes, *observed}))
        if len(expansion_codes) > _MAX_EXPANSION_CODES:
            raise ValueError(f"{label} permission expansion codes exceed their budget")
    arguments: dict[str, object] = {
        **attempt.to_data(),
        "permissionExpansion": list(expansion_codes),
    }
    if hosted_subject_scope is not None:
        arguments["subjectOwner"] = _HOSTED_SUBJECT_OWNER
    if embedded_subject_root is not None:
        arguments["subjectOwner"] = _EMBEDDED_SUBJECT_OWNER
    if policy_evaluator is not None:
        arguments["policyConfigurationFingerprint"] = _policy_fingerprint(
            policy_evaluator
        )
    if execution_profile is not None:
        scope, fingerprint = _execution_scope(execution_profile)
        # Keep the actual scope reviewable by the native Approval surface.
        arguments["executionScope"] = scope
        arguments["executionProfileFingerprint"] = fingerprint
        arguments["baselineExecutionProfileFingerprint"] = (
            _execution_scope(baseline_execution_profile)[1]
            if baseline_execution_profile is not None
            else None
        )
    encoded = canonical_binding_bytes(
        arguments, name=f"{label} permission confirmation"
    )
    fingerprint = sha256(_REQUEST_DOMAIN + encoded).hexdigest()
    return ensure_approval_action_id(
        ApprovalRequest(
            tool_name=_APPROVAL_TOOL,
            actor_id=actor_id,
            action_id=action_id,
            action_fingerprint=fingerprint,
            arguments=arguments,
            policy_code=_APPROVAL_POLICY,
            reason=_APPROVAL_PROMPT + ", ".join(expansion_codes),
            session_grant=ApprovalGrantProposal(
                capability=_APPROVAL_CAPABILITY,
                constraints=(("confirmationFingerprint", fingerprint),),
                summary=_APPROVAL_SUMMARY,
            ),
        )
    )


def _policy_fingerprint(policy: NativeResumePolicy) -> str:
    if type(policy) not in {PolicyEngine, PermissionProfilePolicyEvaluator}:
        raise TypeError(
            f"{_RESUME_APPROVAL_LABEL} requires the original native Policy observation entry"
        )
    return policy.configuration_fingerprint()


def _execution_scope(profile: EffectiveExecutionProfile) -> tuple[dict[str, object], str]:
    return resume_execution_scope(
        profile,
        name=f"{_RESUME_APPROVAL_LABEL} execution scope",
        max_bytes=_SCOPE_LIMIT_BYTES,
        digest_domain=_SCOPE_DOMAIN,
    )


def _require_hosted_subject(
    attempt: CodingActivationAttemptV1,
    hosted_subject_scope: HostedResumeSubjectScope | None,
    hosted_subject_control: HostedResumeSubjectControl | None,
) -> None:
    if hosted_subject_scope is not None or hosted_subject_control is not None:
        from loushang.coding.resume.subject import (
            require_current_coding_hosted_resume_subject as _require_current_coding_hosted_resume_subject,
        )

        _require_current_coding_hosted_resume_subject(attempt, hosted_subject_scope, hosted_subject_control)


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
        label = _RESUME_APPROVAL_LABEL
        if attempt != self.attempt:
            raise PermissionError(f"{label} permission confirmation target changed")
        if self.embedded_subject_root is not None:
            self.embedded_subject_root.require_current_embedded_resume_subject(
                attempt, approval_owner=self.owner
            )
        _require_hosted_subject(
            attempt, self.hosted_subject_scope, self.hosted_subject_control
        )
        if (
            current_execution_profile is not None
            and type(current_execution_profile) is not EffectiveExecutionProfile
        ) or (
            self.execution_profile is not None
            and type(self.execution_profile) is not EffectiveExecutionProfile
        ):
            raise PermissionError(f"{label} execution scope is not a native profile")
        if current_execution_profile != self.execution_profile:
            raise PermissionError(f"{label} current execution scope is missing or changed")
        if (current_policy_evaluator is None) != (self.policy_evaluator is None):
            raise PermissionError(f"{label} current Policy is missing or unbound")
        if (
            current_policy_evaluator is not None
            and self.policy_evaluator is not None
            and _policy_fingerprint(current_policy_evaluator)
            != _policy_fingerprint(self.policy_evaluator)
        ):
            raise PermissionError(f"{label} current Policy configuration changed")
        expected = coding_resume_permission_request(
            attempt,
            actor_id=self.actor_id,
            expansion_codes=self.expansion_codes,
            action_id=self.confirmation.request.action_id,
            execution_profile=self.execution_profile,
            baseline_execution_profile=self.baseline_execution_profile,
            policy_evaluator=self.policy_evaluator,
            hosted_subject_scope=self.hosted_subject_scope,
            hosted_subject_control=self.hosted_subject_control,
            embedded_subject_root=self.embedded_subject_root,
        )
        self.owner.require_current_confirmation(self.confirmation, request=expected)
