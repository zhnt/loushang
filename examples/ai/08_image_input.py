"""Offline image input and image tool-result example."""

from __future__ import annotations

import json

from loushang.ai import (
    AssistantMessage,
    Context,
    ImagePart,
    TextPart,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


def inspect_image_input() -> dict[str, object]:
    return _summarize_images(_build_context().messages)


def main() -> None:
    print(json.dumps(inspect_image_input(), indent=2, sort_keys=True))


def _summarize_images(messages: list[object]) -> dict[str, object]:
    user_images = 0
    tool_result_images = 0
    tool_result_texts: list[str] = []
    for message in messages:
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if role == "user" and isinstance(content, list):
            user_images += sum(1 for part in content if isinstance(part, ImagePart))
        if role == "toolResult" and isinstance(content, list):
            tool_result_images += sum(
                1 for part in content if isinstance(part, ImagePart)
            )
            tool_result_texts.extend(
                part.text for part in content if isinstance(part, TextPart)
            )
    return {
        "userImages": user_images,
        "toolResultImages": tool_result_images,
        "toolResultText": "\n".join(tool_result_texts),
    }


def _build_context() -> Context:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="call_read_image",
                name="read_image",
                arguments={"path": "chart.png"},
            )
        ],
        api="openai-responses",
        provider="openai",
        endpoint="openai-responses",
        model="gpt-5.4-mini",
        response_id="resp_1",
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost={},
        ),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )
    return Context(
        messages=[
            UserMessage(
                role="user",
                content=[
                    TextPart(type="text", text="What does this image show?"),
                    ImagePart(
                        type="image", data="dXNlci1pbWFnZQ==", mime_type="image/png"
                    ),
                ],
                timestamp=0.0,
            ),
            assistant,
            ToolResultMessage(
                role="toolResult",
                tool_call_id="call_read_image",
                tool_name="read_image",
                content=[
                    TextPart(type="text", text="chart shows growth"),
                    ImagePart(
                        type="image", data="dG9vbC1pbWFnZQ==", mime_type="image/png"
                    ),
                ],
                is_error=False,
                timestamp=0.0,
            ),
        ]
    )


if __name__ == "__main__":
    main()
