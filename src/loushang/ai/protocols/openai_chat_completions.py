from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import suppress
from typing import Any, cast

from loushang.ai.context import NormalizedContext
from loushang.ai.errors import AIProviderProtocolError
from loushang.ai.event_stream.raw_parts import RawPart, UsageDeltaPart
from loushang.ai.model.domain import OpenAICompletionsConfig
from loushang.ai.output_budget import resolve_output_token_budget
from loushang.ai.protocols._helpers import (
    canonicalize_sdk_headers,
    close_provider_stream,
)
from loushang.ai.protocols._openai_sdk import OPENAI_SDK_API_KEY_PLACEHOLDER
from loushang.ai.provider import ProviderRequest
from loushang.ai.provider.errors import (
    provider_error_part,
    provider_error_part_from_raw,
)
from loushang.ai.structured import openai_chat_response_format
from loushang.ai.tool.providers import sanitize_tool_parameters
from loushang.ai.tool.transform import MISSING_TOOL_RESULT_TEXT
from loushang.ai.trace import emit_trace as _emit_trace
from loushang.ai.types import AssistantMessage, TextPart, Tool, ToolResultMessage
from loushang.ai.utils import sanitize_surrogates


class OpenAIChatCompletionsAdapter:
    api = "openai-completions"
    supports_structured_output = True

    def __init__(self, *, client: Any | None = None) -> None:
        self._client = client

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        model = request.model
        options = request.options
        resolved = request

        def _debug(event: str, data: dict | None = None) -> None:
            _emit_trace(options, {"type": f"sdk:{event}", **(data or {})})

        normalized = request.context
        adapter_config = _request_adapter_config(resolved)
        supports_usage_in_streaming = adapter_config.streaming_usage
        supports_store = adapter_config.store
        max_tokens_field = adapter_config.max_output_tokens_field or "max_tokens"
        thinking_format = adapter_config.reasoning_format
        reasoning_effort_map = dict(adapter_config.reasoning_effort_map)
        supports_reasoning_effort = adapter_config.reasoning_effort

        # OpenAI Python SDK
        try:
            from openai import AsyncOpenAI, Omit  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "openai SDK is not installed. Install via `pip install openai`"
            ) from e

        headers = resolved.headers or {}
        default_headers = canonicalize_sdk_headers(headers)

        client_kwargs: dict[str, Any] = {
            "api_key": OPENAI_SDK_API_KEY_PLACEHOLDER,
            "base_url": resolved.base_url,
        }
        client = self._client or AsyncOpenAI(**client_kwargs)  # type: ignore[call-arg]
        _debug(
            "client",
            {
                "api": model.api,
                "provider": model.provider_id,
                "endpoint": model.endpoint_id,
                "model": model.id,
            },
        )

        capabilities = model.capabilities
        messages_param = _build_messages(
            model,
            normalized,
            adapter_config,
            capabilities,
        )
        tools_param = _build_tools(normalized.tools, adapter_config)
        if tools_param is None and _has_tool_history(list(normalized.messages)):
            tools_param = []
        max_tokens = resolve_output_token_budget(model, resolved).value
        upstream_model_id = model.upstream_id or model.id
        is_stream_request = getattr(resolved, "mode", "stream") == "stream"
        params: dict[str, Any] = {
            "model": upstream_model_id,
            "messages": messages_param,
        }
        if is_stream_request:
            params["stream"] = True
        extra_body: dict[str, Any] = {}
        if is_stream_request and supports_usage_in_streaming:
            params["stream_options"] = {"include_usage": True}
        if supports_store:
            params["store"] = False
        if max_tokens_field == "max_tokens":
            params["max_tokens"] = max_tokens
        else:
            params["max_completion_tokens"] = max_tokens
        if resolved.temperature is not None:
            params["temperature"] = resolved.temperature
        if tools_param is not None:
            params["tools"] = tools_param
        tool_choice = getattr(options, "tool_choice", None)
        if tool_choice is not None:
            params["tool_choice"] = tool_choice
        response_format = openai_chat_response_format(options)
        if response_format is not None:
            params["response_format"] = response_format
        reasoning_effort = getattr(resolved, "reasoning_effort", None)
        _apply_reasoning_params(
            params,
            extra_body,
            model=model,
            thinking_format=thinking_format,
            reasoning_enabled=resolved.reasoning_enabled,
            reasoning_effort=reasoning_effort,
            reasoning_effort_map=reasoning_effort_map,
            supports_reasoning_effort=supports_reasoning_effort,
            capabilities=capabilities,
        )
        if extra_body:
            params["extra_body"] = extra_body
        _debug(
            "payload",
            {
                "api": model.api,
                "provider": model.provider_id,
                "endpoint": model.endpoint_id,
                "model": model.id,
                "parameter_keys": sorted(params),
                "message_count": len(messages_param),
                "tool_count": len(tools_param or []),
            },
        )
        params["extra_headers"] = {
            "Authorization": Omit(),
            "X-Api-Key": Omit(),
            **default_headers,
        }

        try:
            response = await client.chat.completions.create(**params)
        except Exception as e:
            _debug("stream_error", {"exceptionType": type(e).__name__})
            yield provider_error_part(e, source=self.api)
            return
        if not is_stream_request:
            for part in _iter_complete_response_parts(response, source=self.api):
                yield part
            return

        stream_ctx = response
        _debug("stream_begin")
        try:
            emitted_response_start = False
            emitted_any_text = False
            active_tool_call_ids: list[str] = []
            active_tool_call_indexes: dict[str, int] = {}
            tool_call_ids_by_index: dict[int, str] = {}
            received_finish_reason = False
            while True:
                try:
                    chunk = await stream_ctx.__anext__()  # type: ignore[attr-defined]
                except StopAsyncIteration:
                    _debug("stream_end", {"reason": "upstream_eof"})
                    break
                except Exception as e:
                    _debug("stream_iter_error", {"exceptionType": type(e).__name__})
                    yield provider_error_part(e, source=self.api)
                    return
                if not chunk:
                    continue
                # response id
                if not emitted_response_start:
                    resp_id = getattr(chunk, "id", None)
                    _debug("event", {"kind": "response_start", "response_id": resp_id})
                    if isinstance(resp_id, str) and resp_id:
                        emitted_response_start = True
                        yield {"type": "response_start", "response_id": resp_id}
                # usage
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    usage_part = _usage_part_from_chat_usage(usage)
                    _debug(
                        "event",
                        {
                            "kind": "usage_delta",
                            "input": usage_part["input"],
                            "output": usage_part["output"],
                            "cache_read": usage_part["cache_read"],
                            "total_tokens": usage_part["total_tokens"],
                        },
                    )
                    yield usage_part
                choices = getattr(chunk, "choices", None)
                choice = choices[0] if isinstance(choices, list) and choices else None
                if choice is None:
                    continue
                if usage is None:
                    choice_usage = getattr(choice, "usage", None)
                    if choice_usage is not None:
                        yield _usage_part_from_chat_usage(choice_usage)
                # deltas
                delta = getattr(choice, "delta", None)
                if delta is not None:
                    for candidate in (
                        "reasoning_content",
                        "reasoning",
                        "reasoning_text",
                    ):
                        reasoning_value = getattr(delta, candidate, None)
                        if isinstance(reasoning_value, str) and reasoning_value:
                            _debug(
                                "event",
                                {
                                    "kind": "thinking_delta",
                                    "field": candidate,
                                    "len": len(reasoning_value),
                                },
                            )
                            yield {"type": "thinking_delta", "text": reasoning_value}
                            break
                    reasoning_details = getattr(delta, "reasoning_details", None)
                    if isinstance(reasoning_details, list):
                        for detail in reasoning_details:
                            detail_type = (
                                getattr(detail, "type", None)
                                if not isinstance(detail, dict)
                                else detail.get("type")
                            )
                            detail_id = (
                                getattr(detail, "id", None)
                                if not isinstance(detail, dict)
                                else detail.get("id")
                            )
                            detail_data = (
                                getattr(detail, "data", None)
                                if not isinstance(detail, dict)
                                else detail.get("data")
                            )
                            if (
                                detail_type == "reasoning.encrypted"
                                and isinstance(detail_id, str)
                                and detail_id
                                and isinstance(detail_data, str)
                                and detail_data
                            ):
                                yield {
                                    "type": "tool_call_thought_signature",
                                    "tool_call_id": detail_id,
                                    "thought_signature": __import__("json").dumps(
                                        {
                                            "type": detail_type,
                                            "id": detail_id,
                                            "data": detail_data,
                                        }
                                    ),
                                }
                    text = getattr(delta, "content", None)
                    if isinstance(text, str) and text:
                        emitted_any_text = True
                        _debug(
                            "event",
                            {
                                "kind": "text_delta",
                                "len": len(text),
                                "preview": text[:120],
                            },
                        )
                        yield {"type": "text_delta", "text": text}
                    tool_calls = getattr(delta, "tool_calls", None)
                    if isinstance(tool_calls, list):
                        for tool_call in tool_calls:
                            raw_tool_call_id = getattr(tool_call, "id", None)
                            tool_call_index = _optional_int(
                                getattr(tool_call, "index", None)
                            )
                            tool_call_id = (
                                raw_tool_call_id
                                if isinstance(raw_tool_call_id, str)
                                and raw_tool_call_id
                                else None
                            )
                            if tool_call_id is None and tool_call_index is not None:
                                tool_call_id = tool_call_ids_by_index.get(
                                    tool_call_index
                                )
                            function = getattr(tool_call, "function", None)
                            tool_call_name = (
                                getattr(function, "name", None)
                                if function is not None
                                else None
                            )
                            tool_call_arguments = (
                                getattr(function, "arguments", None)
                                if function is not None
                                else None
                            )
                            if (
                                isinstance(tool_call_id, str)
                                and tool_call_id
                                and tool_call_id not in active_tool_call_ids
                            ):
                                active_tool_call_ids.append(tool_call_id)
                                if tool_call_index is not None:
                                    active_tool_call_indexes[tool_call_id] = (
                                        tool_call_index
                                    )
                                    tool_call_ids_by_index[tool_call_index] = (
                                        tool_call_id
                                    )
                                start_part: dict[str, object] = {
                                    "type": "tool_call_start",
                                    "id": tool_call_id,
                                    "name": tool_call_name or "",
                                }
                                if tool_call_index is not None:
                                    start_part["index"] = tool_call_index
                                yield _raw_part(start_part)
                            elif (
                                isinstance(tool_call_id, str)
                                and tool_call_id
                                and tool_call_index is not None
                            ):
                                active_tool_call_indexes.setdefault(
                                    tool_call_id, tool_call_index
                                )
                                tool_call_ids_by_index.setdefault(
                                    tool_call_index, tool_call_id
                                )
                            if (
                                isinstance(tool_call_arguments, str)
                                and tool_call_arguments
                            ):
                                delta_part: dict[str, object] = {
                                    "type": "tool_call_args_delta",
                                    "delta": tool_call_arguments,
                                }
                                if isinstance(tool_call_id, str) and tool_call_id:
                                    delta_part["tool_call_id"] = tool_call_id
                                elif tool_call_index is not None:
                                    delta_part["index"] = tool_call_index
                                yield _raw_part(delta_part)
                # finish reason
                finish = getattr(choice, "finish_reason", None)
                if isinstance(finish, str):
                    received_finish_reason = True
                    for tool_call_id in active_tool_call_ids:
                        done_part: dict[str, object] = {
                            "type": "tool_call_done",
                            "tool_call_id": tool_call_id,
                        }
                        if tool_call_id in active_tool_call_indexes:
                            done_part["index"] = active_tool_call_indexes[tool_call_id]
                        yield _raw_part(done_part)
                    active_tool_call_ids = []
                    active_tool_call_indexes = {}
                    tool_call_ids_by_index = {}
                    # 有些上游在流模式下仅在最后一次返回完整 message.content，而不逐字增量
                    if not emitted_any_text:
                        msg_obj = getattr(choice, "message", None)
                        msg_content = (
                            getattr(msg_obj, "content", None)
                            if msg_obj is not None
                            else None
                        )
                        if isinstance(msg_content, str) and msg_content:
                            emitted_any_text = True
                            _debug(
                                "event",
                                {
                                    "kind": "text_delta_fallback",
                                    "len": len(msg_content),
                                    "preview": msg_content[:120],
                                },
                            )
                            yield {"type": "text_delta", "text": msg_content}
                    mapped = _map_stop_reason(finish)
                    _debug(
                        "event",
                        {"kind": "stop_reason", "raw": finish, "mapped": mapped},
                    )
                    yield {"type": "stop_reason", "stop_reason": mapped}
                    if mapped == "error":
                        yield provider_error_part_from_raw(
                            f"provider finish_reason={finish}",
                            code=finish,
                            source=self.api,
                        )
                        return
            if not received_finish_reason:
                yield provider_error_part(
                    AIProviderProtocolError(
                        "provider stream ended before a terminal response event",
                        source=self.api,
                    ),
                    source=self.api,
                )
                return
            for tool_call_id in active_tool_call_ids:
                done_part = {"type": "tool_call_done", "tool_call_id": tool_call_id}
                if tool_call_id in active_tool_call_indexes:
                    done_part["index"] = active_tool_call_indexes[tool_call_id]
                yield _raw_part(done_part)
            _debug("stream_done", {})
            yield {"type": "response_done"}
        except Exception as e:
            _debug("stream_iter_error_outer", {"exceptionType": type(e).__name__})
            yield provider_error_part(e, source=self.api)
        finally:
            await close_provider_stream(stream_ctx)


