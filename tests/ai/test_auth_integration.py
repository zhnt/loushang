from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from loushang.ai import OAuthBearerAuth, OAuthCredential, complete
from loushang.ai.advanced.registry import (
    clear_api_adapters,
    register_api_adapter,
    reset_api_adapters,
)
from loushang.ai.auth import FileCredentialStore, get_auth
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.provider import ProviderRequest


class _RecordingProvider:
    api = "auth-integration"

    def __init__(self) -> None:
        self.request: ProviderRequest | None = None

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        self.request = request
        yield {"type": "response_start", "response_id": "auth-integration"}
        yield {"type": "text_delta", "text": "ok"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


def test_get_auth_bearer_provider_request_chain(tmp_path: Path) -> None:
    provider = _RecordingProvider()
    model = Model(
        id="model-a",
        provider="example",
        endpoint="oauth",
        api=provider.api,
        base_url="https://example.test/v1",
        auth=Auth(kind="oauth", provider="example-oauth"),
        capabilities=Capabilities(stream=True),
    )
    credential = OAuthCredential(
        provider="example-oauth",
        access_token="access-secret",
        refresh_token="refresh-secret",
        expires_at=4102444800,
        extra_headers={"x-account": "account-id"},
    )

    async def scenario():
        store = FileCredentialStore(tmp_path)
        store.save(credential)
        request_auth = await get_auth(model, store=store)
        clear_api_adapters()
        register_api_adapter(provider)
        try:
            return await complete(
                model,
                {"messages": [{"role": "user", "content": "hello"}]},
                auth=request_auth,
            )
        finally:
            reset_api_adapters()

    message = asyncio.run(scenario())

    assert message.content[0].text == "ok"  # type: ignore[union-attr]
    assert provider.request is not None
    assert provider.request.headers == {
        "Authorization": "Bearer access-secret",
        "x-account": "account-id",
    }
    assert isinstance(provider.request.options.auth, OAuthBearerAuth)
    assert provider.request.options.credential is None
    assert provider.request.options.credential_file is None
