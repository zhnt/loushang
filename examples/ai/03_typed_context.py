"""Offline explicit Context type example."""

from __future__ import annotations

import json

from loushang.ai import Context, TextPart, Tool, UserMessage

PROVIDER_ID = "moonshot"
ENDPOINT_ID = "openai-completions"
MODEL_ID = "kimi-k3.1-pro"


def _build_context() -> Context:
    return Context(
        system_prompt=(
            "You are an offline example assistant. Answer directly; only call tools "
            "when the user asks for them."
        ),
        messages=[
            UserMessage(
                role="user",
                content="Introduce yourself in two sentences and say what 1 + 1 equals. Do not call tools.",
                timestamp=0.0,
            )
        ],
        tools=[
            Tool(
                name="add",
                description="Return the sum of two numbers a and b.",
                parameters={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                    "additionalProperties": False,
                },
            )
        ],
    )


def inspect_typed_context() -> dict[str, object]:
    context = _build_context()
    fixture_content = [TextPart(type="text", text="mock hello from typed context")]
    return {
        "model": f"{PROVIDER_ID}:{ENDPOINT_ID}:{MODEL_ID}",
        "messageCount": len(context.messages),
        "toolCount": len(context.tools or ()),
        "stopReason": "stop",
        "text": "".join(part.text for part in fixture_content),
    }


def main() -> None:
    print(json.dumps(inspect_typed_context(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
