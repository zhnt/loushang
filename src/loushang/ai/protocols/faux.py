from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.options import is_reasoning_requested
from loushang.ai.provider import ProviderRequest
from loushang.ai.types import TextPart, ToolResultMessage


class FauxAdapter:
    api = "anthropic-messages"

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        options = request.options
        normalized = request.context
        yield {"type": "response_start", "response_id": "faux-response"}
        tool_result_text = self._extract_tool_result_text(normalized.messages)
        if is_reasoning_requested(options):
            yield {"type": "thinking_delta", "text": "reasoning trace"}
        if tool_result_text is not None:
            yield {
                "type": "text_delta",
                "text": f"faux saw tool result: {tool_result_text}",
            }
        else:
            yield {"type": "text_delta", "text": "mock hello from faux provider"}

        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}

    def _extract_tool_result_text(self, messages: Sequence[object]) -> str | None:
        for message in reversed(messages):
            if isinstance(message, ToolResultMessage):
                text_parts = [
                    part.text for part in message.content if isinstance(part, TextPart)
                ]
                if text_parts:
                    return "\n".join(text_parts)
                return "<non-text-tool-result>"
        return None
