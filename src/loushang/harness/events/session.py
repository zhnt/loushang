from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypeAlias

from loushang.harness.permissions import PermissionProfileId, PermissionProfileScope

CompactionReason: TypeAlias = Literal["manual", "threshold", "overflow"]
CompactionStage: TypeAlias = Literal[
    "started",
    "aborted",
    "failed",
    "committed",
    "post_hook_failed",
]
PackageProgressType: TypeAlias = Literal["start", "progress", "complete", "error"]
PackageProgressAction: TypeAlias = Literal[
    "install", "update", "remove", "check", "resolve"
]
QueueKind: TypeAlias = Literal["steering", "follow_up"]
ToolPolicyAuditEventType: TypeAlias = Literal[
    "tool_action_frozen",
    "tool_policy_evaluated",
    "tool_approval_requested",
    "tool_approval_resolved",
    "tool_execution_started",
    "tool_execution_completed",
    "tool_execution_failed",
]


@dataclass(frozen=True)
class QueuedMessageSnapshot:
    id: str
    kind: QueueKind
    text: str


@dataclass(frozen=True)
class QueueSnapshot:
    steering: tuple[QueuedMessageSnapshot, ...] = ()
    follow_up: tuple[QueuedMessageSnapshot, ...] = ()


@dataclass(frozen=True)
class RetryAttempt:
    attempt: int
    max_attempts: int
    delay_ms: int
    error: str


@dataclass(frozen=True)
class RetryOutcome:
    success: bool
    attempt: int
    error: str | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class QueueChanged:
    snapshot: QueueSnapshot


@dataclass(frozen=True)
class ContextCompactionStarted:
    reason: CompactionReason
    usage: Mapping[str, object] | None = None
    stage: CompactionStage | None = None
    product_id: str | None = None
    session_id: str | None = None
    tokens_before: int | None = None


@dataclass(frozen=True)
class ContextCompactionCompleted:
    reason: CompactionReason
    result: object | None
    aborted: bool
    will_retry: bool
    error_message: str | None = None
    usage_before: Mapping[str, object] | None = None
    usage_after: Mapping[str, object] | None = None
    stage: CompactionStage | None = None
    product_id: str | None = None
    session_id: str | None = None
    duration_ms: float | None = None
    tokens_before: int | None = None
    tokens_after: int | None = None
    checkpoint_record_id: str | None = None


@dataclass(frozen=True)
class RetryStarted:
    attempt: RetryAttempt


@dataclass(frozen=True)
class RetryCompleted:
    outcome: RetryOutcome


@dataclass(frozen=True)
class BranchSummaryStarted:
    target_id: str
    old_leaf_id: str | None
    summarize: bool


@dataclass(frozen=True)
class BranchSummaryCompleted:
    target_id: str
    old_leaf_id: str | None
    new_leaf_id: str | None
    summary_record_id: str | None
    cancelled: bool
    aborted: bool
    error_message: str | None = None


@dataclass(frozen=True)
class ConversationMetadataChanged:
    name: str | None


@dataclass(frozen=True)
class PackageProgressChanged:
    progress_type: PackageProgressType
    action: PackageProgressAction
    source: str
    message: str | None = None
    target_path: str | None = None


@dataclass(frozen=True)
class ToolPolicyAuditEvent:
    event_type: ToolPolicyAuditEventType
    details: Mapping[str, object]


@dataclass(frozen=True)
class PermissionProfileChanged:
    previous_profile_id: PermissionProfileId
    requested_profile_id: PermissionProfileId
    effective_profile_id: PermissionProfileId
    scope: PermissionProfileScope


SessionRuntimeEventPayload: TypeAlias = (
    QueueChanged
    | ContextCompactionStarted
    | ContextCompactionCompleted
    | RetryStarted
    | RetryCompleted
    | BranchSummaryStarted
    | BranchSummaryCompleted
    | ConversationMetadataChanged
    | PackageProgressChanged
    | ToolPolicyAuditEvent
    | PermissionProfileChanged
)

_EVENT_KINDS: dict[type[object], str] = {
    QueueChanged: "session.queue_update",
    ContextCompactionStarted: "session.compaction_start",
    ContextCompactionCompleted: "session.compaction_end",
    RetryStarted: "session.auto_retry_start",
    RetryCompleted: "session.auto_retry_end",
    BranchSummaryStarted: "session.branch_summary_start",
    BranchSummaryCompleted: "session.branch_summary_end",
    ConversationMetadataChanged: "session.session_info_changed",
    PackageProgressChanged: "session.package_progress",
    PermissionProfileChanged: "session.permission_profile_changed",
}


def session_runtime_event_kind(payload: SessionRuntimeEventPayload) -> str:
    """Return the stable runtime kind for one common Session fact."""

    if isinstance(payload, ToolPolicyAuditEvent):
        return f"session.{payload.event_type}"
    try:
        return _EVENT_KINDS[type(payload)]
    except KeyError as exc:
        raise TypeError(
            f"unsupported Session runtime event payload: {type(payload).__name__}"
        ) from exc


__all__ = [
    "BranchSummaryCompleted",
    "BranchSummaryStarted",
    "CompactionReason",
    "CompactionStage",
    "ContextCompactionCompleted",
    "ContextCompactionStarted",
    "ConversationMetadataChanged",
    "PackageProgressAction",
    "PackageProgressChanged",
    "PackageProgressType",
    "PermissionProfileChanged",
    "QueueChanged",
    "QueuedMessageSnapshot",
    "QueueKind",
    "QueueSnapshot",
    "RetryAttempt",
    "RetryCompleted",
    "RetryOutcome",
    "RetryStarted",
    "SessionRuntimeEventPayload",
    "ToolPolicyAuditEvent",
    "ToolPolicyAuditEventType",
    "session_runtime_event_kind",
]