def _request_adapter_config(request: ProviderRequest) -> OpenAICompletionsConfig:
    adapter_config = request.model.adapter
    if isinstance(adapter_config, OpenAICompletionsConfig):
        return adapter_config
    return OpenAICompletionsConfig()


def _raw_part(part: dict[str, object]) -> RawPart:
    return cast(RawPart, part)


def _iter_complete_response_parts(
    response: object, *, source: str
) -> Iterator[RawPart]:
    resp_id = getattr(response, "id", None)
    if isinstance(resp_id, str) and resp_id:
        yield {"type": "response_start", "response_id": resp_id}

    usage = getattr(response, "usage", None)
    if usage is not None:
        yield _usage_part_from_chat_usage(usage)

    choices = getattr(response, "choices", None)
    if isinstance(choices, list):
        for choice in choices:
            message = getattr(choice, "message", None)
            if message is not None:
                yield from _iter_complete_message_parts(message)
            finish = getattr(choice, "finish_reason", None)
            if isinstance(finish, str):
                mapped = _map_stop_reason(finish)
                yield {"type": "stop_reason", "stop_reason": mapped}
                if mapped == "error":
                    yield provider_error_part_from_raw(
                        f"provider finish_reason={finish}",
                        code=finish,
                        source=source,
                    )
                    return
    yield {"type": "response_done"}


