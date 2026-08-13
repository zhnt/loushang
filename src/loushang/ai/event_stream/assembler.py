from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from time import time
from typing import cast

from loushang.ai.event_stream.raw_parts import (
    AbortedPart,
    ImagePartRaw,
    RawPart,
    RedactedThinkingPart,
    ResponseDonePart,
    ResponseErrorPart,
    ResponseStartPart,
    StopReasonPart,
    TextDeltaPart,
    TextSignatureDeltaPart,
    ThinkingDeltaPart,
    ThinkingSignatureDeltaPart,
    ToolCallArgsDeltaPart,
    ToolCallDonePart,
    ToolCallStartPart,
    ToolCallThoughtSignaturePart,
    UsageCostMultiplierPart,
    UsageDeltaPart,
)
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.pricing import calculate_usage_cost
from loushang.ai.provider.errors import (
    is_http_status_code,
    provider_error_info_from_raw,
)
from loushang.ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    DoneEvent,
    ErrorEvent,
    ImageEndEvent,
    ImagePart,
    ImageStartEvent,
    StartEvent,
    StopReason,
    TextDeltaEvent,
    TextEndEvent,
    TextPart,
    TextStartEvent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingPart,
    ThinkingStartEvent,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    Usage,
)
from loushang.ai.utils.json_parse import parse_streaming_json


@dataclass
class _ToolCallBuffer:
    id: str
    name: str
    index: int | None
    args_chunks: list[str] = field(default_factory=list)
    thought_signature: str | None = None


