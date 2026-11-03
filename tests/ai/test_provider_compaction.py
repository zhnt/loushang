from __future__ import annotations

import asyncio

import pytest

from loushang.ai import (
    ApiKeyAuth,
    CallOptions,
    Context,
    ProviderCompactionWindow,
    UserMessage,
    compact_provider_window,
)
from loushang.ai.context import normalize_context
from loushang.ai.errors import AIProviderProtocolError, UnsupportedCapabilityError
from loushang.ai.model import Capabilities, Model
from loushang.ai.protocols._openai_responses import convert_responses_messages
from loushang.ai.protocols.openai_responses import OpenAIResponsesAdapter
from loushang.ai.provider.resolution import resolve_request_for_model


def _model(*, capable: bool = True, endpoint: str = "responses") -> Model:
    return Model(
        id="gpt-test",
        provider="openai",
        endpoint=endpoint,
        api="openai-responses",
        base_url="https://api.example.test/v1",
        capabilities=Capabilities(
            provider_compaction="openai-responses" if capable else None
        ),
    )


class _CompactionClient:
    def __init__(self, output: list[dict[str, object]]) -> None:
        self.kwargs: dict[str, object] = {}
        self.responses = self
        self.output = output

    async def compact(self, **kwargs: object) -> dict[str, object]:
        self.kwargs = kwargs
        return {"output": self.output}


def test_standalone_compaction_preserves_canonical_window_and_replays_it() -> None:
    model = _model()
    output: list[dict[str, object]] = [
        {"type": "message", "role": "user", "content": "keep this", "future_field": 7},
        {"type": "compaction", "encrypted_content": "opaque-ciphertext"},
    ]
    client = _CompactionClient(output)
    adapter = OpenAIResponsesAdapter(client=client)
    request = resolve_request_for_model(
        model,
        context=normalize_context(
            Context(messages=[UserMessage(role="user", content="old", timestamp=0)]),
            model=model,
        ),
        options=CallOptions(auth=ApiKeyAuth("test-key")),
    )

    window = asyncio.run(adapter.compact_window(request))

    assert client.kwargs["model"] == "gpt-test"
    assert client.kwargs["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "old"}]}
    ]
    assert client.kwargs["extra_headers"]["Authorization"] == "Bearer test-key"
    assert window.items == output
    assert ProviderCompactionWindow.from_raw(window.to_raw()).items == output
    output[0]["content"] = "changed after return"
    assert window.items[0]["content"] == "keep this"

    normalized = normalize_context(
        Context(
            provider_window=window,
            messages=[UserMessage(role="user", content="next", timestamp=1)],
        ),
        model=model,
    )
    assert convert_responses_messages(model, normalized) == [
        *window.items,
        {"role": "user", "content": [{"type": "input_text", "text": "next"}]},
    ]


def test_provider_window_rejects_model_switch_and_duplicate_system_prompt() -> None:
    window = ProviderCompactionWindow.from_items(
        provider="openai",
        endpoint="responses",
        model="gpt-test",
        items=[{"type": "compaction", "encrypted_content": "opaque"}],
    )
    with pytest.raises(ValueError, match="incompatible"):
        normalize_context(
            Context(provider_window=window), model=_model(endpoint="other")
        )
    with pytest.raises(ValueError, match="prior system context"):
        normalize_context(Context(system_prompt="duplicate", provider_window=window))


def test_provider_compaction_rejects_missing_capability_before_request() -> None:
    with pytest.raises(UnsupportedCapabilityError, match="provider compaction"):
        asyncio.run(compact_provider_window(_model(capable=False), Context()))


def test_public_provider_compaction_routes_to_registered_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = ProviderCompactionWindow.from_items(
        provider="openai",
        endpoint="responses",
        model="gpt-test",
        items=[{"type": "compaction", "encrypted_content": "opaque"}],
    )

    class _Adapter:
        async def compact_window(self, request: object) -> ProviderCompactionWindow:
            assert request.model.id == "gpt-test"
            return expected

    class _Registry:
        def list_api_adapters(self) -> list[object]:
            return [_Adapter()]

        def get_api_adapter(self, api: str) -> object:
            assert api == "openai-responses"
            return _Adapter()

    monkeypatch.setattr(
        "loushang.ai.api.compaction.get_default_api_registry", lambda: _Registry()
    )
    result = asyncio.run(
        compact_provider_window(
            _model(),
            Context(messages=[UserMessage(role="user", content="old", timestamp=0)]),
            CallOptions(auth=ApiKeyAuth("test-key")),
        )
    )
    assert result is expected


@pytest.mark.parametrize(
    "output",
    [[], [{"type": "message", "content": "summary"}], [{"type": "compaction"}]],
)
def test_standalone_compaction_rejects_incomplete_provider_output(
    output: list[dict[str, object]],
) -> None:
    model = _model()
    adapter = OpenAIResponsesAdapter(client=_CompactionClient(output))
    request = resolve_request_for_model(
        model,
        options=CallOptions(auth=ApiKeyAuth("test-key")),
    )
    with pytest.raises(AIProviderProtocolError, match="invalid output window"):
        asyncio.run(adapter.compact_window(request))