def _iter_complete_message_parts(message: object) -> Iterator[RawPart]:
    for candidate in (
        "reasoning_content",
        "reasoning",
        "reasoning_text",
    ):
        reasoning_value = getattr(message, candidate, None)
        if isinstance(reasoning_value, str) and reasoning_value:
            yield {"type": "thinking_delta", "text": reasoning_value}
            break
    reasoning_details = getattr(message, "reasoning_details", None)
    if isinstance(reasoning_details, list):
        for detail in reasoning_details:
            detail_type = (
                getattr(detail, "type", None)
                if not isinstance(detail, dict)
                else detail.get("type")
            )
            detail_id = (
                getattr(detail, "id", None)
                if not isinstance(detail, dict)
                else detail.get("id")
            )
            detail_data = (
                getattr(detail, "data", None)
                if not isinstance(detail, dict)
                else detail.get("data")
            )
            if (
                detail_type == "reasoning.encrypted"
                and isinstance(detail_id, str)
                and detail_id
                and isinstance(detail_data, str)
                and detail_data
            ):
                yield {
                    "type": "tool_call_thought_signature",
                    "tool_call_id": detail_id,
                    "thought_signature": json.dumps(
                        {
                            "type": detail_type,
                            "id": detail_id,
                            "data": detail_data,
                        }
                    ),
                }

    text = getattr(message, "content", None)
    if isinstance(text, str) and text:
        yield {"type": "text_delta", "text": text}

    tool_calls = getattr(message, "tool_calls", None)
    if isinstance(tool_calls, list):
        for index, tool_call in enumerate(tool_calls):
            tool_call_id = getattr(tool_call, "id", None)
            if not isinstance(tool_call_id, str) or not tool_call_id:
                tool_call_id = f"tool_call_{index}"
            function = getattr(tool_call, "function", None)
            name = getattr(function, "name", "") if function is not None else ""
            arguments = (
                getattr(function, "arguments", None) if function is not None else None
            )
            yield _raw_part(
                {
                    "type": "tool_call_start",
                    "id": tool_call_id,
                    "name": name if isinstance(name, str) else "",
                    "index": index,
                }
            )
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


