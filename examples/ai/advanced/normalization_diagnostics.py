"""Inspect context normalization diagnostics.

This advanced example is offline. It builds a provider-specific assistant
message, projects it to another provider API, and prints the stable diagnostics
emitted for repairs, downgrades, and signature removal.
"""

from __future__ import annotations

import json

from loushang.ai import (
    AssistantMessage,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    Usage,
)
from loushang.ai.context import normalize_context_result
from loushang.ai.model import load_builtin_model_registry


def inspect_normalization_diagnostics() -> dict[str, object]:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ThinkingPart(
                type="thinking",
                thinking="private reasoning",
                thinking_signature="thinking-sig",
            ),
            TextPart(type="text", text="answer", text_signature="text-sig"),
            ToolCall(
                type="toolCall",
                id="call:1",
                name="calc",
                arguments={"x": 1},
                thought_signature="thought-sig",
            ),
        ],
        api="openai-responses",
        provider="openai",
        endpoint="openai-responses",
        model="gpt-test",
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=None,
        ),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )
    result = normalize_context_result(
        {"messages": [assistant]},
        model=load_builtin_model_registry().get_model(
            "anthropic",
            "anthropic-messages",
            "claude-sonnet-5",
        ),
        pairing_mode="repair",
    )
    return {
        "messageRoles": [
            getattr(message, "role", None) for message in result.context.messages
        ],
        "normalizedMessages": [
            _message_summary(message) for message in result.context.messages
        ],
        "diagnostics": [
            {
                "code": diagnostic.code,
                "path": diagnostic.path,
                "level": diagnostic.level,
            }
            for diagnostic in result.diagnostics
        ],
    }


def _message_summary(message: object) -> dict[str, object]:
    if isinstance(message, AssistantMessage):
        return {
            "role": message.role,
            "content": [_part_summary(part) for part in message.content],
        }
    if isinstance(message, ToolResultMessage):
        return {
            "role": message.role,
            "toolCallId": message.tool_call_id,
            "toolName": message.tool_name,
            "isError": message.is_error,
            "details": message.details,
            "content": [_part_summary(part) for part in message.content],
        }
    return {"role": getattr(message, "role", None)}


def _part_summary(part: object) -> dict[str, object]:
    part_type = getattr(part, "type", None)
    if part_type == "text":
        return {"type": "text", "text": getattr(part, "text", "")}
    if part_type == "toolCall":
        return {
            "type": "toolCall",
            "id": getattr(part, "id", ""),
            "name": getattr(part, "name", ""),
            "arguments": getattr(part, "arguments", {}),
            "thoughtSignature": getattr(part, "thought_signature", None),
        }
    return {"type": part_type}


def main() -> None:
    print(json.dumps(inspect_normalization_diagnostics(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
