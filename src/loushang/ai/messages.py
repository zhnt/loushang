from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any, cast

from loushang.ai.diagnostics import (
    NormalizationDiagnostic,
    sort_normalization_diagnostics,
)
from loushang.ai.errors import AIRequestValidationError
from loushang.ai.model.registry import resolve_model_api
from loushang.ai.tool import (
    normalize_tool_call_id_for_model,
)
from loushang.ai.tool.transform import (
    PairingMode,
    coerce_cross_provider_assistant_message_result,
    transform_messages_result,
)
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    TextPart,
    ThinkingPart,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)


@dataclass(frozen=True)
class MessageNormalizationResult:
    messages: list[object]
    diagnostics: tuple[NormalizationDiagnostic, ...] = ()


def normalize_messages(
    messages: list[object],
    *,
    tools: list[Tool] | None = None,
    model=None,
    pairing_mode: PairingMode = "strict",
) -> list[object]:
    return normalize_messages_result(
        messages,
        tools=tools,
        model=model,
        pairing_mode=pairing_mode,
    ).messages


def normalize_messages_result(
    messages: list[object],
    *,
    tools: list[Tool] | None = None,
    model=None,
    pairing_mode: PairingMode = "strict",
    message_paths: list[str] | None = None,
) -> MessageNormalizationResult:
    messages = [canonicalize_message(message) for message in messages]
    diagnostics: list[NormalizationDiagnostic] = []
    normalize_tool_call_id = None
    if model is not None:

        def _normalize_tool_call_id(
            tool_call_id: str, _message: AssistantMessage
        ) -> str:
            return normalize_tool_call_id_for_model(tool_call_id, model)

        normalize_tool_call_id = _normalize_tool_call_id

    transform_result = transform_messages_result(
        messages,
        normalize_tool_call_id=normalize_tool_call_id,
        pairing_mode=pairing_mode,
        message_paths=message_paths,
    )
    transformed = transform_result.messages
    transformed_paths = list(transform_result.message_paths)
    diagnostics.extend(transform_result.diagnostics)
    transformed = [canonicalize_user_message(message) for message in transformed]

    if model is not None:
        target_api = resolve_model_api(model)
        if isinstance(target_api, str) and target_api:
            coerced: list[object] = []
            for index, message in enumerate(transformed):
                if not isinstance(message, AssistantMessage):
                    coerced.append(message)
                    continue
                coercion_result = coerce_cross_provider_assistant_message_result(
                    message,
                    target_api=target_api,
                    target_provider=getattr(model, "provider_id", None),
                    target_endpoint=getattr(model, "endpoint_id", None),
                    target_model=getattr(model, "id", None),
                    path=transformed_paths[index],
                )
                coerced.append(coercion_result.message)
                diagnostics.extend(coercion_result.diagnostics)
            transformed = coerced

    # Tool arguments are validated before execution. Provider-context projection
    # must keep historical malformed calls recoverable when they already have
    # matching error tool results in the transcript.
    return MessageNormalizationResult(
        messages=transformed,
        diagnostics=sort_normalization_diagnostics(diagnostics),
    )


def canonicalize_message(message: object) -> object:
    if isinstance(message, UserMessage):
        if message.role != "user":
            raise AIRequestValidationError(
                f"Unsupported message role: {message.role!r}"
            )
        return message
    if isinstance(message, AssistantMessage):
        if message.role != "assistant":
            raise AIRequestValidationError(
                f"Unsupported message role: {message.role!r}"
            )
        return AssistantMessage(
            role="assistant",
            content=[_assistant_content_part(part) for part in message.content],
            api=message.api,
            provider=message.provider,
            endpoint=message.endpoint,
            model=message.model,
            response_id=message.response_id,
            usage=_usage_from_dict(message.usage),
            stop_reason=message.stop_reason,
            error_message=message.error_message,
            timestamp=message.timestamp,
            response_model=message.response_model,
        )
    if isinstance(message, ToolResultMessage):
        if message.role != "toolResult":
            raise AIRequestValidationError(
                f"Unsupported message role: {message.role!r}"
            )
        if not isinstance(message.is_error, bool):
            raise AIRequestValidationError("Tool result is_error must be a boolean")
        return ToolResultMessage(
            role="toolResult",
            tool_call_id=message.tool_call_id,
            tool_name=message.tool_name,
            content=canonicalize_user_content(message.content),
            is_error=message.is_error,
            timestamp=message.timestamp,
            details=message.details,
        )
    if not isinstance(message, Mapping):
        return message
    message = dict(message)
    role = message.get("role")
    if role == "user":
        return _user_message_from_dict(message)
    if role == "assistant":
        return _assistant_message_from_dict(message)
    if role == "toolResult":
        return _tool_result_message_from_dict(message)
    raise TypeError(f"Unsupported message role: {role!r}")


