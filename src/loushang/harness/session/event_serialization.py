from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from loushang.agent.types import AgentMessage, AgentToolResult
from loushang.ai.types import AssistantMessageEvent
from loushang.foundation.json import require_json_value
from loushang.harness.events.json import snake_case_json_keys


def serialize_agent_message(message: object) -> object:
    from loushang.harness.transcript import create_agent_transcript_message_codec

    return create_agent_transcript_message_codec().serialize(
        cast(AgentMessage, message)
    )


def serialize_tool_result(message: object) -> object:
    from loushang.agent.json_codec import serialize_tool_result as serialize

    return serialize(cast(AgentToolResult[Any], message))


def serialize_session_event(event: Mapping[str, object]) -> dict[str, Any]:
    return snake_case_json_keys(_serialize_session_event(event))  # type: ignore[return-value]


def _serialize_session_event(event: Mapping[str, object]) -> dict[str, Any]:
    event_type = event["type"]

    if event_type in {"agent_start", "turn_start"}:
        return {"type": event_type}
    if event_type == "agent_end":
        return {
            "type": event_type,
            "messages": [
                serialize_agent_message(message)
                for message in cast(list[object], event["messages"])
            ],
        }
    if event_type == "turn_end":
        return {
            "type": event_type,
            "message": serialize_agent_message(event["message"]),
            "tool_results": [
                serialize_agent_message(message)
                for message in cast(list[object], event["tool_results"])
            ],
        }
    if event_type == "message_start":
        return {
            "type": event_type,
            "message": serialize_agent_message(event["message"]),
        }
    if event_type == "message_update":
        from loushang.ai.json_codec import serialize_assistant_message_event

        return {
            "type": event_type,
            "message": serialize_agent_message(event["message"]),
            "assistant_message_event": serialize_assistant_message_event(
                cast(AssistantMessageEvent, event["assistant_message_event"])
            ),
        }
    if event_type == "message_end":
        return {
            "type": event_type,
            "message": serialize_agent_message(event["message"]),
        }
    if event_type == "tool_execution_start":
        return {
            "type": event_type,
            "tool_call_id": event["tool_call_id"],
            "tool_name": event["tool_name"],
            "args": require_json_value(event["args"], name="tool_event.args"),
        }
    if event_type == "tool_execution_update":
        return {
            "type": event_type,
            "tool_call_id": event["tool_call_id"],
            "tool_name": event["tool_name"],
            "args": require_json_value(event["args"], name="tool_event.args"),
            "partial_result": serialize_tool_result(event["partial_result"]),
        }
    if event_type == "tool_execution_end":
        payload = {
            "type": event_type,
            "tool_call_id": event["tool_call_id"],
            "tool_name": event["tool_name"],
            "result": serialize_tool_result(event["result"]),
            "is_error": event["is_error"],
        }
        if "duration_ms" in event:
            payload["duration_ms"] = event["duration_ms"]
        return payload
    if event_type == "queue_update":
        return {
            "type": event_type,
            "steering": list(cast(list[object], event["steering"])),
            "follow_up": list(cast(list[object], event["follow_up"])),
        }
    if event_type == "session_info_changed":
        return {"type": event_type, "name": event["name"]}
    if event_type == "compaction_start":
        from loushang.harness.context import serialize_context_usage_payload

        compaction_payload: dict[str, Any] = {
            "type": event_type,
            "reason": event["reason"],
        }
        if "usage" in event:
            compaction_payload["usage"] = serialize_context_usage_payload(
                event["usage"]
            )
        for name in ("stage", "product_id", "session_id", "tokens_before"):
            if name in event:
                compaction_payload[name] = event[name]
        return compaction_payload
    if event_type == "compaction_end":
        from loushang.harness.context import serialize_context_usage_payload

        compaction_end_payload: dict[str, Any] = {
            "type": event_type,
            "reason": event["reason"],
            "result": require_json_value(
                event["result"],
                name="compaction_event.result",
            ),
            "aborted": event["aborted"],
            "will_retry": event["will_retry"],
        }
        if "usage_before" in event:
            compaction_end_payload["usage_before"] = serialize_context_usage_payload(
                event["usage_before"]
            )
        if "usage_after" in event:
            compaction_end_payload["usage_after"] = serialize_context_usage_payload(
                event["usage_after"]
            )
        if "error_message" in event:
            compaction_end_payload["error_message"] = event["error_message"]
        for name in (
            "stage",
            "product_id",
            "session_id",
            "duration_ms",
            "tokens_before",
            "tokens_after",
            "checkpoint_record_id",
        ):
            if name in event:
                compaction_end_payload[name] = event[name]
        return compaction_end_payload
    if event_type == "auto_retry_start":
        return {
            "type": event_type,
            "attempt": event["attempt"],
            "max_attempts": event["max_attempts"],
            "delay_ms": event["delay_ms"],
            "error_message": event["error_message"],
        }
    if event_type == "auto_retry_end":
        payload = {
            "type": event_type,
            "success": event["success"],
            "attempt": event["attempt"],
        }
        if "final_error" in event:
            payload["final_error"] = event["final_error"]
        return payload
    if event_type == "package_progress":
        return {
            "type": event_type,
            "progress_type": event["progress_type"],
            "action": event["action"],
            "source": event["source"],
            "message": event["message"],
            "target_path": event["target_path"],
        }
    if event_type == "branch_summary_start":
        return {
            "type": event_type,
            "target_id": event["target_id"],
            "old_leaf_id": event["old_leaf_id"],
            "summarize": event["summarize"],
        }
    if event_type == "branch_summary_end":
        payload = {
            "type": event_type,
            "target_id": event["target_id"],
            "old_leaf_id": event["old_leaf_id"],
            "new_leaf_id": event["new_leaf_id"],
            "summary_entry_id": event["summary_entry_id"],
            "cancelled": event["cancelled"],
            "aborted": event["aborted"],
        }
        if "error_message" in event:
            payload["error_message"] = event["error_message"]
        return payload
    raise ValueError(f"Unsupported session event type: {event_type}")


__all__ = ["serialize_session_event"]
