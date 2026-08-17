"""Headless, deny, and actor-bound approval resolvers."""


from __future__ import annotations

import inspect
from dataclasses import dataclass, field, replace
from typing import Literal

from loushang.harness.approval.ports import ApprovalResolver
from loushang.harness.approval.requests import (
    ApprovalDecision,
    ApprovalRequest,
    MaybeAwaitable,
    _validate_approval_decision,
)


@dataclass(slots=True)
class ActorBoundApprovalResolver:
    """Bind requests and approval lifecycle to one child incarnation."""

    resolver: ApprovalResolver
    actor_id: str
    _session_open: bool = field(default=True, init=False, repr=False)
    _session_close_reason: str = field(
        default="Child agent closed before approval was resolved",
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str) or not self.actor_id:
            raise ValueError("actor_id must be a non-empty string")

    def preauthorize(
        self,
        request: ApprovalRequest,
    ) -> MaybeAwaitable[ApprovalDecision | None]:
        if not self._session_open:
            return None
        preauthorize = getattr(self.resolver, "preauthorize", None)
        if not callable(preauthorize):
            return None
        return preauthorize(replace(request, actor_id=self.actor_id))

    def resolve(self, request: ApprovalRequest) -> MaybeAwaitable[ApprovalDecision]:
        if not self._session_open:
            return ApprovalDecision.deny(self._session_close_reason)
        return self.resolver.resolve(replace(request, actor_id=self.actor_id))

    def open_session(self) -> None:
        """Open only this actor binding; the root owns the shared resolver."""

        self._session_open = True

    def close_session(
        self,
        reason: str = "Child agent closed before approval was resolved",
    ) -> int:
        """Cancel this actor's pending requests while retaining its grants."""

        self._session_open = False
        self._session_close_reason = reason
        cancel_actor = getattr(self.resolver, "cancel_actor", None)
        if not callable(cancel_actor):
            return 0
        return int(cancel_actor(self.actor_id, reason))

    def end_session(
        self,
        reason: str = "Child agent closed before approval was resolved",
    ) -> int:
        """Release pending requests and retained grants for this incarnation."""

        completed = self.close_session(reason)
        revoke_actor_grants = getattr(self.resolver, "revoke_actor_grants", None)
        if callable(revoke_actor_grants):
            revoke_actor_grants(self.actor_id)
        return completed

@dataclass(frozen=True)
class DenyApprovalResolver:
    def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.deny(
            request.reason or f"Tool {request.tool_name} requires approval"
        )

@dataclass(frozen=True)
class HeadlessApprovalResolver:
    mode: Literal["allow", "deny"] = "deny"
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"allow", "deny"}:
            raise ValueError(f"Unsupported headless approval mode: {self.mode}")

    def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        if self.mode == "allow":
            return ApprovalDecision.allow()
        return ApprovalDecision.deny(
            self.reason
            or request.reason
            or f"Tool {request.tool_name} requires approval"
        )

async def resolve_approval(
    resolver: ApprovalResolver | None,
    request: ApprovalRequest,
) -> ApprovalDecision:
    resolved = resolver or DenyApprovalResolver()
    result = resolved.resolve(request)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, ApprovalDecision):
        raise TypeError(
            f"ApprovalResolver returned {type(result).__name__}, expected ApprovalDecision"
        )
    result.__post_init__()
    return result

async def find_approval_grant(
    resolver: ApprovalResolver | None,
    request: ApprovalRequest,
) -> ApprovalDecision | None:
    """Return a validated existing grant without presenting a new request."""

    if resolver is None:
        return None
    preauthorize = getattr(resolver, "preauthorize", None)
    if not callable(preauthorize):
        return None
    result = preauthorize(request)
    if inspect.isawaitable(result):
        result = await result
    if result is None:
        return None
    decision = _validate_approval_decision(result)
    is_session_grant = (
        decision.scope == "session" and decision.grant_id is not None
    )
    is_policy_rule = (
        decision.policy_rule_id is not None
        and decision.policy_scope in {"project", "user"}
    )
    if decision.disposition != "allow" or not (
        is_session_grant or is_policy_rule
    ):
        raise ValueError(
            "preauthorized approval must identify a session grant or Policy rule"
        )
    return decision
