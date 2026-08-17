"""Approval request, decision, option, and proposal values with projections.

A grant proposal (`ApprovalGrantProposal`) is proposed, not yet issued
authority attached to a request; an issued grant lives in
`loushang.harness.approval.grants.ApprovalGrant`. See the terminology
conventions in policy-approval-redesign.md section 7.0.
"""


from __future__ import annotations

import shlex
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal, TypeAlias, TypeVar
from uuid import uuid4

from loushang.harness.approval._freeze import _freeze_mapping, _thaw_value
from loushang.harness.diagnostics.export import redact_text

T = TypeVar("T")

MaybeAwaitable: TypeAlias = T | Awaitable[T]

ApprovalScope = Literal["once", "session"]

PolicyAmendmentScope = Literal["project", "user"]

ApprovalOutcome = Literal[
    "allow_once",
    "allow_session",
    "allow_project",
    "allow_user",
    "deny",
    "abort",
]

@dataclass(frozen=True, slots=True)
class ApprovalGrantProposal:
    """A Policy-generated capability matcher safe to retain for one session."""

    capability: str
    constraints: tuple[tuple[str, str], ...]
    summary: str = field(compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.capability, str) or not self.capability:
            raise ValueError("grant capability must be a non-empty string")
        if not isinstance(self.summary, str) or not self.summary:
            raise ValueError("grant summary must be a non-empty string")
        constraints = tuple(self.constraints)
        if any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or not value
            for key, value in constraints
        ):
            raise ValueError("grant constraints must contain non-empty string pairs")
        if len({key for key, _value in constraints}) != len(constraints):
            raise ValueError("grant constraint keys must be unique")
        object.__setattr__(self, "constraints", tuple(sorted(constraints)))

@dataclass(frozen=True, slots=True)
class PolicyAmendmentProposal:
    """A Policy-authored persistent rule offered for one explicit scope."""

    scope: PolicyAmendmentScope
    grant: ApprovalGrantProposal

    def __post_init__(self) -> None:
        if self.scope not in {"project", "user"}:
            raise ValueError(f"Unsupported policy amendment scope: {self.scope}")
        if not isinstance(self.grant, ApprovalGrantProposal):
            raise TypeError("policy amendment grant must be an ApprovalGrantProposal")

@dataclass(frozen=True, slots=True)
class ApprovalOption:
    """One Policy-generated choice rendered by an approval client."""

    outcome: ApprovalOutcome
    label: str
    shortcut: str
    tone: Literal["allow", "session", "persistent", "deny"] = "allow"

@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    arguments: Mapping[str, Any]
    cwd: str | None = None
    reason: str | None = None
    policy_code: str | None = None
    policy_decision: object | None = None
    action_id: str | None = None
    action_fingerprint: str | None = None
    actor_id: str = "root"
    session_grant: ApprovalGrantProposal | None = None
    policy_amendments: tuple[PolicyAmendmentProposal, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.tool_name, str) or not self.tool_name:
            raise ValueError("ApprovalRequest tool_name must be a non-empty string")
        _validate_optional_string(self.cwd, "ApprovalRequest cwd")
        _validate_optional_string(self.reason, "ApprovalRequest reason")
        _validate_optional_string(self.policy_code, "ApprovalRequest policy_code")
        _validate_optional_string(self.action_id, "ApprovalRequest action_id")
        _validate_optional_string(
            self.action_fingerprint,
            "ApprovalRequest action_fingerprint",
        )
        if self.action_id == "":
            raise ValueError("ApprovalRequest action_id must not be empty")
        if self.action_fingerprint == "":
            raise ValueError("ApprovalRequest action_fingerprint must not be empty")
        if not isinstance(self.actor_id, str) or not self.actor_id:
            raise ValueError("ApprovalRequest actor_id must be a non-empty string")
        if self.session_grant is not None and not isinstance(
            self.session_grant,
            ApprovalGrantProposal,
        ):
            raise TypeError(
                "ApprovalRequest session_grant must be an ApprovalGrantProposal"
            )
        amendments = tuple(self.policy_amendments)
        if any(
            not isinstance(amendment, PolicyAmendmentProposal)
            for amendment in amendments
        ):
            raise TypeError(
                "ApprovalRequest policy_amendments must contain "
                "PolicyAmendmentProposal values"
            )
        scopes = [amendment.scope for amendment in amendments]
        if len(scopes) != len(set(scopes)):
            raise ValueError("ApprovalRequest policy amendment scopes must be unique")
        object.__setattr__(self, "policy_amendments", amendments)
        object.__setattr__(
            self,
            "arguments",
            _freeze_mapping(self.arguments),
        )

