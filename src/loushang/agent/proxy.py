from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from math import isfinite
from typing import Any

from loushang.agent.types import ProxyAssistantMessageEvent, ProxyStreamOptions
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Model
from loushang.ai.model.registry import resolve_model_api
from loushang.ai.options import get_max_output_tokens
from loushang.ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    ImagePart,
    TextPart,
    ThinkingPart,
    ToolCall,
    Usage,
    UsageCost,
)


@dataclass
class _MutablePartialMessage:
    role: str
    api: str
    provider: str
    endpoint: str
    model: str
    timestamp: float
    content: list[TextPart | ThinkingPart | ToolCall | ImagePart] = field(
        default_factory=list
    )
    stop_reason: str = "stop"
    response_id: str | None = None
    usage: Usage = field(
        default_factory=lambda: Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=None,
        )
    )
    error_message: str | None = None
    _toolcall_partial_json: dict[int, str] = field(default_factory=dict)

    def snapshot(self) -> AssistantMessage:
        return AssistantMessage(
            role="assistant",
            content=list(self.content),
            api=self.api,
            provider=self.provider,
            endpoint=self.endpoint,
            model=self.model,
            response_id=self.response_id,
            usage=self.usage,
            stop_reason=self.stop_reason,  # type: ignore[arg-type]
            error_message=self.error_message,
            timestamp=self.timestamp,
        )


def _create_initial_partial_message(model: Model) -> _MutablePartialMessage:
    return _MutablePartialMessage(
        role="assistant",
        api=resolve_model_api(model),
        provider=model.provider_id,
        endpoint=model.endpoint_id,
        model=model.id,
        timestamp=time.time() * 1000,
    )


