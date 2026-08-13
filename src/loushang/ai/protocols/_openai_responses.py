from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any, TypedDict, cast

from loushang.ai.context import NormalizedContext
from loushang.ai.errors import AIProviderProtocolError
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.model.domain import OpenAIResponsesConfig
from loushang.ai.model.registry import resolve_model_api
from loushang.ai.provider.errors import (
    provider_error_part,
    provider_error_part_from_raw,
)
from loushang.ai.tool.providers import to_openai_responses_tools
from loushang.ai.tool.transform import (
    MISSING_TOOL_RESULT_TEXT,
)
from loushang.ai.types import AssistantMessage, TextPart, Tool, ToolResultMessage
from loushang.ai.utils import sanitize_surrogates, short_hash


class _BufferedTextPart(TypedDict):
    text: str
    text_signature: str | dict[str, Any] | None


def convert_responses_messages(
    model,
    normalized: NormalizedContext,
    adapter_config: OpenAIResponsesConfig | None = None,
    capabilities: object | None = None,
) -> list[dict[str, Any]]:
    """
    Minimal shared message conversion for the OpenAI Responses provider.

    This is intentionally the current behavior extracted from the provider so the
    next steps can iterate toward pi-ai's shared architecture without keeping the
    logic in the orchestration file.
    """
    adapter_config = adapter_config or OpenAIResponsesConfig()
    input_items: list[dict[str, Any]] = []
    tool_call_id_map: dict[str, str] = {}
    system_prompt = normalized.system_prompt
    if isinstance(system_prompt, str) and system_prompt.strip():
        role = (
            "developer"
            if _supports_developer_role(model, adapter_config, capabilities)
            else "system"
        )
        input_items.append(
            {"role": role, "content": sanitize_surrogates(system_prompt)}
        )

    messages = normalized.messages
    index = 0
    while index < len(messages):
        msg = messages[index]
        message_role = _message_role(msg)
        content = _message_content(msg)
        if message_role == "user":
            user_payload = _user_message_payload(content, model, capabilities)
            if user_payload is not None:
                input_items.append(user_payload)
            index += 1
            continue
        if message_role == "assistant":
            assistant_payload, tool_call_ids = _assistant_message_payload(
                msg, model, tool_call_id_map
            )
            if assistant_payload:
                input_items.extend(assistant_payload)
            next_is_tool_result = (
                index + 1 < len(messages)
                and _message_role(messages[index + 1]) == "toolResult"
            )
            if tool_call_ids and not next_is_tool_result:
                for tool_call_id in tool_call_ids:
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": tool_call_id.split("|", 1)[0],
                            "output": MISSING_TOOL_RESULT_TEXT,
                        }
                    )
            index += 1
            continue
        if message_role == "toolResult":
            tool_result_payload = _tool_result_payload(
                msg,
                model,
                tool_call_id_map,
                capabilities,
            )
            if tool_result_payload is not None:
                input_items.append(tool_result_payload)
            index += 1
            continue
        index += 1

    return input_items


def convert_responses_tools(
    tools: Sequence[Tool] | None,
) -> list[dict[str, Any]] | None:
    if not isinstance(tools, Sequence) or isinstance(tools, str) or not tools:
        return None
    return to_openai_responses_tools(list(tools))