def canonicalize_user_message(message: object) -> object:
    if isinstance(message, UserMessage):
        return UserMessage(
            role=message.role,
            content=cast(
                list[TextPart | ImagePart],
                canonicalize_user_content(message.content),
            ),
            timestamp=message.timestamp,
        )

    if isinstance(message, Mapping):
        return canonicalize_message(message)

    return message


def _user_message_from_dict(message: dict[str, Any]) -> UserMessage:
    return UserMessage(
        role="user",
        content=cast(
            list[TextPart | ImagePart],
            canonicalize_user_content(message.get("content")),
        ),
        timestamp=_float_or_default(message.get("timestamp")),
    )


def _assistant_message_from_dict(message: dict[str, Any]) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[
            _assistant_content_part(part)
            for part in _content_parts(message.get("content"))
        ],
        api=str(message.get("api", "")),
        provider=str(message.get("provider", "")),
        endpoint=str(message.get("endpoint", "")),
        model=str(message.get("model", "")),
        response_id=_optional_str(
            message.get("response_id", message.get("responseId"))
        ),
        usage=_usage_from_dict(message.get("usage")),
        stop_reason=message.get("stop_reason", message.get("stopReason", "stop")),  # type: ignore[arg-type]
        error_message=_optional_str(
            message.get("error_message", message.get("errorMessage"))
        ),
        timestamp=_float_or_default(message.get("timestamp")),
        response_model=_optional_str(
            message.get("response_model", message.get("responseModel"))
        ),
    )


def _tool_result_message_from_dict(message: dict[str, Any]) -> ToolResultMessage:
    content = canonicalize_user_content(message.get("content") or [])
    return ToolResultMessage(
        role="toolResult",
        tool_call_id=str(message.get("tool_call_id", message.get("toolCallId", ""))),
        tool_name=str(message.get("tool_name", message.get("toolName", ""))),
        content=content,  # type: ignore[arg-type]
        is_error=_strict_aliased_bool(message, "is_error", "isError"),
        timestamp=_float_or_default(message.get("timestamp")),
        details=message.get("details"),
        terminate=message.get("terminate", False) is True,
    )


def _assistant_content_part_from_dict(
    part: dict[str, Any],
) -> TextPart | ThinkingPart | ToolCall | ImagePart:
    part_type = part.get("type")
    if part_type in {"text", "image"}:
        return _part_from_dict(part)
    if part_type == "thinking":
        return ThinkingPart(
            type="thinking",
            thinking=str(part.get("thinking", "")),
            thinking_signature=_optional_str(
                part.get("thinking_signature", part.get("thinkingSignature"))
            ),
            redacted=_strict_bool_field(part, "redacted"),
        )
    if part_type == "toolCall":
        arguments = _tool_arguments(part.get("arguments"))
        return ToolCall(
            type="toolCall",
            id=str(part.get("id", "")),
            name=str(part.get("name", "")),
            arguments=arguments,
            thought_signature=_optional_str(
                part.get("thought_signature", part.get("thoughtSignature"))
            ),
        )
    raise TypeError(f"Unsupported assistant content part type: {part_type!r}")


def _content_parts(content: object) -> list[Any]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, Mapping):
        return [dict(content)]
    if not isinstance(content, list):
        raise TypeError(f"Unsupported message content type: {type(content)!r}")
    return list(content)


def _assistant_content_part(
    part: dict[str, Any] | TextPart | ThinkingPart | ToolCall | ImagePart,
) -> TextPart | ThinkingPart | ToolCall | ImagePart:
    if isinstance(part, Mapping):
        return _assistant_content_part_from_dict(dict(part))
    if isinstance(part, ThinkingPart):
        if not isinstance(part.redacted, bool):
            raise AIRequestValidationError("Thinking part redacted must be a boolean")
        return part
    if isinstance(part, ToolCall):
        return ToolCall(
            type="toolCall",
            id=part.id,
            name=part.name,
            arguments=_tool_arguments(part.arguments),
            thought_signature=part.thought_signature,
        )
    if isinstance(part, (TextPart, ImagePart)):
        return part
    raise TypeError(f"Unsupported assistant content part type: {type(part)!r}")