def stream_proxy(
    model: Model,
    context: Context,
    options: ProxyStreamOptions,
    *,
    client: Any | None = None,
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()
    partial = _create_initial_partial_message(model)

    async def _run() -> None:
        owned_client = None
        current_task = asyncio.current_task()

        def _cancel_current_task() -> None:
            if current_task is not None and not current_task.done():
                current_task.cancel()

        remove_abort_listener = _attach_abort_listener(
            options.signal,
            _cancel_current_task,
        )
        try:
            if getattr(options.signal, "aborted", False):
                raise RuntimeError("Request aborted by user")
            stream_client = client
            if stream_client is None:
                try:
                    import httpx
                except ImportError as exc:  # pragma: no cover
                    raise RuntimeError(
                        "httpx is required for proxy streaming. Install via `pip install httpx`"
                    ) from exc
                owned_client = httpx.AsyncClient(base_url=options.proxy_url)
                stream_client = owned_client

            async with stream_client.stream(
                "POST",
                "/api/stream",
                json={
                    "model": model,
                    "context": context,
                    "options": {
                        "temperature": options.temperature,
                        "max_tokens": get_max_output_tokens(options),
                        "reasoning": options.reasoning,
                    },
                },
                headers={
                    "Authorization": f"Bearer {options.auth_token}",
                    "Content-Type": "application/json",
                },
            ) as response:
                if not response.is_success:
                    raise RuntimeError(await _proxy_error_message(response))

                async for line in response.aiter_lines():
                    if getattr(options.signal, "aborted", False):
                        raise RuntimeError("Request aborted by user")
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if not data:
                        continue
                    proxy_event = json.loads(data)
                    event = _process_proxy_event(proxy_event, partial)
                    if event is not None:
                        await stream.emit(event)
                    if _is_terminal_proxy_event(proxy_event):
                        return

                if getattr(options.signal, "aborted", False):
                    raise RuntimeError("Request aborted by user")

                if partial.stop_reason not in {"error", "aborted"}:
                    stream.end()
        except asyncio.CancelledError:
            if getattr(options.signal, "aborted", False):
                partial.stop_reason = "aborted"
                partial.error_message = "Request aborted by user"
                await stream.emit(
                    {
                        "type": "error",
                        "reason": "aborted",
                        "error": partial.snapshot(),
                    }
                )
                return
            raise
        except Exception as error:
            reason = "aborted" if getattr(options.signal, "aborted", False) else "error"
            partial.stop_reason = reason
            partial.error_message = str(error)
            await stream.emit(
                {
                    "type": "error",
                    "reason": reason,
                    "error": partial.snapshot(),
                }
            )
        finally:
            remove_abort_listener()
            if owned_client is not None:
                await owned_client.aclose()

    stream.attach_task(asyncio.create_task(_run()))
    return stream


async def _proxy_error_message(response: Any) -> str:
    status_code = getattr(response, "status_code", "unknown")
    status_text = getattr(response, "reason_phrase", "")
    message = f"Proxy error: {status_code} {status_text}".strip()
    try:
        payload = await response.json()
    except Exception:
        return message
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return f"Proxy error: {payload['error']}"
    return message


def _process_proxy_event(
    proxy_event: ProxyAssistantMessageEvent | dict[str, Any],
    partial: _MutablePartialMessage,
) -> AssistantMessageEvent | None:
    event_type = proxy_event["type"]

    if event_type == "start":
        return {"type": "start", "partial": partial.snapshot()}

    if event_type == "text_start":
        content_index = proxy_event["content_index"]
        _set_content(partial, content_index, TextPart(type="text", text=""))
        return {
            "type": "text_start",
            "content_index": content_index,
            "partial": partial.snapshot(),
        }

    if event_type == "text_delta":
        content_index = proxy_event["content_index"]
        content = _require_content_type(partial, content_index, TextPart, "text_delta")
        updated = replace(content, text=content.text + proxy_event["delta"])
        _set_content(partial, content_index, updated)
        return {
            "type": "text_delta",
            "content_index": content_index,
            "delta": proxy_event["delta"],
            "partial": partial.snapshot(),
        }

    if event_type == "text_end":
        content_index = proxy_event["content_index"]
        content = _require_content_type(partial, content_index, TextPart, "text_end")
        updated = replace(content, text_signature=proxy_event.get("content_signature"))
        _set_content(partial, content_index, updated)
        return {
            "type": "text_end",
            "content_index": content_index,
            "content": updated.text,
            "partial": partial.snapshot(),
        }

    if event_type == "thinking_start":
        content_index = proxy_event["content_index"]
        _set_content(partial, content_index, ThinkingPart(type="thinking", thinking=""))
        return {
            "type": "thinking_start",
            "content_index": content_index,
            "partial": partial.snapshot(),
        }

    if event_type == "thinking_delta":
        content_index = proxy_event["content_index"]
        content = _require_content_type(
            partial, content_index, ThinkingPart, "thinking_delta"
        )
        updated = replace(content, thinking=content.thinking + proxy_event["delta"])
        _set_content(partial, content_index, updated)
        return {
            "type": "thinking_delta",
            "content_index": content_index,
            "delta": proxy_event["delta"],
            "partial": partial.snapshot(),
        }

    if event_type == "thinking_end":
        content_index = proxy_event["content_index"]
        content = _require_content_type(
            partial, content_index, ThinkingPart, "thinking_end"
        )
        updated = replace(
            content, thinking_signature=proxy_event.get("content_signature")
        )
        _set_content(partial, content_index, updated)
        return {
            "type": "thinking_end",
            "content_index": content_index,
            "content": updated.thinking,
            "partial": partial.snapshot(),
        }

    if event_type == "toolcall_start":
        content_index = proxy_event["content_index"]
        partial._toolcall_partial_json[content_index] = ""
        _set_content(
            partial,
            content_index,
            ToolCall(
                type="toolCall",
                id=proxy_event["id"],
                name=proxy_event["tool_name"],
                arguments={},
            ),
        )
        return {
            "type": "toolcall_start",
            "content_index": content_index,
            "partial": partial.snapshot(),
        }

    if event_type == "toolcall_delta":
        content_index = proxy_event["content_index"]
        content = _require_content_type(
            partial, content_index, ToolCall, "toolcall_delta"
        )
        partial_json = (
            partial._toolcall_partial_json.get(content_index, "") + proxy_event["delta"]
        )
        partial._toolcall_partial_json[content_index] = partial_json
        arguments = _parse_streaming_json(partial_json) or content.arguments
        _set_content(partial, content_index, replace(content, arguments=arguments))
        return {
            "type": "toolcall_delta",
            "content_index": content_index,
            "delta": proxy_event["delta"],
            "partial": partial.snapshot(),
        }

    if event_type == "toolcall_end":
        content_index = proxy_event["content_index"]
        content = _require_content_type(
            partial, content_index, ToolCall, "toolcall_end"
        )
        full_arguments = (
            _parse_streaming_json(partial._toolcall_partial_json.get(content_index, ""))
            or content.arguments
        )
        final_call = replace(content, arguments=full_arguments)
        _set_content(partial, content_index, final_call)
        partial._toolcall_partial_json.pop(content_index, None)
        return {
            "type": "toolcall_end",
            "content_index": content_index,
            "tool_call": final_call,
            "partial": partial.snapshot(),
        }

    if event_type == "done":
        partial.stop_reason = proxy_event["reason"]
        partial.usage = _usage_from_proxy_value(proxy_event["usage"])
        return {
            "type": "done",
            "reason": proxy_event["reason"],
            "message": partial.snapshot(),
        }

    if event_type == "error":
        partial.stop_reason = proxy_event["reason"]
        partial.usage = _usage_from_proxy_value(proxy_event["usage"])
        partial.error_message = proxy_event.get("error_message")
        return {
            "type": "error",
            "reason": proxy_event["reason"],
            "error": partial.snapshot(),
        }

    return None


def _usage_from_proxy_value(value: object) -> Usage:
    if isinstance(value, Usage):
        return value if value.cost else replace(value, cost=None)
    if isinstance(value, dict):
        return Usage(
            input=_int_value(value.get("input")),
            output=_int_value(value.get("output")),
            cache_read=_int_value(value.get("cache_read", value.get("cacheRead"))),
            cache_write=_int_value(value.get("cache_write", value.get("cacheWrite"))),
            total_tokens=_int_value(
                value.get("total_tokens", value.get("totalTokens"))
            ),
            cost=_usage_cost_from_proxy_value(value.get("cost")),
        )
    return Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost=None
    )