async def process_responses_stream(
    openai_stream,
    *,
    reasoning_enabled: bool = False,
    source: str = "openai-responses",
) -> AsyncIterator[RawPart]:
    thinking_buf: list[str] = []
    text_buf: list[str] = []
    thinking_closed = False
    text_closed = False
    current_reasoning_item: dict[str, Any] | None = None
    tool_call_ids_by_item_id: dict[str, str] = {}
    tool_call_ids_by_index: dict[int, str] = {}
    emitted_response_start = False
    emit_thinking = reasoning_enabled

    async for event in openai_stream:
        etype = getattr(event, "type", None)
        if etype == "response.created":
            resp = getattr(event, "response", None)
            rid = getattr(resp, "id", None)
            if isinstance(rid, str):
                emitted_response_start = True
                yield {"type": "response_start", "response_id": rid}
        elif etype == "response.output_item.added":
            item = getattr(event, "item", None)
            if item is None:
                continue
            if getattr(item, "type", None) == "reasoning":
                current_reasoning_item = {
                    "type": "reasoning",
                    "id": getattr(item, "id", None),
                    "summary": [],
                }
            elif getattr(item, "type", None) == "function_call":
                index = _optional_int(getattr(event, "output_index", None))
                item_id = getattr(item, "id", None)
                call_id = getattr(item, "call_id", None)
                tool_call_id = f"{call_id or ''}|{item_id or ''}"
                if isinstance(item_id, str) and item_id:
                    tool_call_ids_by_item_id[item_id] = tool_call_id
                if index is not None:
                    tool_call_ids_by_index[index] = tool_call_id
                start_part: dict[str, object] = {
                    "type": "tool_call_start",
                    "id": tool_call_id,
                    "name": getattr(item, "name", ""),
                }
                if index is not None:
                    start_part["index"] = index
                yield _raw_part(start_part)
        elif etype == "response.reasoning_summary_part.added":
            if current_reasoning_item is not None:
                part = getattr(event, "part", None)
                if part is not None:
                    current_reasoning_item["summary"].append(
                        {
                            "type": getattr(part, "type", "summary_text"),
                            "text": getattr(part, "text", ""),
                        }
                    )
        elif etype == "response.reasoning_summary_text.delta":
            delta = getattr(event, "delta", None)
            if isinstance(delta, str) and delta:
                if current_reasoning_item is not None:
                    if not current_reasoning_item["summary"]:
                        current_reasoning_item["summary"].append(
                            {"type": "summary_text", "text": ""}
                        )
                    current_reasoning_item["summary"][-1]["text"] += delta
                if emit_thinking:
                    thinking_buf.append(delta)
                    yield {"type": "thinking_delta", "text": delta}
        elif etype == "response.reasoning_summary_part.done":
            if current_reasoning_item is not None and current_reasoning_item.get(
                "summary"
            ):
                current_reasoning_item["summary"][-1]["text"] += "\n\n"
                if emit_thinking:
                    thinking_buf.append("\n\n")
                    yield {"type": "thinking_delta", "text": "\n\n"}
        elif etype == "response.output_text.delta":
            delta = getattr(event, "delta", None)
            if isinstance(delta, str) and delta:
                text_buf.append(delta)
                yield {"type": "text_delta", "text": delta}
        elif etype == "response.refusal.delta":
            delta = getattr(event, "delta", None)
            if isinstance(delta, str) and delta:
                text_buf.append(delta)
                yield {"type": "text_delta", "text": delta}
        elif etype == "response.function_call_arguments.delta":
            delta = getattr(event, "delta", None)
            if isinstance(delta, str) and delta:
                delta_part: dict[str, object] = {
                    "type": "tool_call_args_delta",
                    "delta": delta,
                }
                item_id = getattr(event, "item_id", None)
                if isinstance(item_id, str) and item_id:
                    delta_part["tool_call_id"] = tool_call_ids_by_item_id.get(
                        item_id,
                        item_id,
                    )
                index = _optional_int(getattr(event, "output_index", None))
                if "tool_call_id" not in delta_part and index is not None:
                    indexed_tool_call_id = tool_call_ids_by_index.get(index)
                    if indexed_tool_call_id is not None:
                        delta_part["tool_call_id"] = indexed_tool_call_id
                if index is not None:
                    delta_part["index"] = index
                yield _raw_part(delta_part)
        elif etype == "response.output_item.done":
            item = getattr(event, "item", None)
            if item is None:
                continue
            if getattr(item, "type", None) == "reasoning":
                signature_payload = {
                    "type": "reasoning",
                    "id": getattr(item, "id", None),
                    "summary": [
                        {
                            "type": getattr(part, "type", "summary_text"),
                            "text": getattr(part, "text", ""),
                        }
                        for part in (getattr(item, "summary", None) or [])
                    ],
                }
                yield {
                    "type": "thinking_signature_delta",
                    "signature": json.dumps(signature_payload),
                }
                thinking_closed = True
                current_reasoning_item = None
            elif getattr(item, "type", None) == "message":
                yield {
                    "type": "text_signature_delta",
                    "signature": encode_text_signature_v1(
                        str(getattr(item, "id", "") or ""),
                        getattr(item, "phase", None),
                    ),
                }
                text_closed = True
            elif getattr(item, "type", None) == "function_call":
                done_part: dict[str, object] = {"type": "tool_call_done"}
                item_id = getattr(item, "id", None)
                call_id = getattr(item, "call_id", None)
                if isinstance(call_id, str) and isinstance(item_id, str):
                    done_part["tool_call_id"] = f"{call_id}|{item_id}"
                    tool_call_ids_by_item_id.pop(item_id, None)
                index = _optional_int(getattr(event, "output_index", None))
                if index is not None:
                    done_part["index"] = index
                    tool_call_ids_by_index.pop(index, None)
                yield _raw_part(done_part)
        elif etype in {
            "response.completed",
            "response.done",
            "response.failed",
            "response.incomplete",
        }:
            resp = getattr(event, "response", None)
            if resp is not None:
                rid = getattr(resp, "id", None)
                if not emitted_response_start and isinstance(rid, str) and rid:
                    emitted_response_start = True
                    yield {"type": "response_start", "response_id": rid}
                multiplier = _service_tier_cost_multiplier(
                    getattr(resp, "service_tier", None)
                )
                if multiplier != 1.0:
                    yield {"type": "usage_cost_multiplier", "multiplier": multiplier}
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    cached = (
                        getattr(
                            getattr(usage, "input_tokens_details", None) or {},
                            "cached_tokens",
                            0,
                        )
                        or 0
                    )
                    yield {
                        "type": "usage_delta",
                        "input": (getattr(usage, "input_tokens", 0) or 0) - cached,
                        "output": getattr(usage, "output_tokens", 0) or 0,
                        "cache_read": cached,
                        "cache_write": 0,
                        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                    }
                if (not thinking_closed) and thinking_buf:
                    thinking_closed = True
                if (not text_closed) and text_buf:
                    text_closed = True
                for part in _response_terminal_parts(resp, source=source):
                    yield part
                return
            yield provider_error_part_from_raw(
                "response terminal event did not include a response",
                code="provider_protocol",
                source=source,
            )
            return
        elif etype == "error":
            code = getattr(event, "code", None)
            message = getattr(event, "message", None)
            err = (
                f"Error Code {code}: {message}" if code or message else "Unknown error"
            )
            yield provider_error_part_from_raw(err, code=code, source=source)
            return

    yield provider_error_part(
        AIProviderProtocolError(
            "provider stream ended before a terminal response event",
            source=source,
        ),
        source=source,
    )


