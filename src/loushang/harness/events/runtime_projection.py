"""Project shared session runtime facts into the standard event payload shape."""

from __future__ import annotations

from collections.abc import Mapping

from loushang.harness.events.session import (
    BranchSummaryCompleted,
    BranchSummaryStarted,
    ContextCompactionCompleted,
    ContextCompactionStarted,
    ConversationMetadataChanged,
    PackageProgressChanged,
    QueueChanged,
    RetryCompleted,
    RetryStarted,
    ToolPolicyAuditEvent,
)
from loushang.harness.events.types import RuntimeEvent

SessionRuntimeEventViewPayload = dict[str, object]


def project_session_runtime_event(
    event: RuntimeEvent[object],
) -> SessionRuntimeEventViewPayload | None:
    """Project one common runtime fact into the standard session event payload.

    The projection contains only the shared session event vocabulary. Product
    hosts can add their transport envelope and presentation fields afterwards.
    """

    payload = event.payload
    if isinstance(payload, Mapping):
        event_type = payload.get("type")
        if isinstance(event_type, str):
            return payload if isinstance(payload, dict) else dict(payload)
        return None
    if isinstance(payload, QueueChanged):
        return {
            "type": "queue_update",
            "steering": [item.text for item in payload.snapshot.steering],
            "follow_up": [item.text for item in payload.snapshot.follow_up],
        }
    if isinstance(payload, ContextCompactionStarted):
        result: SessionRuntimeEventViewPayload = {
            "type": "compaction_start",
            "reason": payload.reason,
        }
        if payload.usage is not None:
            result["usage"] = payload.usage
        for name in ("stage", "product_id", "session_id", "tokens_before"):
            value = getattr(payload, name)
            if value is not None:
                result[name] = value
        return result
    if isinstance(payload, ContextCompactionCompleted):
        result = {
            "type": "compaction_end",
            "reason": payload.reason,
            "result": payload.result,
            "aborted": payload.aborted,
            "will_retry": payload.will_retry,
        }
        if payload.error_message is not None:
            result["error_message"] = payload.error_message
        if payload.usage_before is not None:
            result["usage_before"] = payload.usage_before
        if payload.usage_after is not None:
            result["usage_after"] = payload.usage_after
        for name in (
            "stage",
            "product_id",
            "session_id",
            "duration_ms",
            "tokens_before",
            "tokens_after",
            "checkpoint_record_id",
        ):
            value = getattr(payload, name)
            if value is not None:
                result[name] = value
        return result
    if isinstance(payload, RetryStarted):
        attempt = payload.attempt
        return {
            "type": "auto_retry_start",
            "attempt": attempt.attempt,
            "max_attempts": attempt.max_attempts,
            "delay_ms": attempt.delay_ms,
            "error_message": attempt.error,
        }
    if isinstance(payload, RetryCompleted):
        outcome = payload.outcome
        result = {
            "type": "auto_retry_end",
            "success": outcome.success,
            "attempt": outcome.attempt,
        }
        if not outcome.success and outcome.error is not None:
            result["final_error"] = outcome.error
        return result
    if isinstance(payload, BranchSummaryStarted):
        return {
            "type": "branch_summary_start",
            "target_id": payload.target_id,
            "old_leaf_id": payload.old_leaf_id,
            "summarize": payload.summarize,
        }
    if isinstance(payload, BranchSummaryCompleted):
        result = {
            "type": "branch_summary_end",
            "target_id": payload.target_id,
            "old_leaf_id": payload.old_leaf_id,
            "new_leaf_id": payload.new_leaf_id,
            "summary_entry_id": payload.summary_record_id,
            "cancelled": payload.cancelled,
            "aborted": payload.aborted,
        }
        if payload.error_message is not None:
            result["error_message"] = payload.error_message
        return result
    if isinstance(payload, ConversationMetadataChanged):
        return {"type": "session_info_changed", "name": payload.name}
    if isinstance(payload, PackageProgressChanged):
        return {
            "type": "package_progress",
            "progress_type": payload.progress_type,
            "action": payload.action,
            "source": payload.source,
            "message": payload.message,
            "target_path": payload.target_path,
        }
    if isinstance(payload, ToolPolicyAuditEvent):
        return {"type": payload.event_type, **dict(payload.details)}
    return None


__all__ = ["SessionRuntimeEventViewPayload", "project_session_runtime_event"]