def _usage_cost_from_proxy_value(value: object) -> UsageCost | None:
    if not isinstance(value, Mapping):
        return None
    input_cost = _cost_number(value, "input")
    output_cost = _cost_number(value, "output")
    cache_read = _cost_number(value, "cacheRead", "cache_read")
    cache_write = _cost_number(value, "cacheWrite", "cache_write")
    total = _cost_number(value, "total")
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


def _int_value(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _attach_abort_listener(
    signal: object | None,
    on_abort: Callable[[], None],
):
    if signal is None:
        return lambda: None

    add_event_listener = getattr(signal, "addEventListener", None)
    remove_event_listener = getattr(signal, "removeEventListener", None)
    if callable(add_event_listener) and callable(remove_event_listener):

        def _on_abort(*_args: object) -> None:
            on_abort()

        add_event_listener("abort", _on_abort)
        return lambda: remove_event_listener("abort", _on_abort)

    add_event_listener = getattr(signal, "add_event_listener", None)
    remove_event_listener = getattr(signal, "remove_event_listener", None)
    if callable(add_event_listener) and callable(remove_event_listener):

        def _on_abort(*_args: object) -> None:
            on_abort()

        add_event_listener("abort", _on_abort)
        return lambda: remove_event_listener("abort", _on_abort)

    return lambda: None


def _set_content(
    partial: _MutablePartialMessage,
    index: int,
    content: TextPart | ThinkingPart | ToolCall | ImagePart,
) -> None:
    while len(partial.content) <= index:
        partial.content.append(TextPart(type="text", text=""))
    partial.content[index] = content


def _require_content_type(
    partial: _MutablePartialMessage, index: int, expected_type: type, event_name: str
):
    try:
        content = partial.content[index]
    except IndexError as exc:
        raise ValueError(
            f"Received {event_name} for missing content index {index}"
        ) from exc
    if not isinstance(content, expected_type):
        raise ValueError(
            f"Received {event_name} for unexpected content type {type(content).__name__}"
        )
    return content


def _parse_streaming_json(value: str) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_terminal_proxy_event(
    proxy_event: ProxyAssistantMessageEvent | dict[str, Any],
) -> bool:
    return proxy_event["type"] in {"done", "error"}


__all__ = ["stream_proxy"]