def process_responses_response(
    response: object,
    *,
    reasoning_enabled: bool = False,
    source: str = "openai-responses",
) -> Iterator[RawPart]:
    rid = getattr(response, "id", None)
    if isinstance(rid, str) and rid:
        yield {"type": "response_start", "response_id": rid}

    emit_thinking = reasoning_enabled

    output = getattr(response, "output", None)
    if isinstance(output, list):
        for index, item in enumerate(output):
            item_type = getattr(item, "type", None)
            if item_type == "reasoning":
                yield from _iter_complete_reasoning_parts(
                    item,
                    emit_thinking=emit_thinking,
                )
            elif item_type == "message":
                yield from _iter_complete_message_parts(item)
            elif item_type == "function_call":
                yield from _iter_complete_function_call_parts(item, index=index)

    multiplier = _service_tier_cost_multiplier(getattr(response, "service_tier", None))
    if multiplier != 1.0:
        yield {"type": "usage_cost_multiplier", "multiplier": multiplier}

    usage = getattr(response, "usage", None)
    if usage is not None:
        yield _responses_usage_part(usage)

    yield from _response_terminal_parts(response, source=source)


def _response_terminal_parts(
    response: object,
    *,
    source: str,
) -> Iterator[RawPart]:
    status = getattr(response, "status", None)
    if status == "incomplete":
        incomplete_details = getattr(response, "incomplete_details", None)
        reason = getattr(incomplete_details, "reason", None)
        if reason in {"max_output_tokens", "max_tokens", "length"}:
            yield {"type": "stop_reason", "stop_reason": "length"}
            yield {"type": "response_done"}
            return
        yield {"type": "stop_reason", "stop_reason": "error"}
        yield provider_error_part_from_raw(
            "response incomplete",
            code=reason,
            source=source,
        )
        return
    if status in {"failed", "cancelled"}:
        error = getattr(response, "error", None)
        code = getattr(error, "code", None) if error is not None else status
        message = (
            getattr(error, "message", None) if error is not None else "response failed"
        )
        yield {"type": "stop_reason", "stop_reason": "error"}
        yield provider_error_part_from_raw(message, code=code, source=source)
        return
    yield {
        "type": "stop_reason",
        "stop_reason": map_responses_status_to_reason(status),
    }
    yield {"type": "response_done"}


