from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any, cast

from loushang.ai.context import NormalizedContext
from loushang.ai.errors import AIProviderProtocolError
from loushang.ai.event_stream.raw_parts import RawPart, UsageDeltaPart
from loushang.ai.model.domain import AnthropicMessagesConfig
from loushang.ai.options import (
    get_reasoning_budget_tokens,
)
from loushang.ai.output_budget import resolve_output_token_budget
from loushang.ai.prepared_request import invoke_prepared_request
from loushang.ai.protocols._anthropic import AnthropicMessagesProtocol
from loushang.ai.protocols._helpers import canonicalize_sdk_headers
from loushang.ai.provider import PreparedModelRequest, ProviderRequest
from loushang.ai.provider.errors import (
    provider_error_part,
    provider_error_part_from_raw,
)
from loushang.ai.tool import to_anthropic_tools
from loushang.ai.tool.helpers import (
    compute_remaining_context,
    estimate_tokens_simple_from_messages,
)
from loushang.ai.trace import emit_trace as _emit_trace
from loushang.ai.utils import parse_streaming_json, sanitize_surrogates


def _build_anthropic_message_payloads(
    normalized: NormalizedContext,
) -> tuple[list[dict[str, Any]], list[dict[str, str]] | None]:
    messages_param: list[dict[str, Any]] = []
    system_param = None
    system_prompt = normalized.system_prompt
    if isinstance(system_prompt, str) and system_prompt.strip():
        system_param = [{"type": "text", "text": sanitize_surrogates(system_prompt)}]
    for msg in normalized.messages:
        role = getattr(msg, "role", None)
        if role == "user":
            content = getattr(msg, "content", None)
            if isinstance(content, list):
                user_blocks: list[dict[str, object]] = []
                for p in content:
                    ptype = getattr(p, "type", None)
                    if ptype == "text":
                        txt = getattr(p, "text", "")
                        if isinstance(txt, str) and txt.strip():
                            user_blocks.append(
                                {"type": "text", "text": sanitize_surrogates(txt)}
                            )
                    elif ptype == "image":
                        data = getattr(p, "data", "")
                        mime = getattr(p, "mime_type", "")
                        if (
                            isinstance(data, str)
                            and data
                            and isinstance(mime, str)
                            and mime
                        ):
                            user_blocks.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime,
                                        "data": data,
                                    },
                                }
                            )
                if user_blocks:
                    messages_param.append({"role": "user", "content": user_blocks})
        elif role == "assistant":
            content = getattr(msg, "content", None)
            if isinstance(content, list):
                assistant_blocks: list[dict[str, object]] = []
                for p in content:
                    ptype = getattr(p, "type", None)
                    if ptype == "image":
                        data = getattr(p, "data", "")
                        mime = getattr(p, "mime_type", "")
                        if (
                            isinstance(data, str)
                            and data
                            and isinstance(mime, str)
                            and mime
                        ):
                            assistant_blocks.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime,
                                        "data": data,
                                    },
                                }
                            )
                        continue
                    payload = (
                        AnthropicMessagesProtocol.assistant_block_to_anthropic_payload(p)
                    )
                    if payload is not None:
                        assistant_blocks.append(payload)
                if assistant_blocks:
                    messages_param.append(
                        {"role": "assistant", "content": assistant_blocks}
                    )
        elif role == "toolResult":
            tool_call_id = getattr(msg, "tool_call_id", None)
            is_error = getattr(msg, "is_error", None)
            content = getattr(msg, "content", None)
            if isinstance(tool_call_id, str) and tool_call_id:
                _append_tool_result_payload(
                    messages_param,
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call_id,
                        "content": AnthropicMessagesProtocol.tool_result_content_to_anthropic_payload(
                            content
                        ),
                        "is_error": bool(is_error),
                    },
                )
    return messages_param, system_param


def _append_tool_result_payload(
    messages_param: list[dict[str, Any]],
    tool_result: dict[str, Any],
) -> None:
    if messages_param:
        previous = messages_param[-1]
        previous_content = previous.get("content")
        if (
            previous.get("role") == "user"
            and isinstance(previous_content, list)
            and previous_content
            and all(
                isinstance(block, dict) and block.get("type") == "tool_result"
                for block in previous_content
            )
        ):
            previous_content.append(tool_result)
            return
    messages_param.append({"role": "user", "content": [tool_result]})


