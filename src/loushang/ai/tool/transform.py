from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from loushang.ai.diagnostics import (
    NormalizationDiagnostic,
    NormalizationDiagnosticCode,
)
from loushang.ai.model import Model
from loushang.ai.model.registry import resolve_model_api
from loushang.ai.options import PairingMode
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
)

_ANTHROPIC_TOOL_CALL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MISSING_TOOL_RESULT_TEXT = "No result provided"
TOOL_RESULTS_PROCESSED_ASSISTANT_TEXT = "I have processed the tool results."
SYNTHETIC_TOOL_RESULT_REASON = "missing_tool_result"


class MessagePairingError(ValueError):
    def __init__(self, diagnostic: NormalizationDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic
        self.diagnostics = (diagnostic,)


@dataclass(frozen=True)
class MessageTransformResult:
    messages: list[object]
    diagnostics: tuple[NormalizationDiagnostic, ...] = ()
    message_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssistantMessageCoercionResult:
    message: AssistantMessage
    diagnostics: tuple[NormalizationDiagnostic, ...] = ()


def transform_messages(
    messages: list[object],
    *,
    normalize_tool_call_id: Callable[[str, AssistantMessage], str] | None = None,
    pairing_mode: PairingMode = "strict",
) -> list[object]:
    return transform_messages_result(
        messages,
        normalize_tool_call_id=normalize_tool_call_id,
        pairing_mode=pairing_mode,
    ).messages


def transform_messages_result(
    messages: list[object],
    *,
    normalize_tool_call_id: Callable[[str, AssistantMessage], str] | None = None,
    pairing_mode: PairingMode = "strict",
    message_paths: list[str] | None = None,
) -> MessageTransformResult:
    transformed: list[object] = []
    transformed_paths: list[str] = []
    diagnostics: list[NormalizationDiagnostic] = []
    pending_tool_calls: list[ToolCall] = []
    pending_tool_call_map: dict[str, ToolCall] = {}
    pending_tool_call_paths: dict[int, str] = {}
    existing_tool_result_ids: set[str] = set()
    closed_tool_call_ids: set[str] = set()
    tool_call_id_map: dict[str, str] = {}
    paths = message_paths or [f"messages[{index}]" for index in range(len(messages))]
    if len(paths) != len(messages):
        raise ValueError("message_paths must match messages length")

    for message_index, message in enumerate(messages):
        message_path = paths[message_index]
        if isinstance(message, AssistantMessage):
            if pending_tool_calls:
                missing_tool_calls = _missing_tool_calls(
                    pending_tool_calls,
                    existing_tool_result_ids,
                )
                if missing_tool_calls and pairing_mode == "strict":
                    _raise_pairing_error(
                        "missing_tool_result",
                        _first_tool_call_path(
                            missing_tool_calls,
                            pending_tool_call_paths,
                            fallback=message_path,
                        ),
                        "Missing tool results before next message",
                    )
                if missing_tool_calls:
                    _append_synthetic_tool_results(
                        transformed,
                        transformed_paths,
                        diagnostics,
                        pending_tool_calls,
                        existing_tool_result_ids,
                        pending_tool_call_paths,
                    )
                closed_tool_call_ids.update(
                    tool_call.id for tool_call in pending_tool_calls
                )
                pending_tool_calls = []
                pending_tool_call_map = {}
                pending_tool_call_paths = {}
                existing_tool_result_ids = set()

            normalized_message = message
            normalized_content: list[object] = []
            current_tool_calls: list[ToolCall] = []
            current_tool_call_paths: dict[int, str] = {}
            changed = False

            if normalized_message.stop_reason == "aborted":
                _record_tool_call_id_mappings(
                    normalized_message,
                    normalize_tool_call_id=normalize_tool_call_id,
                    tool_call_id_map=tool_call_id_map,
                    closed_tool_call_ids=closed_tool_call_ids,
                )
                transformed.append(_aborted_boundary_message(normalized_message))
                transformed_paths.append(message_path)
                diagnostics.append(
                    NormalizationDiagnostic(
                        code="aborted_assistant_repaired",
                        path=message_path,
                        message=(
                            "Repaired aborted assistant message as a text turn "
                            "boundary."
                        ),
                    )
                )
                continue
            if normalized_message.stop_reason == "error":
                _record_tool_call_id_mappings(
                    normalized_message,
                    normalize_tool_call_id=normalize_tool_call_id,
                    tool_call_id_map=tool_call_id_map,
                    closed_tool_call_ids=closed_tool_call_ids,
                )
                diagnostics.append(
                    NormalizationDiagnostic(
                        code="error_assistant_dropped",
                        path=message_path,
                        message="Dropped error assistant message during normalization.",
                    )
                )
                continue

            tool_call_id_resolutions = _resolve_tool_call_ids(
                message,
                normalize_tool_call_id=normalize_tool_call_id,
            )
            for block_index, block in enumerate(message.content):
                if isinstance(block, ToolCall):
                    path = f"{message_path}.content[{block_index}]"
                    next_id = tool_call_id_resolutions[id(block)]
                    if next_id != block.id:
                        tool_call_id_map[block.id] = next_id
                        diagnostics.append(
                            NormalizationDiagnostic(
                                code="tool_call_id_normalized",
                                path=path,
                                message=(
                                    f"Normalized tool call id {block.id!r} "
                                    f"to {next_id!r}."
                                ),
                            )
                        )
                        if block.thought_signature is not None:
                            diagnostics.append(
                                NormalizationDiagnostic(
                                    code="tool_call_thought_signature_removed",
                                    path=path,
                                    message=(
                                        "Removed provider-specific tool call "
                                        "thought signature."
                                    ),
                                )
                            )
                        block = ToolCall(
                            type=block.type,
                            id=next_id,
                            name=block.name,
                            arguments=block.arguments,
                        )
                        changed = True
                    current_tool_calls.append(block)
                    current_tool_call_paths[id(block)] = path
                    closed_tool_call_ids.discard(block.id)
                normalized_content.append(block)

            if changed:
                normalized_message = AssistantMessage(
                    role=message.role,
                    content=normalized_content,  # type: ignore[arg-type]
                    api=message.api,
                    provider=message.provider,
                    endpoint=message.endpoint,
                    model=message.model,
                    response_id=message.response_id,
                    usage=message.usage,
                    stop_reason=message.stop_reason,
                    error_message=message.error_message,
                    timestamp=message.timestamp,
                    response_model=message.response_model,
                )

            transformed.append(normalized_message)
            transformed_paths.append(message_path)
            pending_tool_calls = current_tool_calls
            pending_tool_call_map = {
                tool_call.id: tool_call for tool_call in current_tool_calls
            }
            pending_tool_call_paths = current_tool_call_paths
            existing_tool_result_ids = set()
            continue

        if isinstance(message, ToolResultMessage):
            next_id = tool_call_id_map.get(message.tool_call_id, message.tool_call_id)
            if next_id != message.tool_call_id:
                diagnostics.append(
                    NormalizationDiagnostic(
                        code="tool_result_id_normalized",
                        path=message_path,
                        message=(
                            f"Normalized tool result id {message.tool_call_id!r} "
                            f"to {next_id!r}."
                        ),
                    )
                )
                message = ToolResultMessage(
                    role=message.role,
                    tool_call_id=next_id,
                    tool_name=message.tool_name,
                    content=message.content,
                    is_error=message.is_error,
                    timestamp=message.timestamp,
                    details=message.details,
                    terminate=message.terminate,
                )
            if message.tool_call_id in closed_tool_call_ids:
                _raise_pairing_error(
                    "late_tool_result",
                    message_path,
                    f"Late tool result for closed tool call: {message.tool_call_id!r}",
                )
            matched_tool_call = pending_tool_call_map.get(message.tool_call_id)
            if (
                pairing_mode == "strict"
                and not pending_tool_calls
                and matched_tool_call is None
            ):
                _raise_pairing_error(
                    "orphaned_tool_result",
                    message_path,
                    f"Orphaned tool result without pending tool call: {message.tool_call_id!r}",
                )
            if pending_tool_calls and matched_tool_call is None:
                _raise_pairing_error(
                    "unknown_tool_result",
                    message_path,
                    f"Unknown tool result for pending tool calls: {message.tool_call_id!r}",
                )
            if (
                matched_tool_call is not None
                and matched_tool_call.name != message.tool_name
            ):
                _raise_pairing_error(
                    "tool_result_name_mismatch",
                    message_path,
                    f"Tool result name mismatch for {message.tool_call_id!r}: "
                    f"expected {matched_tool_call.name!r}, got {message.tool_name!r}",
                )
            if (
                matched_tool_call is not None
                and message.tool_call_id in existing_tool_result_ids
            ):
                _raise_pairing_error(
                    "duplicate_tool_result",
                    message_path,
                    f"Duplicate tool result for {message.tool_call_id!r}",
                )
            existing_tool_result_ids.add(message.tool_call_id)
            transformed.append(message)
            transformed_paths.append(message_path)
            continue

        if pending_tool_calls:
            missing_tool_calls = _missing_tool_calls(
                pending_tool_calls,
                existing_tool_result_ids,
            )
            if missing_tool_calls and pairing_mode == "strict":
                _raise_pairing_error(
                    "missing_tool_result",
                    _first_tool_call_path(
                        missing_tool_calls,
                        pending_tool_call_paths,
                        fallback=message_path,
                    ),
                    "Missing tool results before next message",
                )
            if missing_tool_calls:
                _append_synthetic_tool_results(
                    transformed,
                    transformed_paths,
                    diagnostics,
                    pending_tool_calls,
                    existing_tool_result_ids,
                    pending_tool_call_paths,
                )
            closed_tool_call_ids.update(
                tool_call.id for tool_call in pending_tool_calls
            )
            pending_tool_calls = []
            pending_tool_call_map = {}
            pending_tool_call_paths = {}
            existing_tool_result_ids = set()

        transformed.append(message)
        transformed_paths.append(message_path)

    if pending_tool_calls:
        missing_tool_calls = _missing_tool_calls(
            pending_tool_calls,
            existing_tool_result_ids,
        )
        if missing_tool_calls and pairing_mode == "strict":
            _raise_pairing_error(
                "missing_tool_result",
                _first_tool_call_path(
                    missing_tool_calls,
                    pending_tool_call_paths,
                    fallback=paths[-1] if paths else "messages",
                ),
                "Missing tool results before next message",
            )
        if missing_tool_calls:
            _append_synthetic_tool_results(
                transformed,
                transformed_paths,
                diagnostics,
                pending_tool_calls,
                existing_tool_result_ids,
                pending_tool_call_paths,
            )
        closed_tool_call_ids.update(tool_call.id for tool_call in pending_tool_calls)

    return MessageTransformResult(
        messages=transformed,
        diagnostics=tuple(diagnostics),
        message_paths=tuple(transformed_paths),
    )


def _raise_pairing_error(
    code: NormalizationDiagnosticCode,
    path: str,
    message: str,
) -> None:
    raise MessagePairingError(
        NormalizationDiagnostic(code=code, path=path, message=message)
    )


def _first_tool_call_path(
    tool_calls: list[ToolCall],
    paths: Mapping[int, str],
    *,
    fallback: str,
) -> str:
    if not tool_calls:
        return fallback
    return paths.get(id(tool_calls[0]), fallback)


def _aborted_boundary_message(message: AssistantMessage) -> AssistantMessage:
    text = (
        _assistant_text(message) or message.error_message or "Request aborted by user"
    )
    return AssistantMessage(
        role=message.role,
        content=[TextPart(type="text", text=text)],
        api=message.api,
        provider=message.provider,
        endpoint=message.endpoint,
        model=message.model,
        response_id=message.response_id,
        usage=message.usage,
        stop_reason="stop",
        error_message=None,
        timestamp=message.timestamp,
        response_model=message.response_model,
    )


def _assistant_text(message: AssistantMessage) -> str:
    parts = [
        block.text.strip()
        for block in message.content
        if isinstance(block, TextPart) and block.text.strip()
    ]
    return "\n".join(parts)


def coerce_cross_provider_assistant_message(
    message: AssistantMessage,
    *,
    target_api: str,
    target_provider: str | None = None,
    target_endpoint: str | None = None,
    target_model: str | None = None,
) -> AssistantMessage:
    return coerce_cross_provider_assistant_message_result(
        message,
        target_api=target_api,
        target_provider=target_provider,
        target_endpoint=target_endpoint,
        target_model=target_model,
    ).message


def coerce_cross_provider_assistant_message_result(
    message: AssistantMessage,
    *,
    target_api: str,
    target_provider: str | None = None,
    target_endpoint: str | None = None,
    target_model: str | None = None,
    path: str = "messages",
) -> AssistantMessageCoercionResult:
    same_target = (
        message.api == target_api
        and message.provider == target_provider
        and message.endpoint == target_endpoint
        and message.model == target_model
    )
    if same_target:
        return AssistantMessageCoercionResult(message=message)
    coerced_content: list[object] = []
    diagnostics: list[NormalizationDiagnostic] = []
    changed = False
    for block_index, block in enumerate(message.content):
        block_path = f"{path}.content[{block_index}]"
        if isinstance(block, ThinkingPart):
            changed = True
            if block.thinking_signature is not None:
                diagnostics.append(
                    NormalizationDiagnostic(
                        code="thinking_signature_removed",
                        path=block_path,
                        message="Removed provider-specific thinking signature.",
                    )
                )
            if block.redacted:
                diagnostics.append(
                    NormalizationDiagnostic(
                        code="redacted_thinking_dropped",
                        path=block_path,
                        message=(
                            "Dropped redacted thinking block while coercing "
                            "assistant message."
                        ),
                    )
                )
                continue
            if not block.thinking.strip():
                diagnostics.append(
                    NormalizationDiagnostic(
                        code="empty_thinking_dropped",
                        path=block_path,
                        message=(
                            "Dropped empty thinking block while coercing "
                            "assistant message."
                        ),
                    )
                )
                continue
            diagnostics.append(
                NormalizationDiagnostic(
                    code="thinking_downgraded_to_text",
                    path=block_path,
                    message="Downgraded provider-specific thinking to text.",
                )
            )
            coerced_content.append(TextPart(type="text", text=block.thinking))
            continue
        if isinstance(block, TextPart):
            if block.text_signature is not None:
                changed = True
                diagnostics.append(
                    NormalizationDiagnostic(
                        code="text_signature_removed",
                        path=block_path,
                        message="Removed provider-specific text signature.",
                    )
                )
            coerced_content.append(TextPart(type="text", text=block.text))
            continue
        if isinstance(block, ToolCall):
            if block.thought_signature is not None:
                changed = True
                diagnostics.append(
                    NormalizationDiagnostic(
                        code="tool_call_thought_signature_removed",
                        path=block_path,
                        message="Removed provider-specific tool call thought signature.",
                    )
                )
            coerced_content.append(
                ToolCall(
                    type=block.type,
                    id=block.id,
                    name=block.name,
                    arguments=block.arguments,
                )
            )
            continue
        coerced_content.append(block)
    if not changed:
        return AssistantMessageCoercionResult(message=message)
    return AssistantMessageCoercionResult(
        message=AssistantMessage(
            role=message.role,
            content=coerced_content,  # type: ignore[arg-type]
            api=message.api,
            provider=message.provider,
            endpoint=message.endpoint,
            model=message.model,
            response_id=message.response_id,
            usage=message.usage,
            stop_reason=message.stop_reason,
            error_message=message.error_message,
            timestamp=message.timestamp,
            response_model=message.response_model,
        ),
        diagnostics=tuple(diagnostics),
    )


def insert_assistant_bridge_after_tool_results(
    payload_messages: list[dict],
    *,
    assistant_content: str = TOOL_RESULTS_PROCESSED_ASSISTANT_TEXT,
) -> list[dict]:
    transformed: list[dict] = []
    previous_was_tool_result = False

    for message in payload_messages:
        if previous_was_tool_result and message.get("role") == "user":
            transformed.append({"role": "assistant", "content": assistant_content})
        transformed.append(message)
        previous_was_tool_result = (
            message.get("role") == "tool"
            or message.get("type") == "function_call_output"
        )

    return transformed


def group_consecutive_tool_results_as_user_messages(
    messages: list[object],
    *,
    build_tool_result_block: Callable[[ToolResultMessage], dict],
) -> list[object]:
    grouped: list[object] = []
    index = 0

    while index < len(messages):
        message = messages[index]
        if isinstance(message, ToolResultMessage):
            content_blocks: list[dict] = []
            while index < len(messages) and isinstance(
                messages[index], ToolResultMessage
            ):
                tool_result = cast(ToolResultMessage, messages[index])
                content_blocks.append(build_tool_result_block(tool_result))
                index += 1
            grouped.append({"role": "user", "content": content_blocks})
            continue

        grouped.append(message)
        index += 1

    return grouped


def merge_adjacent_user_payload_messages(
    messages: list[dict],
    *,
    normalize_user_content: Callable[[object], list[dict]],
) -> list[dict]:
    merged: list[dict] = []

    for message in messages:
        if (
            merged
            and merged[-1].get("role") == "user"
            and message.get("role") == "user"
        ):
            merged[-1]["content"] = normalize_user_content(
                merged[-1]["content"]
            ) + normalize_user_content(message["content"])
            continue
        merged.append(message)

    return merged


def normalize_tool_call_id_for_model(tool_call_id: str, model: Model) -> str:
    if resolve_model_api(model) != "anthropic-messages":
        return tool_call_id
    if _ANTHROPIC_TOOL_CALL_ID_PATTERN.fullmatch(tool_call_id):
        return tool_call_id

    sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", tool_call_id).strip("_")
    if (
        sanitized
        and len(sanitized) <= 64
        and _ANTHROPIC_TOOL_CALL_ID_PATTERN.fullmatch(sanitized)
    ):
        return sanitized

    digest = hashlib.sha256(tool_call_id.encode("utf-8")).hexdigest()[:16]
    prefix = sanitized[:40] if sanitized else "tool_call"
    prefix = re.sub(r"[^A-Za-z0-9_-]", "_", prefix).strip("_") or "tool_call"
    normalized = f"{prefix}_{digest}"[:64]
    return normalized.rstrip("_")


def _record_tool_call_id_mappings(
    message: AssistantMessage,
    *,
    normalize_tool_call_id: Callable[[str, AssistantMessage], str] | None,
    tool_call_id_map: dict[str, str],
    closed_tool_call_ids: set[str],
) -> None:
    tool_call_id_resolutions = _resolve_tool_call_ids(
        message,
        normalize_tool_call_id=normalize_tool_call_id,
    )
    for block in message.content:
        if not isinstance(block, ToolCall):
            continue
        next_id = tool_call_id_resolutions[id(block)]
        if next_id != block.id:
            tool_call_id_map[block.id] = next_id
        closed_tool_call_ids.discard(next_id)


def _resolve_tool_call_ids(
    message: AssistantMessage,
    *,
    normalize_tool_call_id: Callable[[str, AssistantMessage], str] | None,
) -> dict[int, str]:
    tool_calls = [block for block in message.content if isinstance(block, ToolCall)]
    base_ids = {
        id(tool_call): (
            normalize_tool_call_id(tool_call.id, message)
            if normalize_tool_call_id is not None
            else tool_call.id
        )
        for tool_call in tool_calls
    }
    reserved_ids = {
        base_ids[id(tool_call)]
        for tool_call in tool_calls
        if base_ids[id(tool_call)] == tool_call.id
    }
    used_ids: set[str] = set()
    resolved: dict[int, str] = {}

    for tool_call in tool_calls:
        base_id = base_ids[id(tool_call)]
        blocked_ids = set(used_ids)
        if base_id != tool_call.id:
            blocked_ids.update(reserved_ids)
        resolved_id = _unique_tool_call_id(
            base_id,
            original_id=tool_call.id,
            blocked_ids=blocked_ids,
        )
        resolved[id(tool_call)] = resolved_id
        used_ids.add(resolved_id)

    return resolved


def _unique_tool_call_id(
    base_id: str,
    *,
    original_id: str,
    blocked_ids: set[str],
) -> str:
    if base_id not in blocked_ids:
        return base_id

    prefix = re.sub(r"[^A-Za-z0-9_-]", "_", base_id).strip("_") or "tool_call"
    for attempt in range(1, 1000):
        digest = hashlib.sha256(
            f"{original_id}:{base_id}:{attempt}".encode("utf-8")
        ).hexdigest()[:8]
        suffix = f"_{digest}"
        candidate = f"{prefix[: 64 - len(suffix)].rstrip('_-')}{suffix}"
        if candidate not in blocked_ids:
            return candidate
    raise ValueError(f"Unable to assign unique tool call id for {original_id!r}")


def _append_synthetic_tool_results(
    transformed: list[object],
    transformed_paths: list[str],
    diagnostics: list[NormalizationDiagnostic],
    tool_calls: list[ToolCall],
    existing_tool_result_ids: set[str],
    tool_call_paths: Mapping[int, str],
) -> None:
    for tool_call in tool_calls:
        if tool_call.id in existing_tool_result_ids:
            continue
        result = ToolResultMessage(
            role="toolResult",
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            content=[TextPart(type="text", text=MISSING_TOOL_RESULT_TEXT)],
            is_error=True,
            timestamp=0.0,
            details={
                "synthetic": True,
                "reason": SYNTHETIC_TOOL_RESULT_REASON,
            },
        )
        path = tool_call_paths.get(id(tool_call), "messages")
        transformed.append(result)
        transformed_paths.append(path)
        diagnostics.append(
            NormalizationDiagnostic(
                code="missing_tool_result_repaired",
                path=path,
                message=(
                    f"Inserted synthetic error result for missing tool call "
                    f"{result.tool_call_id!r}."
                ),
            )
        )


def _missing_tool_calls(
    tool_calls: list[ToolCall],
    existing_tool_result_ids: set[str],
) -> list[ToolCall]:
    return [
        tool_call
        for tool_call in tool_calls
        if tool_call.id not in existing_tool_result_ids
    ]