def _service_tier_cost_multiplier(service_tier: str | None) -> float:
    if service_tier == "flex":
        return 0.5
    if service_tier == "priority":
        return 2.0
    return 1.0


def _raw_part(part: dict[str, object]) -> RawPart:
    return cast(RawPart, part)


def _iter_complete_reasoning_parts(
    item: object,
    *,
    emit_thinking: bool,
) -> Iterator[RawPart]:
    summary_payload = []
    for part in getattr(item, "summary", None) or []:
        text = getattr(part, "text", "")
        summary_payload.append(
            {
                "type": getattr(part, "type", "summary_text"),
                "text": text,
            }
        )
        if emit_thinking and isinstance(text, str) and text:
            yield {"type": "thinking_delta", "text": text}
    yield {
        "type": "thinking_signature_delta",
        "signature": json.dumps(
            {
                "type": "reasoning",
                "id": getattr(item, "id", None),
                "summary": summary_payload,
            }
        ),
    }


def _iter_complete_message_parts(item: object) -> Iterator[RawPart]:
    content = getattr(item, "content", None)
    if isinstance(content, str) and content:
        yield {"type": "text_delta", "text": content}
    elif isinstance(content, list):
        for part in content:
            text = _complete_content_text(part)
            if isinstance(text, str) and text:
                yield {"type": "text_delta", "text": text}
    yield {
        "type": "text_signature_delta",
        "signature": encode_text_signature_v1(
            str(getattr(item, "id", "") or ""),
            getattr(item, "phase", None),
        ),
    }


def _iter_complete_function_call_parts(
    item: object,
    *,
    index: int,
) -> Iterator[RawPart]:
    item_id = getattr(item, "id", None)
    call_id = getattr(item, "call_id", None)
    tool_call_id = f"{call_id or ''}|{item_id or ''}"
    yield _raw_part(
        {
            "type": "tool_call_start",
            "id": tool_call_id,
            "name": getattr(item, "name", ""),
            "index": index,
        }
    )
    arguments = getattr(item, "arguments", None)
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    if isinstance(arguments, str) and arguments:
        yield _raw_part(
            {
                "type": "tool_call_args_delta",
                "tool_call_id": tool_call_id,
                "delta": arguments,
                "index": index,
            }
        )
    yield _raw_part(
        {
            "type": "tool_call_done",
            "tool_call_id": tool_call_id,
            "index": index,
        }
    )


def _complete_content_text(part: object) -> str | None:
    text = getattr(part, "text", None)
    if isinstance(text, str):
        return text
    refusal = getattr(part, "refusal", None)
    if isinstance(refusal, str):
        return refusal
    return None


def _responses_usage_part(usage: object) -> RawPart:
    cached = (
        getattr(
            getattr(usage, "input_tokens_details", None) or {},
            "cached_tokens",
            0,
        )
        or 0
    )
    return {
        "type": "usage_delta",
        "input": (getattr(usage, "input_tokens", 0) or 0) - cached,
        "output": getattr(usage, "output_tokens", 0) or 0,
        "cache_read": cached,
        "cache_write": 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
    }


def map_responses_status_to_reason(status: str | None) -> str:
    if not status:
        return "stop"
    if status == "completed":
        return "stop"
    if status == "incomplete":
        return "length"
    if status in {"failed", "cancelled"}:
        return "error"
    return "stop"


