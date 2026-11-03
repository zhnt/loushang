"""Ephemeral confirmation facts issued and validated by the Approval owner."""

from __future__ import annotations

from dataclasses import dataclass

from .requests import ApprovalDecision, ApprovalRequest


@dataclass(frozen=True, slots=True, eq=False)
class ApprovalConfirmation:
    """One exact action's confirmation, with no standalone authority.

    Only the issuing resolver can validate this identity. Copying these fields,
    serializing them or retaining them across owner close grants no permission.
    The caller must release the fact after its coordinated action settles.
    """

    request: ApprovalRequest
    decision: ApprovalDecision
