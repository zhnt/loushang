"""Inspect capability validation failures before provider invocation."""

from __future__ import annotations

import asyncio
import json

from loushang.ai import AIError, Model, Tool, UserMessage, stream
from loushang.ai.model import Auth, Capabilities


async def inspect_capability_failure() -> dict[str, object]:
    model = Model(
        id="capability-demo",
        provider="faux",
        endpoint="anthropic-messages",
        api="anthropic-messages",
        base_url="https://example.invalid/v1",
        capabilities=Capabilities(stream=True, tool_use=False),
        auth=Auth(kind="none"),
    )
    context = {
        "messages": [UserMessage(role="user", content="hello", timestamp=0.0)],
        "tools": [
            Tool(
                name="calc",
                description="Calculate values",
                parameters={"type": "object"},
            )
        ],
    }

    try:
        await stream(model, context)
    except AIError as error:
        return {
            "errorType": type(error).__name__,
            "message": str(error),
        }
    raise AssertionError("capability validation should fail before provider lookup")


def main() -> None:
    print(json.dumps(asyncio.run(inspect_capability_failure()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
