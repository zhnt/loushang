"""Resolve API-key auth, then pass it to a model request as an application."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator

import loushang.ai as ai
from loushang.ai.advanced.registry import (
    clear_api_adapters,
    register_api_adapter,
    reset_api_adapters,
)
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.provider import ProviderRequest

ENV_NAME = "LOUSHANG_AUTH_EXAMPLE_API_KEY"


class _RecordingProvider:
    api = "auth-example-api-key"

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        self.requests.append(request)
        yield {"type": "response_start", "response_id": "auth-example"}
        yield {"type": "text_delta", "text": "ok"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


async def run() -> dict[str, object]:
    provider = _RecordingProvider()
    model = Model(
        id="api-key-example",
        provider="example",
        endpoint="api-key",
        api=provider.api,
        base_url="https://offline.example/v1",
        auth=Auth(kind="apiKey", api_key_env=ENV_NAME),
        capabilities=Capabilities(stream=True),
    )
    previous = os.environ.get(ENV_NAME)
    os.environ[ENV_NAME] = "environment-secret"
    clear_api_adapters()
    register_api_adapter(provider)
    try:
        request_auth = await ai.auth.get_auth(model)
        await ai.complete(
            model,
            {"messages": [{"role": "user", "content": "environment"}]},
            auth=request_auth,
        )
    finally:
        reset_api_adapters()
        if previous is None:
            os.environ.pop(ENV_NAME, None)
        else:
            os.environ[ENV_NAME] = previous

    request = provider.requests[0]
    return {
        "calls": len(provider.requests),
        "authenticated": request.headers.get("Authorization")
        == "Bearer environment-secret",
        "authType": type(request.options.auth).__name__,
    }


def main() -> None:
    print(json.dumps(asyncio.run(run()), sort_keys=True))


if __name__ == "__main__":
    main()