def _usage_part_from_chat_usage(usage: object) -> UsageDeltaPart:
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    cached = (
        getattr(
            getattr(usage, "prompt_tokens_details", None) or {},
            "cached_tokens",
            0,
        )
        or 0
    )
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    return {
        "type": "usage_delta",
        "input": input_tokens - cached,
        "output": output_tokens,
        "cache_read": cached,
        "cache_write": 0,
        "total_tokens": (input_tokens - cached) + output_tokens + cached,
    }


def _map_stop_reason(reason: str) -> str:
    if reason in {"stop", "end"}:
        return "stop"
    if reason == "length":
        return "length"
    if reason in {"function_call", "tool_calls"}:
        return "toolUse"
    if reason in {"content_filter", "network_error"}:
        return "error"
    return "error"


def _apply_reasoning_params(
    params: dict[str, Any],
    extra_body: dict[str, Any],
    *,
    model,
    thinking_format: str | None,
    reasoning_enabled: bool | None,
    reasoning_effort: str | None,
    reasoning_effort_map: Mapping[str, str | None],
    supports_reasoning_effort: bool,
    capabilities: object | None = None,
) -> None:
    if not _supports_reasoning(model, capabilities):
        return
    if reasoning_enabled is None:
        return
    if thinking_format == "moonshot":
        extra_body["thinking"] = {
            "type": "enabled" if reasoning_enabled else "disabled"
        }
        return
    if thinking_format == "deepseek":
        extra_body["thinking"] = {
            "type": "enabled" if reasoning_enabled else "disabled"
        }
        _apply_reasoning_effort_if_supported(
            params,
            reasoning_effort,
            reasoning_effort_map,
            supports_reasoning_effort,
        )
        return
    if thinking_format == "zai-thinking":
        params["thinking"] = {"type": "enabled" if reasoning_enabled else "disabled"}
        _apply_reasoning_effort_if_supported(
            params,
            reasoning_effort,
            reasoning_effort_map,
            supports_reasoning_effort,
        )
        return
    if reasoning_enabled:
        _apply_reasoning_effort_if_supported(
            params,
            reasoning_effort,
            reasoning_effort_map,
            supports_reasoning_effort,
        )
    elif supports_reasoning_effort:
        params["reasoning_effort"] = "none"