@dataclass(frozen=True)
class ApprovalDecision:
    disposition: Literal["allow", "deny", "abort"]
    reason: str | None = None
    scope: ApprovalScope = "once"
    grant_id: str | None = None
    policy_rule_id: str | None = None
    policy_scope: PolicyAmendmentScope | None = None

    def __post_init__(self) -> None:
        if self.disposition not in {"allow", "deny", "abort"}:
            raise ValueError(
                f"Unsupported approval decision disposition: {self.disposition}"
            )
        _validate_optional_string(self.reason, "ApprovalDecision reason")
        if self.scope not in {"once", "session"}:
            raise ValueError(f"Unsupported approval decision scope: {self.scope}")
        _validate_optional_string(self.grant_id, "ApprovalDecision grant_id")
        _validate_optional_string(
            self.policy_rule_id,
            "ApprovalDecision policy_rule_id",
        )
        if self.grant_id == "":
            raise ValueError("ApprovalDecision grant_id must not be empty")
        if self.disposition in {"deny", "abort"} and (
            self.scope != "once"
            or self.grant_id is not None
            or self.policy_rule_id is not None
            or self.policy_scope is not None
        ):
            raise ValueError(
                "denied and aborted approval decisions cannot carry authorization"
            )
        if self.policy_rule_id is not None:
            if self.disposition != "allow":
                raise ValueError("policy authorization requires an allowed decision")
            if self.policy_scope not in {"project", "user"}:
                raise ValueError("policy authorization requires its persistent scope")
            if self.scope != "once" or self.grant_id is not None:
                raise ValueError(
                    "policy authorization is distinct from a session approval grant"
                )
        elif self.policy_scope is not None:
            raise ValueError("policy scope requires a policy rule id")
        if self.scope == "session" and self.grant_id is None:
            raise ValueError("session approval decisions require a grant id")
        if self.scope == "once" and self.grant_id is not None:
            raise ValueError("one-shot approval decisions cannot carry a grant id")

    @classmethod
    def allow(
        cls,
        *,
        scope: ApprovalScope = "once",
        grant_id: str | None = None,
    ) -> "ApprovalDecision":
        return cls(disposition="allow", scope=scope, grant_id=grant_id)

    @classmethod
    def deny(cls, reason: str | None = None) -> "ApprovalDecision":
        return cls(disposition="deny", reason=reason)

    @classmethod
    def abort(cls, reason: str | None = None) -> "ApprovalDecision":
        return cls(disposition="abort", reason=reason)

    @classmethod
    def allow_by_policy(
        cls,
        *,
        rule_id: str,
        scope: PolicyAmendmentScope,
    ) -> "ApprovalDecision":
        return cls(
            disposition="allow",
            policy_rule_id=rule_id,
            policy_scope=scope,
        )

class ApprovalRequestCollisionError(RuntimeError):
    def __init__(self, action_id: str) -> None:
        super().__init__(
            f"Approval action id was already presented by this broker: {action_id}"
        )
        self.action_id = action_id