def _tool_input_to_json_delta(value: object) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        if not value:
            return None
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return None


_MISSING = object()


@dataclass
class _AnthropicToolStreamState:
    args_from_start: bool = False
    arg_chunks: list[str] = field(default_factory=list)
    id: str | None = None
    name: str | None = None
    args_source: str = "none"
    delta_chars: int = 0


def _get_tool_stream_state(
    states: dict[int | None, _AnthropicToolStreamState],
    content_index: int | None,
) -> _AnthropicToolStreamState | None:
    state = states.get(content_index)
    if state is not None:
        return state
    if content_index is not None and len(states) == 1:
        return states.get(None)
    return None


def _pop_tool_stream_state(
    states: dict[int | None, _AnthropicToolStreamState],
    content_index: int | None,
) -> _AnthropicToolStreamState | None:
    state = states.pop(content_index, None)
    if state is not None:
        return state
    if content_index is not None and len(states) == 1:
        return states.pop(None, None)
    return None


def _summarize_tool_args_json(raw: str) -> dict[str, object]:
    summary: dict[str, object] = {"chars": len(raw)}
    if not raw:
        return {**summary, "valid_json": False, "error": "empty"}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        repaired = parse_streaming_json(raw)
        repair_summary: dict[str, object] = {"repair_valid": bool(repaired)}
        if repaired:
            repair_summary.update(
                {
                    "repaired_keys": sorted(str(key) for key in repaired),
                    "repaired_content_chars": len(repaired["content"])
                    if isinstance(repaired.get("content"), str)
                    else None,
                }
            )
        return {
            **summary,
            "valid_json": False,
            "error_position": error.pos,
            **repair_summary,
        }
    if not isinstance(parsed, dict):
        return {
            **summary,
            "valid_json": True,
            "kind": type(parsed).__name__,
        }
    return {
        **summary,
        "valid_json": True,
        "kind": "object",
        "keys": sorted(str(key) for key in parsed),
        "content_chars": len(parsed["content"])
        if isinstance(parsed.get("content"), str)
        else None,
    }