def _apply_reasoning_effort_if_supported(
    params: dict[str, Any],
    reasoning_effort: str | None,
    reasoning_effort_map: Mapping[str, str | None],
    supports_reasoning_effort: bool,
) -> None:
    if isinstance(reasoning_effort, str) and supports_reasoning_effort:
        params["reasoning_effort"] = _map_reasoning_effort(
            reasoning_effort, reasoning_effort_map
        )


def _map_reasoning_effort(
    effort: str | None,
    reasoning_effort_map: Mapping[str, str | None],
) -> str | None:
    if not isinstance(effort, str):
        return "none"
    return reasoning_effort_map.get(effort, effort)


def _supports_image_input(model: object, capabilities: object | None = None) -> bool:
    if capabilities is not None:
        return bool(getattr(capabilities, "supports_image_input", False))
    return "image" in getattr(model, "input", ())


def _supports_reasoning(model: object, capabilities: object | None = None) -> bool:
    if capabilities is not None:
        supports_thinking = getattr(capabilities, "supports_thinking", None)
        if supports_thinking is not None:
            return bool(supports_thinking)
        return bool(getattr(capabilities, "reasoning", False))
    return bool(
        getattr(
            model,
            "supports_thinking",
            getattr(model, "reasoning", False),
        )
    )