def encode_text_signature_v1(signature_id: str, phase: str | None = None) -> str:
    payload: dict[str, Any] = {"v": 1, "id": signature_id}
    if phase in {"commentary", "final_answer"}:
        payload["phase"] = phase
    return json.dumps(payload)


def parse_text_signature(
    signature: str | dict[str, Any] | None,
) -> dict[str, Any] | None:
    if isinstance(signature, dict):
        return signature if isinstance(signature.get("id"), str) else None
    if not isinstance(signature, str) or not signature:
        return None
    if signature.startswith("{"):
        try:
            parsed = json.loads(signature)
        except Exception:
            return None
        if (
            isinstance(parsed, dict)
            and parsed.get("v") == 1
            and isinstance(parsed.get("id"), str)
        ):
            return parsed
        return None
    return {"id": signature}


def _message_role(message: object) -> str | None:
    return getattr(message, "role", None)


def _message_content(message: object) -> object:
    return getattr(message, "content", None)


def _user_message_payload(
    content: object, model, capabilities: object | None = None
) -> dict[str, Any] | None:
    if not isinstance(content, list):
        return None

    parts: list[dict[str, Any]] = []
    for part in content:
        part_type = _part_type(part)
        if part_type == "text":
            text = _part_text(part)
            if isinstance(text, str) and text.strip():
                parts.append({"type": "input_text", "text": sanitize_surrogates(text)})
        elif part_type == "image" and _supports_image_input(model, capabilities):
            data = _part_data(part)
            mime_type = _part_mime_type(part)
            if (
                isinstance(data, str)
                and data
                and isinstance(mime_type, str)
                and mime_type
            ):
                parts.append(
                    {
                        "type": "input_image",
                        "detail": "auto",
                        "image_url": f"data:{mime_type};base64,{data}",
                    }
                )
    if not parts:
        return None
    return {"role": "user", "content": parts}


