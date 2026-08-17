from __future__ import annotations

from typing import Any


def event_writes_transcript(event: dict[str, Any]) -> bool:
    event_type = event.get("type")
    if event_type == "message_start":
        message = event.get("message")
        return getattr(message, "role", None) == "user"
    if event_type == "message_end":
        message = event.get("message")
        return getattr(message, "role", None) in {"assistant", "toolResult"}
    if event_type == "tool_execution_end":
        return True
    if event_type == "agent_end":
        return _agent_end_has_visible_error(event)
    return event_type in {"auto_retry_start", "compaction_start", "compaction_end"}


def is_cancelled_error_message(message: str | None) -> bool:
    if not isinstance(message, str):
        return False
    normalized = message.strip().lower()
    return (
        normalized
        in {
            "request cancelled.",
            "request cancelled",
            "operation aborted",
            "request aborted by user",
        }
        or "aborted" in normalized
    )


def _agent_end_has_visible_error(event: dict[str, Any]) -> bool:
    if event.get("type") != "agent_end":
        return False
    messages = event.get("messages")
    if not isinstance(messages, list):
        return False
    for message in reversed(messages):
        if getattr(message, "role", None) != "assistant":
            continue
        error_message = getattr(message, "error_message", None)
        if not isinstance(error_message, str) or not error_message:
            return False
        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason not in {"error", "aborted"}:
            return False
        return not (
            stop_reason == "aborted" and is_cancelled_error_message(error_message)
        )
    return False


__all__ = ["event_writes_transcript", "is_cancelled_error_message"]