class AnthropicMessagesAdapter(AnthropicMessagesProtocol):
    api = "anthropic-messages"

    def __init__(self, *, client: Any | None = None) -> None:
        # 允许注入自建客户端（同步或异步），否则按需创建
        self._client = client

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        """
        将 Anthropic SDK 的 streaming 事件映射到 RawPart。
        当前实现覆盖文本、thinking、signature、redacted thinking、工具增量、usage、stop_reason 与完成事件。
        """
        async for part in invoke_prepared_request(self, request):
            yield part

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        model = request.model
        options = request.options
        resolved = request

        def _debug(event: str, data: dict | None = None) -> None:
            payload = {"type": f"sdk:{event}"}
            if data:
                for key, value in data.items():
                    payload["event_type" if key == "type" else key] = value
            _emit_trace(options, payload)

        normalized = request.context
        adapter_config = _request_adapter_config(resolved)
        # Resolved headers mix transport configuration and credentials.  They
        # are never eligible for durable/model-visible projection because
        # provenance has already been erased at this boundary.  Only behavior
        # headers generated from typed adapter inputs are frozen and replayed.
        protocol_headers: dict[str, str] = {}
        need_ilt = self.should_inject_interleaved_thinking(
            reasoning_enabled=resolved.reasoning_enabled,
            adapter_config=adapter_config,
        )
        need_fg = self.should_inject_fine_grained_tools(
            adapter_config=adapter_config,
            headers=None,
        )
        if need_ilt or need_fg:
            protocol_headers = self.apply_beta_headers(
                existing_headers=protocol_headers,
                need_interleaved_beta=need_ilt,
                force_fine_grained_tools=need_fg,
            )
        model_visible_headers = {
            name: value
            for name, value in protocol_headers.items()
            if name.casefold() == "anthropic-beta"
        }

        messages_param, system_param = _build_anthropic_message_payloads(normalized)
        upstream_model_id = model.upstream_id or model.id

        tools_param = None
        if normalized.tools:
            tools_param = []
            tools_param.extend(to_anthropic_tools(list(normalized.tools)))

        max_tokens = resolve_output_token_budget(model, resolved).value
        thinking_cfg: dict[str, object] | None = None
        # 思考模式：自适应或预算式；与 temperature 互斥
        want_thinking = resolved.reasoning_enabled is True
        if want_thinking:
            if self.supports_adaptive_thinking(adapter_config):
                thinking_cfg = {"type": "adaptive"}
            else:
                thinking_budget_tokens = get_reasoning_budget_tokens(options)
                thinking_cfg = {
                    "type": "enabled",
                    "budget_tokens": thinking_budget_tokens
                    if isinstance(thinking_budget_tokens, int)
                    else 1024,
                }

        params: dict[str, Any] = {
            "model": upstream_model_id,
            "messages": messages_param,
            "max_tokens": max_tokens,
        }
        if system_param:
            params["system"] = system_param
        if tools_param:
            params["tools"] = tools_param
        if thinking_cfg:
            params["thinking"] = thinking_cfg
        # 若存在自适应思考的 effort，注入 output_config
        if want_thinking and self.supports_adaptive_thinking(adapter_config):
            effort = self.map_thinking_level_to_effort(
                resolved.reasoning_effort,
                adapter_config,
            )
            if effort:
                params["output_config"] = {"effort": effort}
        # 透传 tool_choice（auto/any/none 或 {type:'tool', name:...}）
        tool_choice = getattr(options, "tool_choice", None)
        if tool_choice is not None:
            if isinstance(tool_choice, str):
                params["tool_choice"] = {"type": tool_choice}
            elif isinstance(tool_choice, dict) and "type" in tool_choice:
                params["tool_choice"] = tool_choice
        # 注入 cache_control（system/最后一个 user）
        cc = self.get_cache_control(
            base_url=resolved.base_url,
            cache_retention=getattr(options, "cache_retention", None)
            if options is not None
            else None,
            supports_long_cache_retention=adapter_config.long_cache_retention,
        )
        cache_control = cc.get("cacheControl")
        if cache_control:
            if isinstance(params.get("system"), list) and params["system"]:
                last = params["system"][-1]
                if isinstance(last, dict):
                    last.setdefault("cache_control", cache_control)
            # 最后一个 user 消息
            for m in reversed(params.get("messages", [])):
                if isinstance(m, dict) and m.get("role") == "user":
                    content = m.get("content")
                    if isinstance(content, list) and content:
                        lb = content[-1]
                        if isinstance(lb, dict) and lb.get("type") in {
                            "text",
                            "image",
                            "tool_result",
                        }:
                            lb.setdefault("cache_control", cache_control)
                    break
        # temperature：仅在未启用思考时设置
        if not thinking_cfg and resolved.temperature is not None:
            params["temperature"] = resolved.temperature
        # Clamp max_tokens by remaining context if capability provides window
        remaining = compute_remaining_context(
            getattr(model, "context_window", None),
            estimate_tokens_simple_from_messages(list(normalized.messages)),
            safety_margin=64,
        )
        if remaining is not None and isinstance(params.get("max_tokens"), int):
            before = params["max_tokens"]
            params["max_tokens"] = max(1, min(before, remaining))
            _emit_trace(
                options,
                {
                    "type": "clamp",
                    "api": model.api,
                    "provider": model.provider_id,
                    "field": "max_tokens",
                    "before": before,
                    "after": params["max_tokens"],
                    "remaining": remaining,
                },
            )

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
        return PreparedModelRequest.from_provider_request(
            request,
            payload=params,
            model_visible_headers=model_visible_headers,
        )

    async def invoke_prepared_raw(
        self,
        request: ProviderRequest,
        prepared: PreparedModelRequest,
    ) -> AsyncIterator[RawPart]:
        model = request.model
        options = request.options
        resolved = request

        def _debug(event: str, data: dict | None = None) -> None:
            payload = {"type": f"sdk:{event}"}
            if data:
                for key, value in data.items():
                    payload["event_type" if key == "type" else key] = value
            _emit_trace(options, payload)

        try:
            from anthropic import AsyncAnthropic, Omit  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "anthropic SDK is not installed. Install via `pip install anthropic`"
            ) from e

        default_headers = canonicalize_sdk_headers(resolved.headers or {})
        default_headers = {
            name: value
            for name, value in default_headers.items()
            if name.casefold() != "anthropic-beta"
        }
        default_headers.update(prepared.model_visible_headers_for_transport())

        client = self._client or AsyncAnthropic(  # type: ignore[call-arg]
            api_key="",
            auth_token="",
            base_url=resolved.base_url,
        )
        _debug(
            "client",
            {
                "api": model.api,
                "provider": model.provider_id,
                "endpoint": model.endpoint_id,
                "model": model.id,
            },
        )

        params: dict[str, Any] = prepared.payload_for_transport()
        params["extra_headers"] = {
            "X-Api-Key": Omit(),
            "Authorization": Omit(),
            **default_headers,
        }

        try:
            if getattr(resolved, "mode", "stream") == "complete":
                response = await client.messages.create(**params)
            else:
                response = client.messages.stream(**params)
        except Exception as e:
            _debug("stream_error", {"exceptionType": type(e).__name__})
            yield provider_error_part(e, source=self.api)
            return
        if getattr(resolved, "mode", "stream") == "complete":
            for part in _iter_complete_response_parts(
                response,
                source=self.api,
            ):
                yield part
            return

        stream_ctx = response
        # 启动事件：发出 response_start（若 SDK 提供 id 会在后续 message_start 拿到）
        # 主循环（SDK 为 async context manager）
        active_tool_blocks: dict[int | None, _AnthropicToolStreamState] = {}
        try:
            async with stream_ctx as stream:
                async for event in stream:
                    etype = getattr(event, "type", None)
                    if etype == "message_start":
                        msg = getattr(event, "message", None)
                        rid = getattr(msg, "id", None)
                        if isinstance(rid, str):
                            yield {"type": "response_start", "response_id": rid}
                        usage = getattr(msg, "usage", None)
                        if usage:
                            usage_part = _usage_part_from_anthropic_usage(usage)
                            if usage_part is not None:
                                yield usage_part
                        continue
                    if etype == "content_block_start":
                        cblk = getattr(event, "content_block", None)
                        content_index = _optional_int(getattr(event, "index", None))
                        active_tool_blocks.pop(content_index, None)
                        # text/thinking/tool_use 起始：我们只需开始时打标，增量通过 delta 下发
                        # 目前 RawAssembler 不依赖 *_start 事件，故不强制发送 start，减少噪音
                        if (
                            cblk is not None
                            and getattr(cblk, "type", None) == "tool_use"
                        ):
                            # 记录开始，立刻发出 tool_call_start
                            tid = getattr(cblk, "id", None)
                            tname = getattr(cblk, "name", None)
                            if isinstance(tid, str) and isinstance(tname, str) and tid:
                                new_tool_state = _AnthropicToolStreamState(
                                    id=tid,
                                    name=tname,
                                )
                                active_tool_blocks[content_index] = new_tool_state
                                active_tool_name = new_tool_state.name
                                active_tool_id = new_tool_state.id
                                _debug(
                                    "tool_start",
                                    {
                                        "id": active_tool_id,
                                        "name": active_tool_name,
                                        "args": getattr(cblk, "input", {}),
                                    },
                                )
                                start_part: dict[str, object] = {
                                    "type": "tool_call_start",
                                    "id": tid,
                                    "name": active_tool_name,
                                }
                                if content_index is not None:
                                    start_part["index"] = content_index
                                yield _raw_part(start_part)
                                input_value = getattr(cblk, "input", _MISSING)
                                input_delta = _tool_input_to_json_delta(input_value)
                                if input_delta:
                                    new_tool_state.args_from_start = True
                                    new_tool_state.args_source = "content_block.input"
                                    new_tool_state.arg_chunks = [input_delta]
                                    args_part: dict[str, object] = {
                                        "type": "tool_call_args_delta",
                                        "delta": input_delta,
                                    }
                                    if content_index is not None:
                                        args_part["index"] = content_index
                                    yield _raw_part(args_part)
                        elif (
                            cblk is not None
                            and getattr(cblk, "type", None) == "redacted_thinking"
                        ):
                            signature = getattr(cblk, "data", None)
                            if isinstance(signature, str) and signature:
                                yield {
                                    "type": "redacted_thinking",
                                    "signature": signature,
                                }
                        continue
                    if etype == "content_block_delta":
                        content_index = _optional_int(getattr(event, "index", None))
                        delta = getattr(event, "delta", None)
                        active_tool_state = _get_tool_stream_state(
                            active_tool_blocks, content_index
                        )
                        if (
                            delta is not None
                            and getattr(delta, "type", None) == "text_delta"
                        ):
                            text = getattr(delta, "text", None)
                            if isinstance(text, str) and text:
                                yield {"type": "text_delta", "text": text}
                        elif (
                            delta is not None
                            and getattr(delta, "type", None) == "thinking_delta"
                        ):
                            thinking_text = getattr(delta, "thinking", None)
                            if isinstance(thinking_text, str) and thinking_text:
                                # RawAssembler 期望键名为 text
                                yield {"type": "thinking_delta", "text": thinking_text}
                        elif (
                            delta is not None
                            and getattr(delta, "type", None) == "signature_delta"
                        ):
                            signature = getattr(delta, "signature", None)
                            if isinstance(signature, str) and signature:
                                yield {
                                    "type": "thinking_signature_delta",
                                    "signature": signature,
                                }
                        elif (
                            delta is not None
                            and getattr(delta, "type", None) == "input_json_delta"
                        ):
                            partial = getattr(delta, "partial_json", None)
                            if isinstance(partial, str) and partial:
                                if active_tool_state is None:
                                    active_tool_state = _AnthropicToolStreamState()
                                    active_tool_blocks[content_index] = (
                                        active_tool_state
                                    )
                                active_tool_state.delta_chars += len(partial)
                                if not active_tool_state.args_from_start:
                                    active_tool_state.args_source = "input_json_delta"
                                    active_tool_state.arg_chunks.append(partial)
                                    args_part = {
                                        "type": "tool_call_args_delta",
                                        "delta": partial,
                                    }
                                    if content_index is not None:
                                        args_part["index"] = content_index
                                    yield _raw_part(args_part)
                        continue
                    if etype == "content_block_stop":
                        content_index = _optional_int(getattr(event, "index", None))
                        # 工具块结束：发出 tool_call_done（不带 payload，RawAssembler 内部汇总参数）
                        active_tool_state = _pop_tool_stream_state(
                            active_tool_blocks, content_index
                        )
                        if active_tool_state is not None:
                            tool_trace = {
                                "id": active_tool_state.id,
                                "name": active_tool_state.name,
                                "args_source": active_tool_state.args_source,
                                "delta_chars": active_tool_state.delta_chars,
                                "args": _summarize_tool_args_json(
                                    "".join(active_tool_state.arg_chunks)
                                ),
                            }
                            _debug(
                                "tool_empty_args"
                                if active_tool_state.args_source == "none"
                                else "tool_done",
                                tool_trace,
                            )
                            done_part: dict[str, object] = {"type": "tool_call_done"}
                            if content_index is not None:
                                done_part["index"] = content_index
                            yield _raw_part(done_part)
                        continue
                    if etype == "message_delta":
                        delta = getattr(event, "delta", None)
                        stop_reason = getattr(delta, "stop_reason", None)
                        if isinstance(stop_reason, str):
                            mapped = _map_stop_reason(stop_reason)
                            yield {"type": "stop_reason", "stop_reason": mapped}
                            if mapped == "error":
                                yield provider_error_part_from_raw(
                                    f"provider stop_reason={stop_reason}",
                                    code=stop_reason,
                                    source=self.api,
                                )
                                return
                        usage = getattr(event, "usage", None)
                        if usage:
                            usage_part = _usage_part_from_anthropic_usage(usage)
                            if usage_part is not None:
                                yield usage_part
                        continue
                    if etype == "message_stop":
                        yield {"type": "response_done"}
                        return
                    if etype == "error":
                        err = getattr(event, "error", None)
                        msg = getattr(err, "message", None) if err is not None else None
                        code = getattr(err, "type", None) if err is not None else None
                        yield provider_error_part_from_raw(
                            msg or "Unknown error",
                            code=code,
                            source=self.api,
                        )
                        return
            yield provider_error_part(
                AIProviderProtocolError(
                    "provider stream ended before a terminal response event",
                    source=self.api,
                ),
                source=self.api,
            )
        except Exception as e:
            _debug("stream_iter_error", {"exceptionType": type(e).__name__})
            yield provider_error_part(e, source=self.api)


