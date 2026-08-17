"""Session-scoped approval grants, stores, and permission snapshots.

An approval permissions snapshot (`ApprovalPermissionsSnapshot`) is a read
model of pending requests, session grants, and retained rules; it is not a
permission profile (`loushang.harness.permissions.PermissionProfile`) or an
effective execution profile
(`loushang.harness.authorization.EffectiveExecutionProfile`). See the
terminology conventions in policy-approval-redesign.md section 7.0.
"""


from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from loushang.harness.approval.requests import (
    ApprovalGrantProposal,
    ApprovalRequest,
)


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    grant_id: str
    actor_id: str
    proposal: ApprovalGrantProposal
    source_action_id: str

@dataclass(frozen=True, slots=True)
class ApprovalPermission:
    """Safe read model for one pending request or retained session grant."""

    kind: Literal["pending", "session", "project", "user"]
    permission_id: str
    actor_id: str
    capability: str
    summary: str

@dataclass(frozen=True, slots=True)
class ApprovalPermissionsSnapshot:
    """Product-neutral permissions page input without raw tool arguments."""

    pending: tuple[ApprovalPermission, ...] = ()
    grants: tuple[ApprovalPermission, ...] = ()
    project_rules: tuple[ApprovalPermission, ...] = ()
    user_rules: tuple[ApprovalPermission, ...] = ()

class InMemoryApprovalGrantStore:
    """Session-owned grants; disposing the resolver revokes the whole store."""

    def __init__(self) -> None:
        self._grants: dict[
            tuple[str, ApprovalGrantProposal],
            ApprovalGrant,
        ] = {}

    def find(self, request: ApprovalRequest) -> ApprovalGrant | None:
        proposal = request.session_grant
        if proposal is None:
            return None
        return self._grants.get((request.actor_id, proposal))

    def issue(self, request: ApprovalRequest) -> ApprovalGrant:
        proposal = request.session_grant
        if proposal is None:
            raise ValueError("approval request has no safe session grant proposal")
        action_id = request.action_id
        if action_id is None:
            raise ValueError("approval request must have an action id before granting")
        grant = ApprovalGrant(
            grant_id=f"grant-{uuid4().hex}",
            actor_id=request.actor_id,
            proposal=proposal,
            source_action_id=action_id,
        )
        self._grants[(request.actor_id, proposal)] = grant
        return grant

    def revoke(self, grant_id: str) -> bool:
        for key, grant in tuple(self._grants.items()):
            if grant.grant_id == grant_id:
                self._grants.pop(key, None)
                return True
        return False

    def revoke_actor(self, actor_id: str) -> int:
        """Revoke grants owned by one actor without disturbing its siblings."""

        keys = tuple(key for key in self._grants if key[0] == actor_id)
        for key in keys:
            self._grants.pop(key, None)
        return len(keys)

    def clear(self) -> int:
        count = len(self._grants)
        self._grants.clear()
        return count

    def grants(self) -> tuple[ApprovalGrant, ...]:
        return tuple(self._grants.values())
