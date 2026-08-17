"""Approval resolver and presenter ports plus payload projection."""


from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from loushang.harness.approval.requests import (
    ApprovalDecision,
    ApprovalRequest,
    MaybeAwaitable,
)


class ApprovalResolver(Protocol):
    def resolve(self, request: ApprovalRequest) -> MaybeAwaitable[ApprovalDecision]: ...

def approval_actor_id(resolver: ApprovalResolver | None) -> str:
    """Return the stable actor bound to a resolver, defaulting to Root."""

    actor_id = getattr(resolver, "actor_id", None)
    return actor_id if isinstance(actor_id, str) and actor_id else "root"

class ApprovalPresenter(Protocol):
    def present(self, request: ApprovalRequest) -> MaybeAwaitable[None]: ...

ApprovalPayloadProjector = Callable[[ApprovalRequest], Mapping[str, object]]