def _map_stop_reason(reason: str) -> str:
    if reason == "max_tokens":
        return "length"
    if reason in {"end_turn", "stop_sequence", "pause_turn"}:
        return "stop"
    if reason == "tool_use":
        return "toolUse"
    if reason in {"refusal", "sensitive"}:
        return "error"
    raise ValueError(f"Unhandled stop reason: {reason}")


def _iter_complete_response_parts(
    response: object,
    *,
    source: str,
) -> Iterator[RawPart]:
    response_id = getattr(response, "id", None)
    if isinstance(response_id, str) and response_id:
        yield {"type": "response_start", "response_id": response_id}

    usage = getattr(response, "usage", None)
    if usage is not None:
        usage_part = _usage_part_from_anthropic_usage(usage)
        if usage_part is not None:
            yield usage_part

    content = getattr(response, "content", None)
    if isinstance(content, list):
        for index, block in enumerate(content):
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text = getattr(block, "text", None)
                if isinstance(text, str) and text:
                    yield {"type": "text_delta", "text": text}
            elif block_type == "thinking":
                thinking = getattr(block, "thinking", None)
                if isinstance(thinking, str) and thinking:
                    yield {"type": "thinking_delta", "text": thinking}
                signature = getattr(block, "signature", None)
                if isinstance(signature, str) and signature:
                    yield {
                        "type": "thinking_signature_delta",
                        "signature": signature,
                    }
            elif block_type == "redacted_thinking":
                signature = getattr(block, "data", None)
                if isinstance(signature, str) and signature:
                    yield {"type": "redacted_thinking", "signature": signature}
            elif block_type == "tool_use":
                yield from _iter_complete_tool_call_parts(
                    block,
                    index=index,
                )

    stop_reason = getattr(response, "stop_reason", None)
    if isinstance(stop_reason, str):
        mapped = _map_stop_reason(stop_reason)
        yield {"type": "stop_reason", "stop_reason": mapped}
        if mapped == "error":
            yield provider_error_part_from_raw(
                f"provider stop_reason={stop_reason}",
                code=stop_reason,
                source=source,
            )
            return
    yield {"type": "response_done"}


