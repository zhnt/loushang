"""Shared session event dictionaries projected from runtime facts."""

from __future__ import annotations

from typing import Literal, NotRequired, TypeAlias, TypedDict

from loushang.agent.types import AgentEvent
from loushang.harness.events.session import (
    CompactionReason,
    CompactionStage,
    PackageProgressAction,
    PackageProgressType,
)


class QueueUpdateEvent(TypedDict):
    type: Literal["queue_update"]
    steering: list[str]
    follow_up: list[str]


class CompactionStartEvent(TypedDict):
    type: Literal["compaction_start"]
    reason: CompactionReason
    usage: NotRequired[object]
    stage: NotRequired[CompactionStage]
    product_id: NotRequired[str]
    session_id: NotRequired[str]
    tokens_before: NotRequired[int]


class CompactionEndEvent(TypedDict):
    type: Literal["compaction_end"]
    reason: CompactionReason
    result: object | None
    aborted: bool
    will_retry: bool
    error_message: NotRequired[str]
    usage_before: NotRequired[object]
    usage_after: NotRequired[object]
    stage: NotRequired[CompactionStage]
    product_id: NotRequired[str]
    session_id: NotRequired[str]
    duration_ms: NotRequired[float]
    tokens_before: NotRequired[int]
    tokens_after: NotRequired[int]
    checkpoint_record_id: NotRequired[str]


class AutoRetryStartEvent(TypedDict):
    type: Literal["auto_retry_start"]
    attempt: int
    max_attempts: int
    delay_ms: int
    error_message: str


class AutoRetryEndEvent(TypedDict):
    type: Literal["auto_retry_end"]
    success: bool
    attempt: int
    final_error: NotRequired[str]


class BranchSummaryStartEvent(TypedDict):
    type: Literal["branch_summary_start"]
    target_id: str
    old_leaf_id: str | None
    summarize: bool


class BranchSummaryEndEvent(TypedDict):
    type: Literal["branch_summary_end"]
    target_id: str
    old_leaf_id: str | None
    new_leaf_id: str | None
    summary_entry_id: str | None
    cancelled: bool
    aborted: bool
    error_message: NotRequired[str]


class SessionInfoChangedEvent(TypedDict):
    type: Literal["session_info_changed"]
    name: str | None


class PackageProgressSessionEvent(TypedDict):
    type: Literal["package_progress"]
    progress_type: PackageProgressType
    action: PackageProgressAction
    source: str
    message: str | None
    target_path: str | None


class ToolPolicyAuditSessionEvent(TypedDict):
    type: Literal[
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_approval_requested",
        "tool_approval_resolved",
        "tool_execution_started",
        "tool_execution_completed",
        "tool_execution_failed",
    ]
    tool_name: NotRequired[str]
    tool_call_id: NotRequired[str]
    action_fingerprint: NotRequired[str]
    capability: NotRequired[str]
    action_summary: NotRequired[dict[str, object]]
    command_summary: NotRequired[dict[str, object]]
    action_id: NotRequired[str]
    approval_action_id: NotRequired[str]
    policy_disposition: NotRequired[str]
    policy_code: NotRequired[str]
    approval_required: NotRequired[bool]
    approval_decision: NotRequired[str]
    execution_profile: NotRequired[dict[str, object]]
    outcome: NotRequired[str]
    phase: NotRequired[str]


AgentSessionEvent: TypeAlias = (
    AgentEvent
    | QueueUpdateEvent
    | CompactionStartEvent
    | CompactionEndEvent
    | AutoRetryStartEvent
    | AutoRetryEndEvent
    | BranchSummaryStartEvent
    | BranchSummaryEndEvent
    | SessionInfoChangedEvent
    | PackageProgressSessionEvent
    | ToolPolicyAuditSessionEvent
)


__all__ = [
    "AgentSessionEvent",
    "AutoRetryEndEvent",
    "AutoRetryStartEvent",
    "BranchSummaryEndEvent",
    "BranchSummaryStartEvent",
    "CompactionEndEvent",
    "CompactionStartEvent",
    "PackageProgressSessionEvent",
    "QueueUpdateEvent",
    "SessionInfoChangedEvent",
    "ToolPolicyAuditSessionEvent",
]
