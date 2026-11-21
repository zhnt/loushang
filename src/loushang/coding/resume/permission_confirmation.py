"""Coding permission-expansion confirmation through the native Approval owner.

This is one prerequisite of current Resume admission. It does not compute the
actor's current policy or settle activation effects, and grants no Tool scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loushang.coding.harness.session import approval_confirmation
from loushang.coding.resume.activation_attempt import CodingActivationAttemptV1
from loushang.harness.approval import (
    ApprovalConfirmation,
    ApprovalRequest,
    InteractiveApprovalResolver,
)
from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.permissions import PermissionProfilePolicyEvaluator
from loushang.harness.policy.engine import PolicyEngine

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

    return approval_confirmation.build_request(
        attempt, actor_id=actor_id, expansion_codes=expansion_codes,
        action_id=action_id, execution_profile=execution_profile,
        baseline_execution_profile=baseline_execution_profile, policy_evaluator=policy_evaluator,
        hosted_subject_scope=hosted_subject_scope, hosted_subject_control=hosted_subject_control,
        embedded_subject_root=embedded_subject_root,
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
        approval_confirmation.require_current(
            self, attempt,
            current_execution_profile=current_execution_profile,
            current_policy_evaluator=current_policy_evaluator,
        )