def _assistant_message_payload(
    message: object,
    model,
    tool_call_id_map: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(message, AssistantMessage):
        return [], []
    output: list[dict[str, Any]] = []
    tool_call_ids: list[str] = []

    text_buffer: list[_BufferedTextPart] = []

    def _flush_text() -> None:
        if not text_buffer:
            return
        text = "\n".join(
            item["text"]
            for item in text_buffer
            if isinstance(item.get("text"), str) and item["text"].strip()
        )
        signature = None
        for item in text_buffer:
            parsed = parse_text_signature(item.get("text_signature"))
            if parsed is not None:
                signature = parsed
                break
        text_buffer.clear()
        if text:
            payload: dict[str, Any] = {
                "role": "assistant",
                "content": sanitize_surrogates(text),
            }
            if signature is not None:
                payload["id"] = signature["id"]
                if signature.get("phase") in {"commentary", "final_answer"}:
                    payload["phase"] = signature["phase"]
            output.append(payload)

    for part in message.content:
        part_type = _part_type(part)
        if part_type == "text":
            text = _part_text(part)
            if isinstance(text, str) and text.strip():
                text_buffer.append(
                    {
                        "text": text,
                        "text_signature": getattr(part, "text_signature", None),
                    }
                )
            continue
        _flush_text()
        if part_type == "thinking":
            signature = getattr(part, "thinking_signature", None)
            if not isinstance(signature, str) or not signature:
                continue
            try:
                reasoning_item = json.loads(signature)
            except Exception:
                continue
            if isinstance(reasoning_item, dict):
                output.append(reasoning_item)
            continue
        if part_type == "toolCall":
            tool_call_id = getattr(part, "id", None)
            tool_name = getattr(part, "name", None)
            tool_arguments = getattr(part, "arguments", {}) or {}
            if isinstance(tool_call_id, str) and tool_call_id:
                normalized_id = _normalize_responses_tool_call_id(
                    tool_call_id, model, message
                )
                tool_call_id_map[tool_call_id] = normalized_id
                tool_call_ids.append(normalized_id)
                call_id, item_id = _split_tool_call_id(normalized_id)
                payload = {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": tool_name or "",
                    "arguments": json.dumps(tool_arguments),
                }
                if item_id is not None:
                    payload["id"] = item_id
                output.append(payload)
    _flush_text()
    return output, tool_call_ids


def _part_type(part: object) -> str | None:
    return getattr(part, "type", None)


def _part_text(part: object) -> str | None:
    return getattr(part, "text", None)


def _part_data(part: object) -> str | None:
    return getattr(part, "data", None)


def _part_mime_type(part: object) -> str | None:
    return getattr(part, "mime_type", None)


def _tool_result_payload(
    message: object,
    model,
    tool_call_id_map: dict[str, str],
    capabilities: object | None = None,
) -> dict[str, Any] | None:
    if not isinstance(message, ToolResultMessage):
        return None
    text_parts = [
        sanitize_surrogates(part.text)
        for part in message.content
        if isinstance(part, TextPart) and part.text.strip()
    ]
    has_images = any(_part_type(part) == "image" for part in message.content)
    image_parts: list[dict[str, Any]] = []
    if _supports_image_input(model, capabilities):
        for part in message.content:
            if _part_type(part) != "image":
                continue
            data = _part_data(part)
            mime_type = _part_mime_type(part)
            if (
                isinstance(data, str)
                and data
                and isinstance(mime_type, str)
                and mime_type
            ):
                image_parts.append(
                    {
                        "type": "input_image",
                        "detail": "auto",
                        "image_url": f"data:{mime_type};base64,{data}",
                    }
                )
    if image_parts:
        output_parts: list[dict[str, Any]] = [
            {"type": "input_text", "text": text} for text in text_parts
        ]
        output_parts.extend(image_parts)
        output: str | list[dict[str, Any]] = output_parts
    else:
        output = (
            "\n".join(text_parts)
            if text_parts
            else "(see attached image)"
            if has_images
            else "No result provided"
        )
    return {
        "type": "function_call_output",
        "call_id": _split_tool_call_id(
            tool_call_id_map.get(message.tool_call_id, message.tool_call_id)
        )[0],
        "output": output,
    }


def _supports_image_input(model, capabilities: object | None) -> bool:
    if capabilities is not None:
        return bool(getattr(capabilities, "supports_image_input", False))
    return "image" in getattr(model, "input", ())


def _supports_reasoning(model, capabilities: object | None) -> bool:
    if capabilities is not None:
        supports_thinking = getattr(capabilities, "supports_thinking", None)
        if supports_thinking is not None:
            return bool(supports_thinking)
        return bool(getattr(capabilities, "reasoning", False))
    return bool(getattr(model, "supports_thinking", getattr(model, "reasoning", False)))


def _supports_developer_role(
    model, adapter_config: OpenAIResponsesConfig, capabilities: object | None
) -> bool:
    return _supports_reasoning(model, capabilities) and adapter_config.developer_role


def _normalize_id_part(part: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", part)
    normalized = sanitized[:64] if len(sanitized) > 64 else sanitized
    return re.sub(r"_+$", "", normalized) or "_"


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _build_foreign_responses_item_id(item_id: str) -> str:
    normalized = f"fc_{short_hash(item_id)}"
    return normalized[:64]


def _split_tool_call_id(tool_call_id: str) -> tuple[str, str | None]:
    if "|" not in tool_call_id:
        return tool_call_id, None
    call_id, item_id = tool_call_id.split("|", 1)
    return call_id, item_id


def _normalize_responses_tool_call_id(
    tool_call_id: str, model, source: AssistantMessage
) -> str:
    if "|" not in tool_call_id:
        return _normalize_id_part(tool_call_id)
    call_id, item_id = tool_call_id.split("|", 1)
    normalized_call_id = _normalize_id_part(call_id)
    is_foreign_tool_call = (
        source.provider != model.provider_id
        or source.endpoint != model.endpoint_id
        or source.api != resolve_model_api(model)
    )
    normalized_item_id = (
        _build_foreign_responses_item_id(item_id)
        if is_foreign_tool_call
        else _normalize_id_part(item_id)
    )
    if not normalized_item_id.startswith("fc_"):
        normalized_item_id = _normalize_id_part(f"fc_{normalized_item_id}")
    return f"{normalized_call_id}|{normalized_item_id}"
