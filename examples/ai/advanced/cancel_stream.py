"""Advanced offline stream cancellation example."""

from __future__ import annotations

import asyncio
import json

from loushang.ai import CallOptions, Model, stream
from loushang.ai.advanced.registry import clear_api_adapters, register_api_adapter
from loushang.ai.model import Auth, Capabilities
from loushang.ai.provider import ProviderRequest


class _SlowProvider:
    api = "anthropic-messages"

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.blocked = asyncio.Event()
        self.closed = False

    async def invoke_raw(self, request: ProviderRequest):
        self.started.set()
        try:
            yield {"type": "response_start", "response_id": "cancel-demo"}
            self.blocked.set()
            await asyncio.Event().wait()
        finally:
            self.closed = True


async def inspect_stream_cancellation() -> dict[str, object]:
    provider = _SlowProvider()
    signal = asyncio.Event()
    clear_api_adapters()
    register_api_adapter(provider)
    event_stream = await stream(
        _build_model(),
        {"messages": []},
        CallOptions(cancellation=signal),
    )
    await asyncio.wait_for(provider.blocked.wait(), timeout=1)
    signal.set()
    events = [event async for event in event_stream]
    return {
        "events": [event["type"] for event in events],
        "reason": events[-1]["reason"],
        "stopReason": events[-1]["error"].stop_reason,
        "sourceClosed": provider.closed,
    }


def main() -> None:
    print(
        json.dumps(
            asyncio.run(inspect_stream_cancellation()),
            indent=2,
            sort_keys=True,
        )
    )


def _build_model() -> Model:
    return Model(
        id="cancel-demo",
        provider="cancel-demo",
        endpoint="anthropic-messages",
        api="anthropic-messages",
        base_url="https://example.invalid/v1",
        capabilities=Capabilities(stream=True),
        auth=Auth(kind="none"),
    )


if __name__ == "__main__":
    main()