def _build_messages(
    model,
    normalized: NormalizedContext,
    adapter_config: OpenAICompletionsConfig,
    capabilities: object | None = None,
) -> list[dict[str, Any]]:
    messages_param: list[dict[str, Any]] = []
    system_prompt = normalized.system_prompt
    supports_developer_role = adapter_config.developer_role
    if isinstance(system_prompt, str) and system_prompt.strip():
        role = (
            "developer"
            if _supports_reasoning(model, capabilities) and supports_developer_role
            else "system"
        )
        messages_param.append(
            {"role": role, "content": sanitize_surrogates(system_prompt)}
        )

    messages = normalized.messages
    index = 0
    while index < len(messages):
        msg = messages[index]
        message_role = _message_role(msg)
        if message_role == "user":
            payload = _user_message_payload(msg, model, capabilities)
            if payload is not None:
                messages_param.append(payload)
            index += 1
            continue
        if message_role == "assistant":
            payload = _assistant_message_payload(
                msg, adapter_config, model, capabilities
            )
            if payload is not None:
                messages_param.append(payload)
            index += 1
            continue
        if message_role == "toolResult":
            image_blocks: list[dict[str, Any]] = []
            while (
                index < len(messages) and _message_role(messages[index]) == "toolResult"
            ):
                tool_payload, tool_images = _tool_result_payload(
                    messages[index],
                    model,
                    capabilities,
                )
                messages_param.append(tool_payload)
                image_blocks.extend(tool_images)
                index += 1
            if image_blocks:
                messages_param.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Attached image(s) from tool result:",
                            },
                            *image_blocks,
                        ],
                    }
                )
            continue
        index += 1
    return messages_param


def _build_tools(
    tools: Sequence[Tool] | None,
    adapter_config: OpenAICompletionsConfig,
) -> list[dict[str, Any]] | None:
    if not isinstance(tools, Sequence) or isinstance(tools, str) or not tools:
        return None
    supports_strict_mode = adapter_config.strict_schema
    payload: list[dict[str, Any]] = []
    for tool in tools:
        function_payload = {
            "name": tool.name,
            "description": tool.description,
            "parameters": sanitize_tool_parameters(tool.parameters),
        }
        if supports_strict_mode:
            function_payload["strict"] = False
        payload.append({"type": "function", "function": function_payload})
    return payload


def _has_tool_history(messages: list[object]) -> bool:
    for msg in messages:
        role = _message_role(msg)
        if role == "toolResult":
            return True
        if (
            role == "assistant"
            and isinstance(msg, AssistantMessage)
            and any(getattr(block, "type", None) == "toolCall" for block in msg.content)
        ):
            return True
    return False


def _message_role(message: object) -> str | None:
    return getattr(message, "role", None)


