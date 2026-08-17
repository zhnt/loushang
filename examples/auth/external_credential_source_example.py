"""Use the experimental Codex credential source through the public auth API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from tempfile import TemporaryDirectory

import loushang.ai as ai
from loushang.ai.advanced.registry import (
    clear_api_adapters,
    register_api_adapter,
    reset_api_adapters,
)
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.provider import ProviderRequest


class _RecordingProvider:
    api = "auth-example-external-source"

    def __init__(self) -> None:
        self.request: ProviderRequest | None = None

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        self.request = request
        yield {"type": "response_start", "response_id": "external-source-example"}
        yield {"type": "text_delta", "text": "ok"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


def _write_offline_codex_fixture(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "codex-access-secret",
                    "account_id": "example-account",
                },
            }
        ),
        encoding="utf-8",
    )


async def run() -> dict[str, object]:
    provider = _RecordingProvider()
    model = Model(
        id="external-source-example",
        provider="openai",
        endpoint="coding-responses",
        api=provider.api,
        base_url="https://offline.example/v1",
        auth=Auth(kind="oauth", provider="openai-codex"),
        capabilities=Capabilities(stream=True),
    )
    with TemporaryDirectory() as directory:
        auth_path = Path(directory) / "auth.json"
        _write_offline_codex_fixture(auth_path)
        source = ai.auth.OpenAICodexCredentialSource(auth_path)
        extensions = ai.auth.AuthExtensionRegistry([source])
        current = await ai.auth.status(model, extensions=extensions)
        request_auth = await ai.auth.get_auth(model, extensions=extensions)
        clear_api_adapters()
        register_api_adapter(provider)
        try:
            await ai.complete(
                model,
                {"messages": [{"role": "user", "content": "hello"}]},
                auth=request_auth,
            )
        finally:
            reset_api_adapters()

    if provider.request is None:
        raise RuntimeError("ProviderRequest was not captured")
    return {
        "authenticated": current.authenticated,
        "experimental": current.experimental,
        "sourceDescription": current.source_description,
        "recoveryHint": current.source_recovery_hint,
        "requestAuthorized": provider.request.headers.get("Authorization")
        == "Bearer codex-access-secret",
        "accountHeaderResolved": provider.request.headers.get("ChatGPT-Account-ID")
        == "example-account",
    }


def main() -> None:
    print(json.dumps(asyncio.run(run()), sort_keys=True))


if __name__ == "__main__":
    main()
