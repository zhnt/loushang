"""Offline structured output contract example."""

from __future__ import annotations

import json

from loushang.ai import AssistantMessage, StructuredOutputOptions, TextPart

ANSWER_SCHEMA = {
    "title": "Answer",
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "score": {"type": "integer"},
    },
    "required": ["answer", "score"],
    "additionalProperties": False,
}


def _offline_message() -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text='{"answer":"Paris","score":10}')],
        api="openai-responses",
        provider="openai",
        endpoint="openai-responses",
        model="gpt-5.4-mini",
        response_id="structured-demo",
        usage=None,
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def inspect_structured_output() -> dict[str, object]:
    output = StructuredOutputOptions(mode="json_schema", schema=ANSWER_SCHEMA)
    message = _offline_message()
    text = "".join(
        part.text for part in message.content if getattr(part, "type", None) == "text"
    )
    return {
        "mode": output.mode,
        "responseId": message.response_id,
        "stopReason": message.stop_reason,
        "parsed": json.loads(text),
    }


def main() -> None:
    print(json.dumps(inspect_structured_output(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