def _user_message_payload(
    message: object, model, capabilities: object | None = None
) -> dict[str, Any] | None:
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return None
    parts: list[dict[str, Any]] = []
    text_fragments: list[str] = []
    for part in content:
        part_type = _part_type(part)
        if part_type == "text":
            text = _part_text(part)
            if isinstance(text, str) and text.strip():
                sanitized_text = sanitize_surrogates(text)
                text_fragments.append(sanitized_text)
                parts.append({"type": "text", "text": sanitized_text})
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
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{data}"},
                    }
                )
    if not parts:
        return None
    if len(parts) == len(text_fragments) and text_fragments:
        return {"role": "user", "content": "\n".join(text_fragments)}
    return {"role": "user", "content": parts}


def _assistant_message_payload(
    message: object,
    adapter_config: OpenAICompletionsConfig,
    model,
    capabilities: object | None = None,
) -> dict[str, Any] | None:
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return None
    text_blocks: list[str] = []
    thinking_blocks: list[tuple[str, str | None]] = []
    tool_calls: list[dict[str, Any]] = []
    reasoning_details: list[dict[str, Any]] = []
    for part in content:
        part_type = _part_type(part)
        if part_type == "text":
            text = _part_text(part)
            if isinstance(text, str) and text.strip():
                text_blocks.append(sanitize_surrogates(text))
        elif part_type == "thinking":
            thinking = getattr(part, "thinking", None)
            signature = getattr(part, "thinking_signature", None)
            if isinstance(thinking, str) and thinking.strip():
                thinking_blocks.append(
                    (
                        sanitize_surrogates(thinking),
                        signature if isinstance(signature, str) else None,
                    )
                )
        elif part_type == "toolCall":
            tool_id = getattr(part, "id", None)
            tool_name = getattr(part, "name", None)
            tool_args = getattr(part, "arguments", {}) or {}
            if isinstance(tool_id, str) and tool_id:
                tool_calls.append(
                    {
                        "id": tool_id,
                        "type": "function",
                        "function": {
                            "name": tool_name or "",
                            "arguments": __import__("json").dumps(tool_args),
                        },
                    }
                )
                thought_signature = getattr(part, "thought_signature", None)
                if isinstance(thought_signature, str) and thought_signature:
                    with suppress(Exception):
                        reasoning_details.append(json.loads(thought_signature))
    assistant_content = "".join(text_blocks) if text_blocks else None
    payload: dict[str, Any] = {"role": "assistant", "content": assistant_content}
    if thinking_blocks:
        thinking_text = "\n\n".join(block for block, _ in thinking_blocks)
        for _, signature in thinking_blocks:
            if isinstance(signature, str) and signature:
                payload[signature] = thinking_text
                break
    if tool_calls:
        payload["tool_calls"] = tool_calls
    if reasoning_details:
        payload["reasoning_details"] = reasoning_details
    if (
        adapter_config.assistant_reasoning_content
        and _supports_reasoning(model, capabilities)
        and "reasoning_content" not in payload
    ):
        payload["reasoning_content"] = ""
    content_value = payload.get("content")
    has_content = content_value is not None and (
        not isinstance(content_value, str) or content_value != ""
    )
    if not has_content and not tool_calls and not payload.keys() - {"role", "content"}:
        return None
    return payload


def _tool_result_payload(
    message: object,
    model,
    capabilities: object | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assert isinstance(message, ToolResultMessage)
    text_parts = [
        sanitize_surrogates(part.text)
        for part in message.content
        if isinstance(part, TextPart) and part.text.strip()
    ]
    text_result = "\n".join(text_parts)
    has_images = any(_part_type(part) == "image" for part in message.content)
    image_blocks: list[dict[str, Any]] = []
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
                image_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{data}"},
                    }
                )
    tool_payload = {
        "role": "tool",
        "tool_call_id": message.tool_call_id,
        "content": text_result
        or ("(see attached image)" if has_images else MISSING_TOOL_RESULT_TEXT),
    }
    return tool_payload, image_blocks


def _part_type(part: object) -> str | None:
    return getattr(part, "type", None)


def _part_text(part: object) -> str | None:
    return getattr(part, "text", None)


def _part_data(part: object) -> str | None:
    return getattr(part, "data", None)


def _part_mime_type(part: object) -> str | None:
    return getattr(part, "mime_type", None)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None