def approval_request_to_dict(request: ApprovalRequest) -> dict[str, object]:
    """Project a request into mutable JSON-compatible Product data."""

    if not isinstance(request, ApprovalRequest):
        raise TypeError("request must be an ApprovalRequest")
    projection: dict[str, object] = {
        "tool_name": request.tool_name,
        "arguments": _thaw_value(request.arguments),
        "cwd": request.cwd,
        "reason": request.reason,
        "policy_code": request.policy_code,
        "action_id": request.action_id,
        "action": _approval_action(request),
        "risk": request.reason or "Tool call requires approval",
        "environment": "local",
        "grant_summary": (
            request.session_grant.summary
            if request.session_grant is not None
            else None
        ),
    }
    if request.action_fingerprint is not None:
        projection["action_fingerprint"] = request.action_fingerprint
    if request.actor_id != "root":
        projection["actor_id"] = request.actor_id
    projection["approval_options"] = tuple(
        {
            "outcome": option.outcome,
            "label": option.label,
            "shortcut": option.shortcut,
            "tone": option.tone,
        }
        for option in approval_options(request)
    )
    if request.session_grant is not None:
        projection["session_grant"] = {
            "capability": request.session_grant.capability,
            "constraints": dict(request.session_grant.constraints),
            "summary": request.session_grant.summary,
        }
    if request.policy_amendments:
        projection["policy_amendments"] = tuple(
            {
                "scope": amendment.scope,
                "capability": amendment.grant.capability,
                "constraints": dict(amendment.grant.constraints),
                "summary": amendment.grant.summary,
            }
            for amendment in request.policy_amendments
        )
    return projection

def _approval_action(request: ApprovalRequest) -> str:
    command = request.arguments.get("command")
    if isinstance(command, str) and command.strip():
        return _approval_display_text(command)
    if isinstance(command, (tuple, list)) and command and all(
        isinstance(part, str) for part in command
    ):
        return _approval_display_text(shlex.join(command))
    path = request.arguments.get("path")
    if isinstance(path, str) and path.strip():
        return f"{request.tool_name} {_approval_display_text(path)}"
    return f"{request.tool_name} tool call"

def _approval_display_text(value: str) -> str:
    redacted = redact_text(value.strip())
    flattened = " ⏎ ".join(redacted.splitlines())
    safe = "".join(
        character if character.isprintable() else "�"
        for character in flattened
    )
    return safe[:2048]

def approval_options(request: ApprovalRequest) -> tuple[ApprovalOption, ...]:
    """Build the exact menu Policy permits for this action."""

    options: list[ApprovalOption] = [
        ApprovalOption("allow_once", "Allow this action once", "y"),
    ]
    if request.session_grant is not None:
        options.append(
            ApprovalOption(
                "allow_session",
                request.session_grant.summary,
                "s",
                "session",
            )
        )
    for amendment in request.policy_amendments:
        destination = "this project" if amendment.scope == "project" else "this user"
        options.append(
            ApprovalOption(
                (
                    "allow_project"
                    if amendment.scope == "project"
                    else "allow_user"
                ),
                f"Always allow for {destination}: {amendment.grant.summary}",
                "p" if amendment.scope == "project" else "u",
                "persistent",
            )
        )
    options.append(
        ApprovalOption(
            "deny",
            "Deny and let the agent continue",
            "n",
            "deny",
        )
    )
    return tuple(options)

def ensure_approval_action_id(request: ApprovalRequest) -> ApprovalRequest:
    """Return an immutable request with a correlation id."""

    if request.action_id:
        return request
    return replace(request, action_id=f"approval-{uuid4().hex}")

def _validate_optional_string(value: object, field_name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")

def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value

def _request_amendment(
    request: ApprovalRequest,
    scope: PolicyAmendmentScope,
) -> PolicyAmendmentProposal | None:
    return next(
        (
            amendment
            for amendment in request.policy_amendments
            if amendment.scope == scope
        ),
        None,
    )

def _validate_approval_decision(decision: object) -> ApprovalDecision:
    if not isinstance(decision, ApprovalDecision):
        raise TypeError("decision must be an ApprovalDecision")
    decision.__post_init__()
    return decision
