from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any, cast

from loushang.ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    ImagePart,
    Message,
    StopReason,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)
from loushang.foundation.json import JSONValue, require_json_value


def _get_key(payload: dict[str, Any], camel_key: str, snake_key: str) -> Any:
    if camel_key in payload:
        return payload[camel_key]
    return payload[snake_key]


def serialize_json_value(value: object) -> JSONValue:
    """Compatibility name for strict JSON validation at wire boundaries."""

    return require_json_value(value)


def serialize_content_part(
    part: TextPart | ImagePart | ThinkingPart | ToolCall,
) -> dict[str, Any]:
    if isinstance(part, TextPart):
        return {
            "type": "text",
            "text": part.text,
            "textSignature": part.text_signature,
        }
    if isinstance(part, ImagePart):
        return {
            "type": "image",
            "data": part.data,
            "mimeType": part.mime_type,
        }
    if isinstance(part, ThinkingPart):
        return {
            "type": "thinking",
            "thinking": part.thinking,
            "thinkingSignature": part.thinking_signature,
            "redacted": part.redacted,
        }
    if isinstance(part, ToolCall):
        return {
            "type": "toolCall",
            "id": part.id,
            "name": part.name,
            "arguments": part.arguments,
            "thoughtSignature": part.thought_signature,
        }
    raise ValueError(f"Unsupported content part type: {type(part)!r}")


def deserialize_content_part(
    payload: dict[str, Any],
) -> TextPart | ImagePart | ThinkingPart | ToolCall:
    part_type = payload["type"]
    if part_type == "text":
        return TextPart(
            type="text",
            text=payload["text"],
            text_signature=payload.get("textSignature", payload.get("text_signature")),
        )
    if part_type == "image":
        return ImagePart(
            type="image",
            data=payload["data"],
            mime_type=cast(str, payload.get("mimeType", payload.get("mime_type"))),
        )
    if part_type == "thinking":
        return ThinkingPart(
            type="thinking",
            thinking=payload["thinking"],
            thinking_signature=payload.get(
                "thinkingSignature", payload.get("thinking_signature")
            ),
            redacted=payload.get("redacted", False),
        )
    if part_type == "toolCall":
        return ToolCall(
            type="toolCall",
            id=payload["id"],
            name=payload["name"],
            arguments=payload["arguments"],
            thought_signature=payload.get(
                "thoughtSignature", payload.get("thought_signature")
            ),
        )
    raise ValueError(f"Unsupported content part type: {part_type}")


def _deserialize_user_content_part(payload: dict[str, Any]) -> TextPart | ImagePart:
    part = deserialize_content_part(payload)
    if isinstance(part, TextPart | ImagePart):
        return part
    raise ValueError(f"Unsupported user content part type: {part.type}")


def _canonical_cost(cost: Mapping[str, object] | None) -> UsageCost | None:
    if cost is None:
        return None
    input_cost = _cost_number(cost, "input")
    output_cost = _cost_number(cost, "output")
    cache_read = _cost_number(cost, "cacheRead", "cache_read")
    cache_write = _cost_number(cost, "cacheWrite", "cache_write")
    total = _cost_number(cost, "total")
    if (
        input_cost is None
        or output_cost is None
        or cache_read is None
        or cache_write is None
        or total is None
    ):
        return None
    return {
        "input": input_cost,
        "output": output_cost,
        "cacheRead": cache_read,
        "cacheWrite": cache_write,
        "total": total,
    }


def _cost_number(
    cost: Mapping[str, object], key: str, alias: str | None = None
) -> float | None:
    if key in cost:
        value = cost[key]
    elif alias is not None and alias in cost:
        value = cost[alias]
    else:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not isfinite(value)
        or value < 0
    ):
        return None
    return float(value)


def serialize_usage(usage: Usage) -> dict[str, Any]:
    return {
        "input": usage.input,
        "output": usage.output,
        "cacheRead": usage.cache_read,
        "cacheWrite": usage.cache_write,
        "totalTokens": usage.total_tokens,
        "cost": _canonical_cost(usage.cost),
    }


def deserialize_usage(payload: dict[str, Any]) -> Usage:
    cost = payload.get("cost")
    return Usage(
        input=payload["input"],
        output=payload["output"],
        cache_read=_get_key(payload, "cacheRead", "cache_read"),
        cache_write=_get_key(payload, "cacheWrite", "cache_write"),
        total_tokens=_get_key(payload, "totalTokens", "total_tokens"),
        cost=_canonical_cost(cost if isinstance(cost, dict) else None),
    )


