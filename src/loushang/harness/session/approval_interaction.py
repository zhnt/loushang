"""Approval interaction state owned by the standard Agent session profile."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from loushang.harness.approval import (
    ApprovalOutcome,
    ApprovalPermissionsSnapshot,
    InteractiveApprovalResolver,
)
from loushang.harness.events import PermissionProfileChanged
from loushang.harness.permissions import (
    PermissionProfileScope,
    PermissionProfileSnapshot,
    permission_profile,
)
from loushang.harness.session.facade import (
    ApprovalPresentationLease,
    ApprovalRequestDismisser,
    ApprovalRequestPresenter,
)

ApprovalSessionState = Literal["active", "staged", "closed"]
EventDispatcher = Callable[[object], Awaitable[None]]


class PermissionProfileSetter(Protocol):
    def __call__(
        self,
        profile_id: str,
        *,
        scope: PermissionProfileScope,
    ) -> None: ...


@dataclass
class _AgentApprovalPresentationLease:
    close_callback: Callable[[str], None]
    closed: bool = False

    def supersede(self) -> None:
        """Invalidate this lease without closing the shared approval channel."""

        self.closed = True

    def close(
        self,
        reason: str = "Approval presenter closed before approval was resolved",
    ) -> None:
        if self.closed:
            return
        self.closed = True
        self.close_callback(reason)


@dataclass
class AgentSessionApprovalRuntime:
    """Own approval presentation, response, and lifecycle state for a session."""

    resolver: InteractiveApprovalResolver | None
    get_permission_profile_snapshot: Callable[[], PermissionProfileSnapshot]
    set_permission_profile: PermissionProfileSetter
    dispatch_event: EventDispatcher
    abort: Callable[[], object]
    _session_state: ApprovalSessionState = field(init=False, repr=False)
    _presenter_generation: int = field(default=0, init=False, repr=False)
    _presenter_lease: _AgentApprovalPresentationLease | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self._session_state = "active" if self.resolver is not None else "closed"

    @property
    def enabled(self) -> bool:
        return self.resolver is not None

    def set_presenter(
        self,
        presenter: Callable[[dict[str, object]], Awaitable[None] | None] | None,
        *,
        dismisser: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> None:
        resolver = self.resolver
        if resolver is None or self._session_state != "active":
            return
        if presenter is None:
            resolver.close_session(
                "Approval presenter closed before approval was resolved"
            )
            resolver.set_request_presenter(None)
            return
        resolver.set_request_presenter(presenter, dismisser=dismisser)
        resolver.open_session()

    def bind_presenter(
        self,
        presenter: ApprovalRequestPresenter,
        *,
        dismisser: ApprovalRequestDismisser | None = None,
    ) -> ApprovalPresentationLease:
        resolver = self.resolver
        if resolver is None or self._session_state != "active":
            raise RuntimeError("Session approval interaction is not active")
        previous = self._presenter_lease
        if previous is not None:
            previous.supersede()
        self._presenter_generation += 1
        generation = self._presenter_generation
        resolver.set_request_presenter(presenter, dismisser=dismisser)
        resolver.open_session()
        resolver.represent_pending_requests()
        lease = _AgentApprovalPresentationLease(
            lambda reason: self._close_presenter_generation(generation, reason)
        )
        self._presenter_lease = lease
        return lease

    async def respond(
        self,
        action_id: str,
        *,
        outcome: ApprovalOutcome,
        reason: str | None = None,
    ) -> bool:
        resolver = self.resolver
        if resolver is None:
            return False
        accepted = await resolver.handle_result(
            action_id=action_id,
            outcome=outcome,
            reason=reason,
        )
        if accepted and outcome == "abort":
            self.abort()
        return accepted

    async def respond_to_event(self, event: Mapping[str, object]) -> bool:
        action_id = event.get("action_id")
        if not isinstance(action_id, str):
            return False
        reason = event.get("reason")
        if reason is not None and not isinstance(reason, str):
            reason = None
        outcome = event.get("outcome")
        if outcome not in {
            "allow_once",
            "allow_session",
            "allow_project",
            "allow_user",
            "deny",
            "abort",
        }:
            scope = event.get("scope", "once")
            if scope not in {"once", "session"}:
                return False
            outcome = (
                "allow_session"
                if bool(event.get("approved")) and scope == "session"
                else "allow_once"
                if bool(event.get("approved"))
                else "deny"
            )
        return await self.respond(
            action_id,
            outcome=cast(ApprovalOutcome, outcome),
            reason=reason,
        )

    def permissions_snapshot(self) -> ApprovalPermissionsSnapshot:
        resolver = self.resolver
        if resolver is None:
            return ApprovalPermissionsSnapshot()
        return resolver.permissions_snapshot()

    def permission_profile_snapshot(self) -> PermissionProfileSnapshot:
        snapshot = self.get_permission_profile_snapshot()
        if not isinstance(snapshot, PermissionProfileSnapshot):
            raise TypeError(
                "settings permission profile getter must return "
                "PermissionProfileSnapshot"
            )
        return snapshot

    async def apply_permission_action(self, action: str) -> bool:
        kind, separator, permission_id = action.partition(":")
        if not separator or not permission_id:
            return False
        if kind == "set-profile":
            scope, scope_separator, profile_id = permission_id.partition(":")
            if (
                not scope_separator
                or scope not in {"session", "project", "user"}
                or not profile_id
            ):
                return False
            requested = permission_profile(profile_id).profile_id
            before = self.permission_profile_snapshot().effective_profile.profile_id
            typed_scope = cast(PermissionProfileScope, scope)
            self.set_permission_profile(requested, scope=typed_scope)
            after = self.permission_profile_snapshot()
            await self.dispatch_event(
                PermissionProfileChanged(
                    previous_profile_id=before,
                    requested_profile_id=requested,
                    effective_profile_id=after.effective_profile.profile_id,
                    scope=typed_scope,
                )
            )
            return True
        resolver = self.resolver
        if resolver is None:
            return False
        if kind == "reopen":
            return await resolver.represent_request(permission_id)
        if kind == "revoke":
            return resolver.revoke_grant(permission_id)
        if kind == "revoke-policy":
            return resolver.revoke_policy_rule(permission_id)
        return False

    def stage_session(self) -> None:
        self._session_state = "staged"

    def unbind_presenter(
        self,
        reason: str = "Approval presenter closed before approval was resolved",
    ) -> None:
        resolver = self.resolver
        if resolver is None:
            return
        if self._session_state == "active":
            resolver.close_session(reason)
        resolver.set_request_presenter(None)

    def open_session(self) -> None:
        resolver = self.resolver
        if resolver is None:
            return
        resolver.open_session()
        self._session_state = "active"

    def close_session(
        self,
        reason: str = "Session closed before approval was resolved",
    ) -> None:
        resolver = self.resolver
        if resolver is None or self._session_state != "active":
            return
        self._session_state = "closed"
        resolver.end_session(reason)

    def _close_presenter_generation(self, generation: int, reason: str) -> None:
        if generation != self._presenter_generation:
            return
        self._presenter_lease = None
        self.unbind_presenter(reason=reason)


__all__ = ["AgentSessionApprovalRuntime"]
