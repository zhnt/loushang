"""Product-neutral approval lifecycle: requests, broker, grants, and retained rules.

Implements the grant model (§9) and approval lifecycle (§10) of
docs/internals/architecture/harness/policy-approval-redesign.md. The package
splits the mechanism into focused modules: `requests` (request/decision/
option values and projections), `ports` (resolver/presenter protocols),
`grants` (session grants and snapshots), `rules` (retained rule stores),
`resolvers` (headless/deny/actor-bound resolvers), `broker` (the
complete-once broker and interactive resolver), and `proposals` (grant and
policy-amendment proposals). Interactive presenters, product risk wording,
and persisted allowlist policy remain with Product adapters. Terminology
(policy rule vs retained approval rule, grant proposal vs grant, the three
"permission" concepts) is defined in policy-approval-redesign.md section 7.0.
"""

from loushang.harness.approval.broker import (
    ApprovalBroker,
    InteractiveApprovalResolver,
)
from loushang.harness.approval.grants import (
    ApprovalGrant,
    ApprovalPermission,
    ApprovalPermissionsSnapshot,
    InMemoryApprovalGrantStore,
)
from loushang.harness.approval.ports import (
    ApprovalPayloadProjector,
    ApprovalPresenter,
    ApprovalResolver,
    approval_actor_id,
)
from loushang.harness.approval.requests import (
    ApprovalDecision,
    ApprovalGrantProposal,
    ApprovalOption,
    ApprovalOutcome,
    ApprovalRequest,
    ApprovalRequestCollisionError,
    ApprovalScope,
    MaybeAwaitable,
    PolicyAmendmentProposal,
    PolicyAmendmentScope,
    approval_options,
    approval_request_to_dict,
    ensure_approval_action_id,
)
from loushang.harness.approval.resolvers import (
    ActorBoundApprovalResolver,
    DenyApprovalResolver,
    HeadlessApprovalResolver,
    find_approval_grant,
    resolve_approval,
)
from loushang.harness.approval.rules import (
    ApprovalPolicyRule,
    ApprovalPolicyRuleStore,
    InMemoryApprovalPolicyRuleStore,
    JsonApprovalPolicyRuleStore,
    configure_persistent_approval_policy,
)

__all__ = [
    "ActorBoundApprovalResolver",
    "ApprovalBroker",
    "ApprovalDecision",
    "ApprovalGrant",
    "ApprovalGrantProposal",
    "ApprovalOption",
    "ApprovalOutcome",
    "ApprovalPolicyRule",
    "ApprovalPolicyRuleStore",
    "ApprovalPermission",
    "ApprovalPermissionsSnapshot",
    "ApprovalScope",
    "ApprovalPresenter",
    "ApprovalRequest",
    "ApprovalRequestCollisionError",
    "ApprovalResolver",
    "approval_actor_id",
    "DenyApprovalResolver",
    "HeadlessApprovalResolver",
    "InMemoryApprovalGrantStore",
    "InMemoryApprovalPolicyRuleStore",
    "InteractiveApprovalResolver",
    "JsonApprovalPolicyRuleStore",
    "MaybeAwaitable",
    "PolicyAmendmentProposal",
    "PolicyAmendmentScope",
    "ApprovalPayloadProjector",
    "approval_options",
    "approval_request_to_dict",
    "configure_persistent_approval_policy",
    "ensure_approval_action_id",
    "find_approval_grant",
    "resolve_approval",
]
