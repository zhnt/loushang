from __future__ import annotations

import asyncio

from loushang.ai.context import normalize_context
from loushang.ai.model import Auth, Model
from loushang.ai.protocols.faux import FauxAdapter
from loushang.ai.types import UserMessage
from tests.protocols._runtime import start_test_provider_stream


def _normalized_context(model, context, options=None):
    pairing_mode = (
        "strict" if getattr(options, "pairing_mode", "strict") == "strict" else "repair"
    )
    return normalize_context(context, model=model, pairing_mode=pairing_mode)


async def _stream(provider, model, context, options=None, request=None):
    return start_test_provider_stream(
        provider,
        model,
        _normalized_context(model, context, options),
        options,
        request=request,
    )


def test_faux_adapter_stream_resolves_request_when_omitted() -> None:
    adapter = FauxAdapter()
    model = Model(
        id="faux-model",
        provider="faux",
        endpoint="anthropic-messages",
        api="anthropic-messages",
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
    )

    stream = asyncio.run(
        _stream(
            adapter,
            model,
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            None,
        )
    )
    message = asyncio.run(stream.result())

    assert message.api == "anthropic-messages"
    assert message.provider == "faux"
    assert message.model == "faux-model"