def _iter_complete_tool_call_parts(
    block: object,
    *,
    index: int,
) -> Iterator[RawPart]:
    tool_call_id = getattr(block, "id", None)
    if not isinstance(tool_call_id, str) or not tool_call_id:
        tool_call_id = f"tool_call_{index}"
    raw_name = getattr(block, "name", "")
    name = raw_name if isinstance(raw_name, str) else ""
    yield _raw_part(
        {
            "type": "tool_call_start",
            "id": tool_call_id,
            "name": name,
            "index": index,
        }
    )
    input_value = getattr(block, "input", _MISSING)
    input_delta = _tool_input_to_json_delta(input_value)
    if input_delta:
        yield _raw_part(
            {
                "type": "tool_call_args_delta",
                "tool_call_id": tool_call_id,
                "delta": input_delta,
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


def _usage_part_from_anthropic_usage(usage: object) -> UsageDeltaPart | None:
    part: dict[str, object] = {"type": "usage_delta"}
    for source_field, target_field in (
        ("input_tokens", "input"),
        ("output_tokens", "output"),
        ("cache_read_input_tokens", "cache_read"),
        ("cache_creation_input_tokens", "cache_write"),
        ("total_tokens", "total_tokens"),
    ):
        value = getattr(usage, source_field, None)
        if value is not None:
            part[target_field] = value
    if len(part) == 1:
        return None
    return cast(UsageDeltaPart, part)


def _request_adapter_config(request: ProviderRequest) -> AnthropicMessagesConfig:
    adapter_config = request.model.adapter
    if isinstance(adapter_config, AnthropicMessagesConfig):
        return adapter_config
    return AnthropicMessagesConfig()


def _raw_part(part: dict[str, object]) -> RawPart:
    return cast(RawPart, part)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None