def _usage_from_dict(value: object) -> Usage:
    if isinstance(value, Usage):
        _validate_usage(value)
        return value
    if not isinstance(value, Mapping):
        value = {}
    else:
        value = dict(value)
    cost_raw = value.get("cost")
    cost = _canonical_cost(cost_raw if isinstance(cost_raw, dict) else None)
    return Usage(
        input=_token_count_or_default(value.get("input"), "input"),
        output=_token_count_or_default(value.get("output"), "output"),
        cache_read=_token_count_or_default(
            value.get("cache_read", value.get("cacheRead")),
            "cacheRead",
        ),
        cache_write=_token_count_or_default(
            value.get("cache_write", value.get("cacheWrite")),
            "cacheWrite",
        ),
        total_tokens=_token_count_or_default(
            value.get("total_tokens", value.get("totalTokens")),
            "totalTokens",
        ),
        cost=cost,
    )


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


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _token_count_or_default(value: object, field_name: str, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise AIRequestValidationError(
            f"Usage {field_name} must be a non-negative integer"
        )
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float) and isfinite(value) and value.is_integer():
        parsed = int(value)
    elif isinstance(value, str) and value.strip().isdecimal():
        parsed = int(value.strip())
    else:
        raise AIRequestValidationError(
            f"Usage {field_name} must be a non-negative integer"
        )
    if parsed < 0:
        raise AIRequestValidationError(
            f"Usage {field_name} must be a non-negative integer"
        )
    return parsed


def _validate_usage(usage: Usage) -> None:
    for field_name, value in (
        ("input", usage.input),
        ("output", usage.output),
        ("cacheRead", usage.cache_read),
        ("cacheWrite", usage.cache_write),
        ("totalTokens", usage.total_tokens),
    ):
        _token_count_or_default(value, field_name)


def _strict_aliased_bool(
    value: Mapping[str, object],
    key: str,
    alias: str,
    *,
    default: bool = False,
) -> bool:
    if key in value:
        raw = value[key]
    elif alias in value:
        raw = value[alias]
    else:
        return default
    if not isinstance(raw, bool):
        raise AIRequestValidationError(f"{alias} must be a boolean")
    return raw


def _strict_bool_field(
    value: Mapping[str, object],
    key: str,
    *,
    default: bool = False,
) -> bool:
    if key not in value:
        return default
    raw = value[key]
    if not isinstance(raw, bool):
        raise AIRequestValidationError(f"{key} must be a boolean")
    return raw


def _tool_arguments(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AIRequestValidationError("Tool call arguments must be a mapping")
    return dict(value)


def _float_or_default(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def canonicalize_user_content(
    content: object,
) -> list[TextPart | ImagePart]:
    if isinstance(content, str):
        return cast(
            list[TextPart | ImagePart],
            [TextPart(type="text", text=content)],
        )

    if isinstance(content, Mapping):
        return [_part_from_dict(dict(content))]

    if not isinstance(content, list):
        raise TypeError(f"Unsupported user content type: {type(content)!r}")

    normalized_parts: list[TextPart | ImagePart] = []
    for part in content:
        if isinstance(part, Mapping):
            normalized_parts.append(_part_from_dict(dict(part)))
            continue
        if isinstance(part, (TextPart, ImagePart)):
            normalized_parts.append(part)
            continue
        raise TypeError(f"Unsupported user content part object: {type(part)!r}")
    return normalized_parts


def _part_from_dict(part: dict[str, Any]) -> TextPart | ImagePart:
    part_type = part.get("type")
    if part_type == "text":
        return TextPart(
            type="text",
            text=str(part.get("text", "")),
            text_signature=part.get("text_signature") or part.get("textSignature"),
        )
    if part_type == "image":
        mime_type = part.get("mime_type") or part.get("mimeType")
        return ImagePart(
            type="image",
            data=str(part.get("data", "")),
            mime_type=str(mime_type or ""),
        )
    raise TypeError(f"Unsupported user content part type: {part_type!r}")