class RawAssembler:
    def __init__(
        self,
        *,
        stream: AssistantMessageEventStream,
        api: str,
        provider: str,
        endpoint: str,
        model: str,
        pricing=None,
        clock: Callable[[], float] = time,
    ) -> None:
        self._stream = stream
        self._api = api
        self._provider = provider
        self._endpoint = endpoint
        self._model = model
        self._pricing = pricing
        self._clock = clock
        self._response_id: str | None = None
        self._text_chunks: list[str] = []
        self._text_signature: str | None = None
        self._thinking_chunks: list[str] = []
        self._thinking_signature_chunks: list[str] = []
        self._thinking_redacted = False
        self._images: list[ImagePart] = []
        self._tool_calls: list[ToolCall] = []
        self._tool_calls_by_id: dict[str, ToolCall] = {}
        self._active_tool_call_buffers_by_id: dict[str, _ToolCallBuffer] = {}
        self._active_tool_call_buffers_by_index: dict[int, _ToolCallBuffer] = {}
        self._content_order: list[tuple[str, str | None]] = []
        self._stop_reason = "stop"
        self._usage = Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=None,
        )
        self._usage_cost_multiplier = 1.0
        self._final_message: AssistantMessage | None = None
        self._started = False
        self._text_started = False
        self._thinking_started = False
        self._queued_events: list[AssistantMessageEvent] | None = None
        self._terminal_emitted = False

    def feed(self, part: RawPart) -> None:
        if self._terminal_emitted:
            return
        part_type = part["type"]

        if part_type == "response_start":
            response_part = cast(ResponseStartPart, part)
            self._response_id = response_part["response_id"]
            self._ensure_started()
            return

        if part_type == "text_delta":
            text_part = cast(TextDeltaPart, part)
            content_index = self._ensure_text_started()
            self._text_chunks.append(text_part["text"])
            self._push_event(
                cast(
                    TextDeltaEvent,
                    {
                        "type": "text_delta",
                        "content_index": content_index,
                        "delta": text_part["text"],
                        "partial": self._build_partial_message(),
                    },
                )
            )
            return

        if part_type == "text_signature_delta":
            text_signature_part = cast(TextSignatureDeltaPart, part)
            self._text_signature = text_signature_part["signature"]
            return

        if part_type == "thinking_delta":
            thinking_part = cast(ThinkingDeltaPart, part)
            content_index = self._ensure_thinking_started()
            self._thinking_chunks.append(thinking_part["text"])
            self._push_event(
                cast(
                    ThinkingDeltaEvent,
                    {
                        "type": "thinking_delta",
                        "content_index": content_index,
                        "delta": thinking_part["text"],
                        "partial": self._build_partial_message(),
                    },
                )
            )
            return

        if part_type == "thinking_signature_delta":
            thinking_signature_part = cast(ThinkingSignatureDeltaPart, part)
            self._ensure_thinking_started()
            self._thinking_signature_chunks.append(thinking_signature_part["signature"])
            return

        if part_type == "redacted_thinking":
            redacted_part = cast(RedactedThinkingPart, part)
            self._ensure_thinking_started()
            if not self._thinking_chunks:
                self._thinking_chunks.append("[Reasoning redacted]")
            self._thinking_redacted = True
            self._thinking_signature_chunks = [redacted_part["signature"]]
            return

        if part_type == "tool_call_start":
            tool_call_start_part = cast(ToolCallStartPart, part)
            self._ensure_started()
            index = _optional_int(tool_call_start_part.get("index"))
            start_buffer = _ToolCallBuffer(
                id=tool_call_start_part["id"],
                name=tool_call_start_part["name"],
                index=index,
            )
            self._active_tool_call_buffers_by_id[start_buffer.id] = start_buffer
            if index is not None:
                self._active_tool_call_buffers_by_index[index] = start_buffer
            content_index = self._ensure_content_block("tool", start_buffer.id)
            self._push_event(
                cast(
                    ToolCallStartEvent,
                    {
                        "type": "toolcall_start",
                        "content_index": content_index,
                        "partial": self._build_partial_message(),
                    },
                )
            )
            return

        if part_type == "tool_call_args_delta":
            tool_call_args_part = cast(ToolCallArgsDeltaPart, part)
            delta_buffer = self._resolve_active_tool_call_buffer(tool_call_args_part)
            if delta_buffer is None:
                raise RuntimeError("tool call delta received before tool call start")
            delta_buffer.args_chunks.append(tool_call_args_part["delta"])
            self._push_event(
                cast(
                    ToolCallDeltaEvent,
                    {
                        "type": "toolcall_delta",
                        "content_index": self._toolcall_content_index(delta_buffer),
                        "delta": tool_call_args_part["delta"],
                        "partial": self._build_partial_message(),
                    },
                )
            )
            return

        if part_type == "tool_call_done":
            tool_call_done_part = cast(ToolCallDonePart, part)
            done_buffer = self._resolve_active_tool_call_buffer(tool_call_done_part)
            if done_buffer is None:
                raise RuntimeError("tool call done received before tool call start")
            tool_call = self._build_tool_call(done_buffer)
            self._push_event(
                cast(
                    ToolCallEndEvent,
                    {
                        "type": "toolcall_end",
                        "content_index": self._toolcall_content_index(done_buffer),
                        "tool_call": tool_call,
                        "partial": self._build_partial_message(),
                    },
                )
            )
            self._tool_calls.append(tool_call)
            self._tool_calls_by_id[tool_call.id] = tool_call
            self._remove_active_tool_call_buffer(done_buffer)
            return

        if part_type == "tool_call_thought_signature":
            tool_call_signature_part = cast(ToolCallThoughtSignaturePart, part)
            signature_buffer = self._active_tool_call_buffers_by_id.get(
                tool_call_signature_part["tool_call_id"]
            )
            if signature_buffer is not None:
                signature_buffer.thought_signature = tool_call_signature_part[
                    "thought_signature"
                ]
                return
            for index, tool_call in enumerate(self._tool_calls):
                if tool_call.id == tool_call_signature_part["tool_call_id"]:
                    updated_tool_call = ToolCall(
                        type=tool_call.type,
                        id=tool_call.id,
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                        thought_signature=tool_call_signature_part["thought_signature"],
                    )
                    self._tool_calls[index] = updated_tool_call
                    self._tool_calls_by_id[updated_tool_call.id] = updated_tool_call
                    return
            return

        if part_type == "image_part":
            image_part = cast(ImagePartRaw, part)
            self._ensure_started()
            image = ImagePart(
                type="image",
                data=image_part["data"],
                mime_type=image_part["mime_type"],
            )
            self._images.append(image)
            content_index = self._ensure_content_block(
                "image", str(len(self._images) - 1)
            )
            partial = self._build_partial_message()
            self._push_event(
                cast(
                    ImageStartEvent,
                    {
                        "type": "image_start",
                        "content_index": content_index,
                        "partial": partial,
                    },
                )
            )
            self._push_event(
                cast(
                    ImageEndEvent,
                    {
                        "type": "image_end",
                        "content_index": content_index,
                        "image": image,
                        "partial": partial,
                    },
                )
            )
            return

        if part_type == "usage_delta":
            usage_part = cast(UsageDeltaPart, part)
            input_tokens = usage_part.get("input", self._usage.input)
            output_tokens = usage_part.get("output", self._usage.output)
            cache_read_tokens = usage_part.get("cache_read", self._usage.cache_read)
            cache_write_tokens = usage_part.get("cache_write", self._usage.cache_write)
            derived_total_tokens = _derive_total_tokens(
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_write_tokens,
            )
            total_tokens = usage_part.get("total_tokens", 0)
            if "total_tokens" not in usage_part or total_tokens <= 0:
                total_tokens = derived_total_tokens
            else:
                total_tokens = max(total_tokens, derived_total_tokens)
            self._usage = Usage(
                input=input_tokens,
                output=output_tokens,
                cache_read=cache_read_tokens,
                cache_write=cache_write_tokens,
                total_tokens=total_tokens,
                cost=self._usage.cost,
            )
            return

        if part_type == "usage_cost_multiplier":
            usage_multiplier_part = cast(UsageCostMultiplierPart, part)
            self._usage_cost_multiplier = float(usage_multiplier_part["multiplier"])
            return

        if part_type == "stop_reason":
            stop_reason_part = cast(StopReasonPart, part)
            self._stop_reason = stop_reason_part["stop_reason"]
            return

        if part_type == "response_done":
            cast(ResponseDonePart, part)
            self._finalize_usage_cost()
            for kind, _key in self._content_order:
                if kind == "text" and self._text_started:
                    self._push_event(
                        cast(
                            TextEndEvent,
                            {
                                "type": "text_end",
                                "content_index": self._text_content_index(),
                                "content": "".join(self._text_chunks),
                                "partial": self._build_partial_message(),
                            },
                        )
                    )
                elif kind == "thinking" and self._thinking_started:
                    self._push_event(
                        cast(
                            ThinkingEndEvent,
                            {
                                "type": "thinking_end",
                                "content_index": self._thinking_content_index(),
                                "content": "".join(self._thinking_chunks),
                                "partial": self._build_partial_message(),
                            },
                        )
                    )
            message = self._build_message(
                stop_reason=self._stop_reason, error_message=None
            )
            self._final_message = message
            self._push_event(
                cast(
                    DoneEvent,
                    {
                        "type": "done",
                        "reason": _done_reason(self._stop_reason),
                        "message": message,
                    },
                )
            )
            self._terminal_emitted = True
            return

        if part_type == "aborted":
            cast(AbortedPart, part)
            message = self._build_message(
                stop_reason="aborted", error_message="aborted"
            )
            self._final_message = message
            self._push_event(
                cast(
                    ErrorEvent,
                    {"type": "error", "reason": "aborted", "error": message},
                )
            )
            self._terminal_emitted = True
            return

        if part_type == "response_error":
            response_error_part = cast(ResponseErrorPart, part)
            error_info = provider_error_info_from_raw(
                response_error_part,
                source=self._api,
                provider=self._provider,
                endpoint=self._endpoint,
                model=self._model,
            )
            message = self._build_message(
                stop_reason="error",
                error_message=error_info.message,
            )
            error_event: ErrorEvent = {
                "type": "error",
                "reason": "error",
                "error": message,
                "error_info": error_info.to_dict(),
            }
            code = _http_status_code(response_error_part.get("code"))
            if code is not None:
                error_event["code"] = code
            self._final_message = message
            self._push_event(error_event)
            self._terminal_emitted = True
            return

        raise ValueError(f"Unsupported raw part type: {part_type}")

    async def emit(self, part: RawPart) -> None:
        if self._queued_events is not None:
            raise RuntimeError("Raw assembler async emit is already active")
        self._queued_events = []
        try:
            self.feed(part)
            queued_events = self._queued_events
        finally:
            self._queued_events = None
        if queued_events is None:
            return
        for event in queued_events:
            await self._stream.emit(event)

    def _push_event(self, event: AssistantMessageEvent) -> None:
        if self._queued_events is not None:
            self._queued_events.append(event)
            return
        self._stream.push(event)

    def _ensure_started(self) -> None:
        if self._started:
            return
        self._push_event(
            cast(
                StartEvent,
                {"type": "start", "partial": self._build_partial_message()},
            )
        )
        self._started = True

    def _ensure_text_started(self) -> int:
        self._ensure_started()
        if not self._text_started:
            self._text_started = True
            content_index = self._ensure_content_block("text")
            self._push_event(
                cast(
                    TextStartEvent,
                    {
                        "type": "text_start",
                        "content_index": content_index,
                        "partial": self._build_partial_message(),
                    },
                )
            )
            return content_index
        return self._text_content_index()

    def _ensure_thinking_started(self) -> int:
        self._ensure_started()
        if not self._thinking_started:
            self._thinking_started = True
            content_index = self._ensure_content_block("thinking")
            self._push_event(
                cast(
                    ThinkingStartEvent,
                    {
                        "type": "thinking_start",
                        "content_index": content_index,
                        "partial": self._build_partial_message(),
                    },
                )
            )
            return content_index
        return self._thinking_content_index()

    def result_nowait(self) -> AssistantMessage:
        if self._final_message is None:
            raise RuntimeError("Raw assembler has not produced a final message yet")
        return self._final_message

    def _finalize_usage_cost(self) -> None:
        if self._pricing is None:
            return
        with suppress(Exception):
            computed = calculate_usage_cost(
                self._pricing,
                self._usage,
                multiplier=self._usage_cost_multiplier,
            )
            if computed is None:
                return
            self._usage = Usage(
                input=self._usage.input,
                output=self._usage.output,
                cache_read=self._usage.cache_read,
                cache_write=self._usage.cache_write,
                total_tokens=self._usage.total_tokens,
                cost=computed,
            )

    def _build_message(
        self, *, stop_reason: str, error_message: str | None
    ) -> AssistantMessage:
        return AssistantMessage(
            role="assistant",
            content=self._build_content(),
            api=self._api,
            provider=self._provider,
            endpoint=self._endpoint,
            model=self._model,
            response_id=self._response_id,
            usage=self._usage,
            stop_reason=_assistant_stop_reason(stop_reason),
            error_message=error_message,
            timestamp=self._clock(),
        )

    def _build_partial_message(self) -> AssistantMessage:
        return self._build_message(stop_reason=self._stop_reason, error_message=None)

    def _build_content(self) -> list[TextPart | ThinkingPart | ToolCall | ImagePart]:
        content: list[TextPart | ThinkingPart | ToolCall | ImagePart] = []
        for kind, key in self._content_order:
            if kind == "text" and self._has_text_content():
                content.append(
                    TextPart(
                        type="text",
                        text="".join(self._text_chunks),
                        text_signature=self._text_signature,
                    )
                )
            elif kind == "thinking" and self._has_thinking_content():
                thinking_signature = "".join(self._thinking_signature_chunks) or None
                content.append(
                    ThinkingPart(
                        type="thinking",
                        thinking="".join(self._thinking_chunks),
                        thinking_signature=thinking_signature,
                        redacted=self._thinking_redacted,
                    )
                )
            elif kind == "tool" and key is not None:
                tool_call = self._tool_calls_by_id.get(key)
                if tool_call is not None:
                    content.append(tool_call)
                elif key in self._active_tool_call_buffers_by_id:
                    content.append(
                        self._build_tool_call(self._active_tool_call_buffers_by_id[key])
                    )
            elif kind == "image" and key is not None:
                image_index = int(key)
                if image_index < len(self._images):
                    content.append(self._images[image_index])
        return content

    def _build_tool_call(self, buffer: _ToolCallBuffer) -> ToolCall:
        return ToolCall(
            type="toolCall",
            id=buffer.id,
            name=buffer.name,
            arguments=self._parse_tool_call_arguments(buffer),
            thought_signature=buffer.thought_signature,
        )

    def _parse_tool_call_arguments(self, buffer: _ToolCallBuffer) -> dict:
        raw = "".join(buffer.args_chunks)
        return parse_streaming_json(raw)

    def _resolve_active_tool_call_buffer(
        self, part: ToolCallArgsDeltaPart | ToolCallDonePart
    ) -> _ToolCallBuffer | None:
        tool_call_id = _optional_str(
            part.get("tool_call_id") or cast(Mapping[str, object], part).get("id")
        )
        if tool_call_id is not None:
            buffer = self._active_tool_call_buffers_by_id.get(tool_call_id)
            if buffer is not None:
                return buffer
        index = _optional_int(part.get("index"))
        if index is not None:
            buffer = self._active_tool_call_buffers_by_index.get(index)
            if buffer is not None:
                return buffer
        active_buffers = list(self._active_tool_call_buffers_by_id.values())
        if len(active_buffers) == 1:
            return active_buffers[0]
        return None

    def _remove_active_tool_call_buffer(self, buffer: _ToolCallBuffer) -> None:
        self._active_tool_call_buffers_by_id.pop(buffer.id, None)
        if (
            buffer.index is not None
            and self._active_tool_call_buffers_by_index.get(buffer.index) is buffer
        ):
            self._active_tool_call_buffers_by_index.pop(buffer.index, None)

    def _toolcall_content_index(self, buffer: _ToolCallBuffer) -> int:
        return self._content_block_index("tool", buffer.id)

    def _text_content_index(self) -> int:
        return self._content_block_index("text")

    def _thinking_content_index(self) -> int:
        return self._content_block_index("thinking")

    def _image_content_index(self) -> int:
        return len(self._build_content()) - 1

    def _ensure_content_block(self, kind: str, key: str | None = None) -> int:
        marker = (kind, key)
        if marker not in self._content_order:
            self._content_order.append(marker)
        return self._content_block_index(kind, key)

    def _content_block_index(self, kind: str, key: str | None = None) -> int:
        marker = (kind, key)
        try:
            return self._content_order.index(marker)
        except ValueError as exc:
            raise RuntimeError(f"content block has not started: {kind}") from exc

    def _has_text_content(self) -> bool:
        return bool(self._text_started or self._text_chunks or self._text_signature)

    def _has_thinking_content(self) -> bool:
        return bool(
            self._thinking_started
            or self._thinking_chunks
            or self._thinking_signature_chunks
            or self._thinking_redacted
        )


def _http_status_code(value: object) -> int | None:
    if is_http_status_code(value):
        assert isinstance(value, int)
        return value
    return None


def _done_reason(stop_reason: str) -> str:
    if stop_reason in {"stop", "length", "toolUse"}:
        return stop_reason
    return "stop"


def _assistant_stop_reason(stop_reason: str) -> StopReason:
    if stop_reason in {"stop", "length", "toolUse", "error", "aborted"}:
        return cast(StopReason, stop_reason)
    return "stop"


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _derive_total_tokens(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> int:
    return input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