def serialize_message(message: Message) -> dict[str, Any]:
    if isinstance(message, UserMessage):
        content = message.content
        return {
            "role": "user",
            "content": (
                [serialize_content_part(part) for part in content]
                if isinstance(content, list)
                else content
            ),
            "timestamp": message.timestamp,
        }
    if isinstance(message, AssistantMessage):
        payload: dict[str, Any] = {
            "role": "assistant",
            "content": [serialize_content_part(part) for part in message.content],
            "api": message.api,
            "provider": message.provider,
            "endpoint": message.endpoint,
            "model": message.model,
            "responseId": message.response_id,
            "usage": serialize_usage(message.usage),
            "stopReason": message.stop_reason,
            "errorMessage": message.error_message,
            "timestamp": message.timestamp,
        }
        if message.response_model is not None:
            payload["responseModel"] = message.response_model
        if message.error_info is not None:
            payload["errorInfo"] = serialize_json_value(message.error_info)
        return payload
    if isinstance(message, ToolResultMessage):
        if type(message.terminate) is not bool:
            raise TypeError("toolResult.terminate must be a boolean")
        if type(message.is_error) is not bool:
            raise TypeError("toolResult.isError must be a boolean")
        tool_payload: dict[str, Any] = {
            "role": "toolResult",
            "toolCallId": message.tool_call_id,
            "toolName": message.tool_name,
            "content": [serialize_content_part(part) for part in message.content],
            "isError": message.is_error,
            "timestamp": message.timestamp,
            "details": require_json_value(
                message.details,
                name="message.details",
            ),
        }
        if message.terminate:
            tool_payload["terminate"] = True
        return tool_payload
    raise ValueError(f"Unsupported AI message type: {type(message)!r}")


def _deserialize_error_info(
    payload: Mapping[str, Any],
) -> dict[str, JSONValue] | None:
    raw = payload.get("errorInfo", payload.get("error_info"))
    if raw is None:
        return None
    normalized = require_json_value(raw, name="assistant.errorInfo")
    if not isinstance(normalized, dict):
        raise ValueError("assistant.errorInfo must be an object")
    return normalized


def deserialize_message(payload: dict[str, Any]) -> Message:
    role = payload["role"]
    if role == "user":
        content = payload["content"]
        return UserMessage(
            role="user",
            content=(
                [_deserialize_user_content_part(part) for part in content]
                if isinstance(content, list)
                else content
            ),
            timestamp=payload["timestamp"],
        )
    if role == "assistant":
        return AssistantMessage(
            role="assistant",
            content=[deserialize_content_part(part) for part in payload["content"]],
            api=payload["api"],
            provider=payload["provider"],
            endpoint=payload["endpoint"],
            model=payload["model"],
            response_id=payload.get("responseId", payload.get("response_id")),
            usage=deserialize_usage(payload["usage"]),
            stop_reason=cast(
                StopReason,
                payload.get("stopReason", payload.get("stop_reason")),
            ),
            error_message=payload.get("errorMessage", payload.get("error_message")),
            timestamp=payload["timestamp"],
            response_model=payload.get("responseModel", payload.get("response_model")),
            error_info=_deserialize_error_info(payload),
        )
    if role == "toolResult":
        terminate = payload.get("terminate", False)
        if type(terminate) is not bool:
            raise ValueError("toolResult.terminate must be a boolean")
        is_error = payload.get("isError", payload.get("is_error"))
        if type(is_error) is not bool:
            raise ValueError("toolResult.isError must be a boolean")
        return ToolResultMessage(
            role="toolResult",
            tool_call_id=cast(
                str, payload.get("toolCallId", payload.get("tool_call_id"))
            ),
            tool_name=cast(str, payload.get("toolName", payload.get("tool_name"))),
            content=[
                _deserialize_user_content_part(part) for part in payload["content"]
            ],
            is_error=is_error,
            timestamp=payload["timestamp"],
            details=require_json_value(
                payload.get("details"),
                name="message.details",
            ),
            terminate=terminate,
        )
    raise ValueError(f"Unsupported AI message role: {role}")


def serialize_assistant_message_event(
    event: AssistantMessageEvent,
) -> dict[str, Any]:
    raw_event = cast(Mapping[str, Any], event)
    payload: dict[str, Any] = {"type": raw_event["type"]}
    event_type = raw_event["type"]

    if "partial" in raw_event:
        payload["partial"] = serialize_message(raw_event["partial"])
    if event_type == "start":
        return payload
    if event_type in {
        "text_start",
        "thinking_start",
        "toolcall_start",
        "image_start",
    }:
        payload["contentIndex"] = raw_event["content_index"]
        return payload
    if event_type in {"text_delta", "thinking_delta", "toolcall_delta"}:
        payload["contentIndex"] = raw_event["content_index"]
        payload["delta"] = raw_event["delta"]
        return payload
    if event_type in {"text_end", "thinking_end"}:
        payload["contentIndex"] = raw_event["content_index"]
        payload["content"] = raw_event["content"]
        return payload
    if event_type == "toolcall_end":
        payload["contentIndex"] = raw_event["content_index"]
        payload["toolCall"] = serialize_content_part(raw_event["tool_call"])
        return payload
    if event_type == "image_end":
        payload["contentIndex"] = raw_event["content_index"]
        payload["image"] = serialize_content_part(raw_event["image"])
        return payload
    if event_type == "done":
        payload["reason"] = raw_event["reason"]
        payload["message"] = serialize_message(raw_event["message"])
        return payload
    if event_type == "error":
        payload["reason"] = raw_event["reason"]
        payload["error"] = serialize_message(raw_event["error"])
        return payload
    raise ValueError(f"Unsupported assistant message event type: {event_type}")


# Accepted compatibility names used by product adapters.
serialize_ai_message = serialize_message
deserialize_ai_message = deserialize_message


__all__ = [
    "deserialize_ai_message",
    "deserialize_content_part",
    "deserialize_message",
    "deserialize_usage",
    "serialize_ai_message",
    "serialize_assistant_message_event",
    "serialize_content_part",
    "serialize_json_value",
    "serialize_message",
    "serialize_usage",
]
