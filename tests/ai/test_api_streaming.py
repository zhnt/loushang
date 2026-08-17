from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field, replace
from types import ModuleType, SimpleNamespace

import pytest

from loushang.ai import CallOptions, ReasoningOptions, StructuredOutputOptions
from loushang.ai.api.streaming import (
    complete,
    complete_structured,
    stream,
)
from loushang.ai.api_registry import (
    APIRegistry,
    get_default_api_registry,
)
from loushang.ai.auth import ApiKeyAuth
from loushang.ai.context import NormalizedContext, normalize_context
from loushang.ai.errors import AIRateLimitError, UnsupportedCapabilityError
from loushang.ai.model import (
    Auth,
    Capabilities,
    Model,
    OpenAICompletionsConfig,
    OpenAIResponsesConfig,
)
from loushang.ai.options import get_reasoning_effort, is_reasoning_requested
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.protocols.openai_responses import OpenAIResponsesAdapter
from loushang.ai.provider import ProviderRequest
from loushang.ai.provider.invocation import call_api_adapter_stream
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    TextPart,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


@dataclass
class _Capabilities:
    supports_image_input: bool = False
    supports_thinking: bool = False


@dataclass
class _Model:
    id: str = "test-model"
    api: str | None = None
    capabilities: _Capabilities = field(default_factory=_Capabilities)


class _Provider:
    api = "faux"

    def __init__(self, api: str = "faux") -> None:
        self.api = api
        self.context = None
        self.options = None
        self.request = None

    async def invoke_raw(self, request):
        self.context = request.context
        self.options = request.options
        self.request = request
        yield {"type": "response_done"}


class _ValidatingProvider(_Provider):
    def __init__(self, api: str = "faux") -> None:
        super().__init__(api)
        self.validated_request: ProviderRequest | None = None

    def validate_request(self, request: ProviderRequest) -> None:
        self.validated_request = request


class _RejectingValidatorProvider(_Provider):
    def validate_request(self, request: ProviderRequest) -> None:
        raise TypeError(f"invalid adapter for {request.model.api}")


class _ErrorProvider(_Provider):
    async def invoke_raw(self, request):
        self.context = request.context
        self.options = request.options
        self.request = request
        yield {
            "type": "response_error",
            "message": "rate limited",
            "code": 429,
            "error_info": {
                "code": "rate_limit",
                "message": "rate limited",
                "source": "faux",
                "retryable": True,
                "provider": "faux",
                "endpoint": None,
                "model": "test-model",
                "statusCode": 429,
                "requestId": "req_public",
                "details": {},
            },
        }


def _assert_normalized_provider_context(context: object) -> NormalizedContext:
    assert isinstance(context, NormalizedContext)
    return context


class _LegacyProvider:
    api = "faux"

    def __init__(self, api: str = "faux") -> None:
        self.api = api
        self.context = None
        self.options = None

    async def invoke_raw(self, model, context, options):
        self.context = context
        self.options = options
        yield {"type": "response_done"}


class _LegacyProviderWithOptionalDebug:
    api = "faux"

    def __init__(self, api: str = "faux") -> None:
        self.api = api
        self.context = None
        self.debug = None

    async def invoke_raw(self, model, context, options, debug=False):
        self.context = context
        self.debug = debug
        yield {"type": "response_done"}


class _KeywordRequestProvider:
    api = "faux"

    def __init__(self, api: str = "faux") -> None:
        self.api = api
        self.context = None
        self.options = None
        self.request = None

    async def invoke_raw(self, model, context, options, *, request=None):
        self.context = context
        self.options = options
        self.request = request
        yield {"type": "response_done"}


class _StreamOnlyProvider:
    api = "faux"

    async def stream(self, model, context, options, request):
        return None


def _empty_test_registry() -> APIRegistry:
    registry = get_default_api_registry()
    registry.clear_api_adapters()
    return registry


def _test_registry_with(provider) -> APIRegistry:
    registry = _empty_test_registry()
    registry.register_api_adapter(provider)
    return registry


@pytest.mark.parametrize("entrypoint", ["complete", "stream"])
def test_public_invocation_preserves_effective_model_identity(entrypoint: str) -> None:
    provider = _Provider()
    registry = _empty_test_registry()
    registry.register_api_adapter(provider)
    model = Model(
        id="effective-model",
        provider="selected-provider",
        endpoint="selected-endpoint",
        api="faux",
        base_url="https://selected.example/v1",
        region="us",
        auth=Auth(kind="none"),
        capabilities=Capabilities(input=("text",), output=("text",), stream=True),
    )

    async def _run() -> AssistantMessage:
        context = {
            "messages": [UserMessage(role="user", content="hello", timestamp=0.0)]
        }
        if entrypoint == "complete":
            return await complete(model, context)
        event_stream = await stream(model, context)
        return await event_stream.result()

    message = asyncio.run(_run())

    assert provider.request is not None
    assert provider.request.model is model
    assert provider.request.model.provider_id == model.provider_id
    assert provider.request.model.endpoint_id == model.endpoint_id
    assert provider.request.model.region == model.region
    assert message.provider == "selected-provider"
    assert message.endpoint == "selected-endpoint"
    assert message.model == "effective-model"


def test_public_stream_suppresses_cache_key_when_retention_is_none() -> None:
    provider = _Provider()
    registry = _empty_test_registry()
    registry.register_api_adapter(provider)
    model = Model(
        id="cache-model",
        provider="custom",
        endpoint="faux",
        api="faux",
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(input=("text",), stream=True),
        adapter=OpenAIResponsesConfig(prompt_cache_key=True),
    )

    async def _run() -> None:
        event_stream = await stream(
            model,
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(cache_key="opaque-key", cache_retention="none"),
        )
        await event_stream.result()

    asyncio.run(_run())

    assert provider.request is not None
    assert isinstance(provider.request.options, CallOptions)
    assert provider.request.options.cache_key is None


def test_stream_defaults_to_repair_pairing_and_exposes_strict_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default pairing repairs missing tool results; strict remains opt-in.

    The default changed from strict to repair so restored/interrupted
    transcripts recover automatically instead of failing the whole request.
    """
    _patch_resolved_request(monkeypatch)
    monkeypatch.setattr("loushang.ai.messages.resolve_model_api", lambda _model: "faux")
    monkeypatch.setattr(
        "loushang.ai.tool.transform.resolve_model_api", lambda _model: "faux"
    )
    provider = _Provider()
    _test_registry_with(provider)
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
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

    # Default (CallOptions()) now repairs the missing tool result.
    asyncio.run(
        stream(
            _Model(),
            {
                "messages": [
                    assistant,
                    UserMessage(role="user", content="next", timestamp=0.0),
                ]
            },
            CallOptions(),
        )
    )

    normalized = _assert_normalized_provider_context(provider.context)
    assert [type(message).__name__ for message in normalized.messages] == [
        "AssistantMessage",
        "ToolResultMessage",
        "UserMessage",
    ]
    synthetic = normalized.messages[1]
    assert isinstance(synthetic, ToolResultMessage)
    assert synthetic.tool_call_id == "call_1"
    assert synthetic.is_error is True

    # Explicit strict still rejects the malformed transcript.
    with pytest.raises(ValueError, match="Missing tool results before next message"):
        asyncio.run(
            stream(
                _Model(),
                {
                    "messages": [
                        assistant,
                        UserMessage(role="user", content="next", timestamp=0.0),
                    ]
                },
                CallOptions(pairing_mode="strict"),
            )
        )


def test_complete_raises_typed_error_for_stream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(monkeypatch)
    provider = _ErrorProvider()
    _test_registry_with(provider)

    with pytest.raises(AIRateLimitError) as exc_info:
        asyncio.run(
            complete(
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(),
            )
        )

    assert exc_info.value.info.status_code == 429
    assert exc_info.value.info.request_id == "req_public"


def test_stream_exposes_strict_pairing_through_public_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(monkeypatch)
    monkeypatch.setattr("loushang.ai.messages.resolve_model_api", lambda _model: "faux")
    monkeypatch.setattr(
        "loushang.ai.tool.transform.resolve_model_api", lambda _model: "faux"
    )
    provider = _Provider()
    _test_registry_with(provider)
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
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

    with pytest.raises(ValueError, match="Missing tool results before next message"):
        asyncio.run(
            stream(
                _Model(),
                {
                    "messages": [
                        assistant,
                        UserMessage(role="user", content="next", timestamp=0.0),
                    ]
                },
                CallOptions(pairing_mode="strict"),
            )
        )


def test_stream_passes_normalized_context_to_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(monkeypatch)
    monkeypatch.setattr("loushang.ai.messages.resolve_model_api", lambda _model: "faux")
    monkeypatch.setattr(
        "loushang.ai.tool.transform.resolve_model_api", lambda _model: "faux"
    )
    provider = _Provider()
    _test_registry_with(provider)

    asyncio.run(
        stream(
            _Model(),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(),
        )
    )

    normalized = _assert_normalized_provider_context(provider.context)
    assert normalized.messages[0].role == "user"


@pytest.mark.parametrize(
    ("capabilities", "context", "options", "expected_message"),
    [
        (
            Capabilities(input=("text",), stream=False),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(),
            "does not support streaming",
        ),
        (
            Capabilities(input=("text",), stream=True, tool_use=False),
            {
                "messages": [UserMessage(role="user", content="hello", timestamp=0.0)],
                "tools": [
                    {
                        "name": "calc",
                        "description": "Calculate values",
                        "parameters": {"type": "object"},
                    }
                ],
            },
            CallOptions(),
            "does not support tool use",
        ),
        (
            Capabilities(input=("text",), stream=True, reasoning=False),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(reasoning=ReasoningOptions(effort="high")),
            "does not support reasoning",
        ),
        (
            Capabilities(input=("text",), stream=True, structured_output=False),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(output=StructuredOutputOptions(mode="json_object")),
            "does not support structured output",
        ),
        (
            Capabilities(input=("text",), stream=True, temperature=False),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(temperature=0.2),
            "does not support temperature",
        ),
        (
            Capabilities(input=("text",), stream=True),
            {
                "messages": [
                    UserMessage(
                        role="user",
                        content=[
                            ImagePart(
                                type="image",
                                data="aGVsbG8=",
                                mime_type="image/png",
                            )
                        ],
                        timestamp=0.0,
                    )
                ]
            },
            CallOptions(),
            "does not support image input",
        ),
    ],
)
def test_stream_enforces_capability_matrix(
    monkeypatch: pytest.MonkeyPatch,
    capabilities: Capabilities,
    context: dict[str, object],
    options: CallOptions,
    expected_message: str,
) -> None:
    _patch_resolved_request(monkeypatch, capabilities=capabilities)
    monkeypatch.setattr("loushang.ai.messages.resolve_model_api", lambda _model: "faux")
    monkeypatch.setattr(
        "loushang.ai.tool.transform.resolve_model_api", lambda _model: "faux"
    )
    provider = _Provider()
    _test_registry_with(provider)

    with pytest.raises(UnsupportedCapabilityError, match=expected_message):
        asyncio.run(stream(_Model(), context, options))

    assert provider.context is None


def test_stream_allows_complete_capability_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(
        monkeypatch,
        capabilities=Capabilities(
            input=("text", "image"),
            stream=True,
            tool_use=True,
            reasoning=True,
            structured_output=True,
            temperature=True,
        ),
    )
    monkeypatch.setattr("loushang.ai.messages.resolve_model_api", lambda _model: "faux")
    monkeypatch.setattr(
        "loushang.ai.tool.transform.resolve_model_api", lambda _model: "faux"
    )
    provider = _Provider()
    _test_registry_with(provider)

    asyncio.run(
        stream(
            _Model(),
            {
                "messages": [
                    UserMessage(
                        role="user",
                        content=[
                            ImagePart(
                                type="image",
                                data="aGVsbG8=",
                                mime_type="image/png",
                            )
                        ],
                        timestamp=0.0,
                    )
                ],
                "tools": [
                    {
                        "name": "calc",
                        "description": "Calculate values",
                        "parameters": {"type": "object"},
                    }
                ],
            },
            CallOptions(
                temperature=0.2,
                reasoning=ReasoningOptions(effort="high"),
            ),
        )
    )

    normalized = _assert_normalized_provider_context(provider.context)
    assert normalized.tools == (
        Tool(
            name="calc", description="Calculate values", parameters={"type": "object"}
        ),
    )
    assert provider.options.reasoning == ReasoningOptions(effort="high")


def test_complete_does_not_require_stream_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(
        monkeypatch,
        capabilities=Capabilities(input=("text",), stream=False),
    )
    monkeypatch.setattr("loushang.ai.messages.resolve_model_api", lambda _model: "faux")
    monkeypatch.setattr(
        "loushang.ai.tool.transform.resolve_model_api", lambda _model: "faux"
    )
    provider = _Provider()
    _test_registry_with(provider)

    result = asyncio.run(
        complete(
            _Model(),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(),
        )
    )

    assert result.api == "faux"
    assert result.provider == "faux"
    assert result.model == "test-model"
    _assert_normalized_provider_context(provider.context)


def test_complete_structured_requires_output_options() -> None:
    with pytest.raises(ValueError, match="requires StructuredOutputOptions"):
        asyncio.run(
            complete_structured(
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
            )
        )


def test_stream_canonicalizes_raw_dict_context_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(
        monkeypatch, capabilities=Capabilities(input=("text", "image"), stream=True)
    )
    monkeypatch.setattr("loushang.ai.messages.resolve_model_api", lambda _model: "faux")
    monkeypatch.setattr(
        "loushang.ai.tool.transform.resolve_model_api", lambda _model: "faux"
    )
    provider = _Provider()
    _test_registry_with(provider)

    asyncio.run(
        stream(
            _Model(),
            {
                "systemPrompt": "system text",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "hello"},
                            {
                                "type": "image",
                                "data": "aW1n",
                                "mimeType": "image/png",
                            },
                        ],
                        "timestamp": 12.0,
                    }
                ],
            },
            CallOptions(),
        )
    )

    normalized = _assert_normalized_provider_context(provider.context)
    message = normalized.messages[0]
    assert normalized.system_prompt == "system text"
    assert isinstance(message, UserMessage)
    assert message.content == [
        TextPart(type="text", text="hello"),
        ImagePart(type="image", data="aW1n", mime_type="image/png"),
    ]
    assert message.timestamp == 12.0


def test_stream_rejects_raw_dict_tools_with_non_object_parameters_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(monkeypatch)
    provider = _Provider()
    _test_registry_with(provider)

    with pytest.raises(TypeError, match="Unsupported tool parameters type"):
        asyncio.run(
            stream(
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ],
                    "tools": [
                        {
                            "name": "calc",
                            "description": "Calculate values",
                            "parameters": "bad",
                        }
                    ],
                },
                CallOptions(),
            )
        )

    assert provider.context is None


def test_stream_rejects_raw_dict_tools_with_invalid_names_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(monkeypatch)
    provider = _Provider()
    _test_registry_with(provider)

    with pytest.raises(TypeError, match="Unsupported tool name type"):
        asyncio.run(
            stream(
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ],
                    "tools": [
                        {
                            "name": "",
                            "description": "bad",
                            "parameters": {"type": "object"},
                        }
                    ],
                },
                CallOptions(),
            )
        )

    assert provider.context is None


@pytest.mark.parametrize(
    "legacy_options",
    [
        SimpleNamespace(max_tokens=64),
        SimpleNamespace(timeout=10),
        SimpleNamespace(retries=2),
        SimpleNamespace(max_retry_delay_ms=500),
        SimpleNamespace(reasoning="high"),
        SimpleNamespace(reasoning_summary="auto"),
        SimpleNamespace(thinking_budget_tokens=4096),
    ],
)
def test_stream_rejects_non_call_options_before_provider(
    monkeypatch: pytest.MonkeyPatch,
    legacy_options: object,
) -> None:
    _patch_resolved_request(monkeypatch)
    provider = _Provider()
    _test_registry_with(provider)

    with pytest.raises(TypeError, match="options must be CallOptions"):
        asyncio.run(
            stream(
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                legacy_options,  # type: ignore[arg-type]
            )
        )

    assert provider.context is None


def test_complete_rejects_non_call_options_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(monkeypatch)
    provider = _Provider()
    _test_registry_with(provider)

    with pytest.raises(TypeError, match="options must be CallOptions"):
        asyncio.run(
            complete(
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                SimpleNamespace(max_tokens=64),  # type: ignore[arg-type]
            )
        )

    assert provider.context is None


def test_stream_passes_request_through_registered_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(monkeypatch)
    monkeypatch.setattr("loushang.ai.messages.resolve_model_api", lambda _model: "faux")
    monkeypatch.setattr(
        "loushang.ai.tool.transform.resolve_model_api", lambda _model: "faux"
    )
    provider = _Provider()
    registry = _empty_test_registry()
    registry.register_api_adapter(provider)

    asyncio.run(
        stream(
            _Model(),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(),
        )
    )

    _assert_normalized_provider_context(provider.context)
    assert provider.request.model.api == "faux"


def test_stream_runs_optional_provider_request_validator_before_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(monkeypatch)
    provider = _ValidatingProvider()
    registry = _empty_test_registry()
    registry.register_api_adapter(provider)

    event_stream = asyncio.run(
        stream(
            _Model(),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(),
        )
    )

    assert provider.validated_request is provider.request
    assert provider.validated_request is not None
    assert provider.validated_request.model.api == "faux"
    asyncio.run(event_stream.aclose())


def test_stream_raises_provider_request_validation_error_before_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(monkeypatch)
    provider = _RejectingValidatorProvider()
    registry = _empty_test_registry()
    registry.register_api_adapter(provider)

    with pytest.raises(TypeError, match="invalid adapter for faux"):
        asyncio.run(
            stream(
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(),
            )
        )

    assert provider.request is None


def test_register_api_adapter_rejects_stream_only_provider() -> None:
    registry = _empty_test_registry()

    with pytest.raises(TypeError, match="invoke_raw"):
        registry.register_api_adapter(_StreamOnlyProvider())


def test_register_api_adapter_rejects_legacy_provider_signature() -> None:
    provider = _LegacyProvider()
    registry = _empty_test_registry()

    with pytest.raises(TypeError, match="exactly one ProviderRequest"):
        registry.register_api_adapter(provider)


def test_register_api_adapter_rejects_keyword_request_signature() -> None:
    provider = _KeywordRequestProvider()
    registry = _empty_test_registry()

    with pytest.raises(TypeError, match="exactly one ProviderRequest"):
        registry.register_api_adapter(provider)


def test_register_api_adapter_rejects_optional_legacy_argument_signature() -> None:
    provider = _LegacyProviderWithOptionalDebug()
    registry = _empty_test_registry()

    with pytest.raises(TypeError, match="exactly one ProviderRequest"):
        registry.register_api_adapter(provider)


@pytest.mark.parametrize(
    "api",
    (
        "openai-completions",
        "openai-responses",
        "anthropic-messages",
    ),
)
def test_stream_maps_reasoning_options_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
    api: str,
) -> None:
    _patch_resolved_request(
        monkeypatch,
        capabilities=Capabilities(input=("text",), stream=True, reasoning=True),
        api=api,
        provider="custom",
    )
    provider = _Provider(api=api)
    _test_registry_with(provider)

    asyncio.run(
        stream(
            _Model(),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(
                reasoning=ReasoningOptions(
                    enabled=True,
                    effort="medium",
                    budget_tokens=2048,
                    expose_summary=True,
                ),
                max_output_tokens=123,
            ),
        )
    )

    assert isinstance(provider.options, CallOptions)
    assert provider.options.max_output_tokens == 123
    assert provider.options.reasoning == ReasoningOptions(
        enabled=True,
        effort="medium",
        budget_tokens=2048,
        expose_summary=True,
    )
    assert provider.request.model.api == api


def test_default_registry_rejects_legacy_provider_at_registration() -> None:
    with pytest.raises(TypeError, match="exactly one ProviderRequest"):
        _test_registry_with(_LegacyProvider())


def test_call_api_adapter_stream_supports_registered_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved_request(monkeypatch)
    provider = _Provider()
    registry = _empty_test_registry()
    registry.register_api_adapter(provider)

    asyncio.run(
        call_api_adapter_stream(
            registry.get_api_adapter("faux"),
            _provider_request(
                provider="faux",
                endpoint="faux",
                api="faux",
                base_url=None,
                model_id="test-model",
                context=normalize_context(
                    {
                        "messages": [
                            UserMessage(role="user", content="hello", timestamp=0.0)
                        ]
                    }
                ),
                options=CallOptions(),
                capabilities=Capabilities(input=("text",), stream=True),
            ),
        )
    )

    assert provider.request.model.api == "faux"
    assert provider.context.messages[0].role == "user"


def test_call_api_adapter_stream_requires_normalized_context() -> None:
    provider = _Provider()
    registry = _empty_test_registry()
    registry.register_api_adapter(provider)

    with pytest.raises(
        TypeError, match="ProviderRequest.context must be NormalizedContext"
    ):
        asyncio.run(
            call_api_adapter_stream(
                registry.get_api_adapter("faux"),
                _provider_request(
                    provider="faux",
                    endpoint="faux",
                    api="faux",
                    base_url=None,
                    model_id="test-model",
                    context={
                        "messages": [
                            UserMessage(role="user", content="hello", timestamp=0.0)
                        ]
                    },
                    options=CallOptions(),
                    capabilities=Capabilities(input=("text",), stream=True),
                ),
            )
        )


def test_get_api_adapter_stream_rejects_legacy_provider_signature() -> None:
    provider = _LegacyProvider()
    registry = _empty_test_registry()

    with pytest.raises(TypeError, match="exactly one ProviderRequest"):
        registry.register_api_adapter(provider)


def test_get_api_adapter_stream_rejects_legacy_optional_arg_signature() -> None:
    provider = _LegacyProviderWithOptionalDebug()
    registry = _empty_test_registry()

    with pytest.raises(TypeError, match="exactly one ProviderRequest"):
        registry.register_api_adapter(provider)


def test_call_api_adapter_stream_rejects_mismatched_resolved_request() -> None:
    provider = _Provider()
    registry = _empty_test_registry()
    registry.register_api_adapter(provider)
    request = _provider_request(
        provider="faux",
        endpoint="other",
        api="other",
        base_url=None,
        capabilities=Capabilities(input=("text",), stream=True),
    )

    with pytest.raises(ValueError, match="Mismatched api"):
        asyncio.run(
            call_api_adapter_stream(
                registry.get_api_adapter("faux"),
                replace(
                    request,
                    context=normalize_context(
                        {
                            "messages": [
                                UserMessage(
                                    role="user",
                                    content="hello",
                                    timestamp=0.0,
                                )
                            ]
                        }
                    ),
                    options=CallOptions(),
                ),
            )
        )


def test_call_api_adapter_stream_passes_normalized_context_without_renormalizing() -> (
    None
):
    provider = _Provider(api="anthropic-messages")
    registry = _empty_test_registry()
    registry.register_api_adapter(provider)
    request = _provider_request(
        api="anthropic-messages",
        provider="anthropic",
        endpoint="anthropic-messages",
        base_url=None,
        capabilities=Capabilities(input=("text",), stream=True),
    )
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call.1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
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

    normalized = normalize_context(
        {
            "messages": [
                assistant,
                ToolResultMessage(
                    role="toolResult",
                    tool_call_id="call.1",
                    tool_name="calc",
                    content=[],
                    is_error=False,
                    timestamp=0.0,
                ),
            ]
        },
        model=SimpleNamespace(api="anthropic-messages"),
    )

    asyncio.run(
        call_api_adapter_stream(
            registry.get_api_adapter("anthropic-messages"),
            replace(
                request,
                context=normalized,
                options=CallOptions(),
            ),
        )
    )

    assert provider.context is normalized
    normalized_assistant = provider.context.messages[0]
    normalized_tool_result = provider.context.messages[1]
    assert normalized_assistant.content[0].id == "call_1"
    assert normalized_tool_result.tool_call_id == "call_1"


def test_stream_validates_effective_model_capabilities() -> None:
    model = Model(
        id="text-only",
        provider="custom",
        endpoint="faux",
        api="faux",
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(input=("text",), stream=True),
    )
    provider = _Provider()
    _test_registry_with(provider)

    with pytest.raises(
        UnsupportedCapabilityError, match="does not support image input"
    ):
        asyncio.run(
            stream(
                model,
                {
                    "messages": [
                        UserMessage(
                            role="user",
                            content=[
                                ImagePart(
                                    type="image",
                                    data="aGVsbG8=",
                                    mime_type="image/png",
                                )
                            ],
                            timestamp=0.0,
                        )
                    ]
                },
                CallOptions(),
            )
        )


def test_stream_uses_effective_model_capabilities() -> None:
    model = Model(
        id="image-model",
        provider="custom",
        endpoint="faux",
        api="faux",
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(input=("text", "image"), stream=True),
    )
    provider = _Provider()
    _test_registry_with(provider)

    async def _run() -> None:
        event_stream = await stream(
            model,
            {
                "messages": [
                    UserMessage(
                        role="user",
                        content=[
                            ImagePart(
                                type="image",
                                data="aGVsbG8=",
                                mime_type="image/png",
                            )
                        ],
                        timestamp=0.0,
                    )
                ]
            },
            CallOptions(),
        )
        await event_stream.result()

    asyncio.run(_run())

    _assert_normalized_provider_context(provider.context)


def test_stream_normalizes_context_against_effective_model_api() -> None:
    model = Model(
        id="anthropic-model",
        provider="anthropic",
        endpoint="anthropic-messages",
        api="anthropic-messages",
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
        capabilities=Capabilities(input=("text",), stream=True),
    )
    provider = _Provider(api="anthropic-messages")
    _test_registry_with(provider)
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call.1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
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

    asyncio.run(
        stream(
            model,
            {
                "messages": [
                    assistant,
                    ToolResultMessage(
                        role="toolResult",
                        tool_call_id="call.1",
                        tool_name="calc",
                        content=[],
                        is_error=False,
                        timestamp=0.0,
                    ),
                ]
            },
            CallOptions(),
        )
    )

    normalized_assistant = provider.context.messages[0]
    normalized_tool_result = provider.context.messages[1]
    assert normalized_assistant.content[0].id == "call_1"
    assert normalized_tool_result.tool_call_id == "call_1"


def test_stream_public_path_uses_openai_completions_typed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    registry = _empty_test_registry()
    registry.register_api_adapter(OpenAIChatCompletionsAdapter())
    model = SimpleNamespace(
        id="gpt-test",
        provider_id="custom",
        endpoint_id="openai-completions",
        input=("text",),
        pricing=None,
    )
    request = _provider_request(
        provider="custom",
        endpoint="openai-completions",
        api="openai-completions",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAICompletionsConfig(
            max_output_tokens_field="max_completion_tokens",
        ),
        max_tokens=128,
        capabilities=Capabilities(
            input=("text",), stream=True, tool_use=True, max_tokens=4096
        ),
    )

    def _resolve_request(_model, options=None):
        return request

    monkeypatch.setattr(
        "loushang.ai.api.streaming.resolve_request_for_model",
        _resolve_request,
    )

    async def _run() -> None:
        event_stream = await stream(
            model,
            {
                "messages": [UserMessage(role="user", content="hello", timestamp=0.0)],
                "tools": [
                    {
                        "name": "calc",
                        "description": "Calculate values",
                        "parameters": {"type": "object"},
                    }
                ],
            },
            CallOptions(
                cache_retention="short",
                cache_key="session-public",
            ),
        )
        await event_stream.result()

    asyncio.run(_run())

    assert _FakeAsyncOpenAI.last_create_kwargs["max_completion_tokens"] == 128
    assert "max_tokens" not in _FakeAsyncOpenAI.last_create_kwargs
    assert "prompt_cache_key" not in _FakeAsyncOpenAI.last_create_kwargs
    assert "tool_stream" not in _FakeAsyncOpenAI.last_create_kwargs
    assert _FakeAsyncOpenAI.last_create_kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "calc",
                "description": "Calculate values",
                "parameters": {"type": "object"},
                "strict": False,
            },
        }
    ]


def test_stream_missing_base_url_fails_before_sdk_client_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    registry = _empty_test_registry()
    registry.register_api_adapter(OpenAIChatCompletionsAdapter())
    model = Model(
        id="missing-base-url",
        provider="custom",
        endpoint="openai-completions",
        api="openai-completions",
        auth=Auth(kind="apiKey", header="Authorization", prefix="Bearer "),
        capabilities=Capabilities(input=("text",), stream=True),
        adapter=OpenAICompletionsConfig(),
    )

    async def _run() -> None:
        await stream(
            model,
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(auth=ApiKeyAuth("must-not-reach-sdk")),
        )

    with pytest.raises(ValueError, match="no configured provider base URL"):
        asyncio.run(_run())

    assert _FakeAsyncOpenAI.last_init_kwargs == {}


def test_stream_public_path_uses_openai_responses_typed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    registry = _empty_test_registry()
    registry.register_api_adapter(OpenAIResponsesAdapter())
    model = SimpleNamespace(
        id="gpt-test",
        api="anthropic-messages",
        provider_id="custom",
        endpoint_id="openai-responses",
        input=("text",),
        pricing=None,
    )
    request = _provider_request(
        provider="custom",
        endpoint="openai-responses",
        api="openai-responses",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAIResponsesConfig(
            developer_role=False,
            long_cache_retention=False,
            prompt_cache_key=True,
        ),
        max_tokens=128,
        capabilities=Capabilities(
            input=("text",),
            stream=True,
            tool_use=True,
            reasoning=True,
            max_tokens=4096,
        ),
    )

    def _resolve_request(_model, options=None):
        return request

    monkeypatch.setattr(
        "loushang.ai.api.streaming.resolve_request_for_model",
        _resolve_request,
    )

    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="custom",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id="resp_1",
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="calc",
        content=[TextPart(type="text", text="42")],
        is_error=False,
        timestamp=0.0,
    )

    async def _run() -> None:
        event_stream = await stream(
            model,
            {
                "system_prompt": "Use system instructions.",
                "messages": [
                    assistant,
                    tool_result,
                    UserMessage(role="user", content="next", timestamp=0.0),
                ],
                "tools": [
                    Tool(
                        name="calc",
                        description="Calculate values",
                        parameters={"type": "object"},
                    )
                ],
            },
            CallOptions(
                cache_retention="short",
                cache_key="session-responses",
            ),
        )
        await event_stream.result()

    asyncio.run(_run())

    assert _FakeAsyncOpenAI.last_create_kwargs["max_output_tokens"] == 128
    assert _FakeAsyncOpenAI.last_create_kwargs["input"] == [
        {"role": "system", "content": "Use system instructions."},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "calc",
            "arguments": '{"x": 1}',
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "42"},
        {"role": "user", "content": [{"type": "input_text", "text": "next"}]},
    ]
    assert _FakeAsyncOpenAI.last_create_kwargs["tools"] == [
        {
            "type": "function",
            "name": "calc",
            "description": "Calculate values",
            "parameters": {"type": "object"},
        }
    ]
    assert _FakeAsyncOpenAI.last_create_kwargs["prompt_cache_key"] == (
        "session-responses"
    )
    assert "prompt_cache_retention" not in _FakeAsyncOpenAI.last_create_kwargs
    headers = _FakeAsyncOpenAI.last_create_kwargs.get("extra_headers") or {}
    assert "session_id" not in headers
    assert "x-client-request-id" not in headers


def test_stream_public_path_rejects_unsupported_long_cache_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    registry = _empty_test_registry()
    registry.register_api_adapter(OpenAIResponsesAdapter())
    model = SimpleNamespace(
        id="gpt-test",
        provider_id="custom",
        endpoint_id="openai-responses",
        input=("text",),
        pricing=None,
    )
    request = _provider_request(
        provider="custom",
        endpoint="openai-responses",
        api="openai-responses",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAIResponsesConfig(
            long_cache_retention=False,
            prompt_cache_key=True,
        ),
        capabilities=Capabilities(input=("text",), stream=True, max_tokens=4096),
    )

    def _resolve_request(_model, options=None):
        return request

    monkeypatch.setattr(
        "loushang.ai.api.streaming.resolve_request_for_model",
        _resolve_request,
    )

    async def _run() -> None:
        await stream(
            model,
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(cache_retention="long"),
        )

    with pytest.raises(UnsupportedCapabilityError, match="long cache retention"):
        asyncio.run(_run())


def test_stream_public_path_ignores_unsupported_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _empty_test_registry()
    provider = _Provider(api="openai-completions")
    registry.register_api_adapter(provider)
    model = SimpleNamespace(
        id="gpt-test",
        provider_id="custom",
        endpoint_id="openai-completions",
        input=("text",),
        pricing=None,
    )
    request = _provider_request(
        provider="custom",
        endpoint="openai-completions",
        api="openai-completions",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAICompletionsConfig(),
        capabilities=Capabilities(input=("text",), stream=True, max_tokens=4096),
    )

    def _resolve_request(_model, options=None):
        return request

    monkeypatch.setattr(
        "loushang.ai.api.streaming.resolve_request_for_model",
        _resolve_request,
    )

    async def _run() -> None:
        event_stream = await stream(
            model,
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(cache_key="session-public"),
        )
        await event_stream.result()

    asyncio.run(_run())

    assert isinstance(provider.options, CallOptions)
    assert provider.options.cache_key is None


def test_stream_public_path_uses_adapter_protocol_override_for_cache_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    registry = _empty_test_registry()
    registry.register_api_adapter(OpenAIResponsesAdapter())
    model = SimpleNamespace(
        id="gpt-test",
        provider_id="custom",
        endpoint_id="openai-responses",
        input=("text",),
        pricing=None,
    )
    request = _provider_request(
        provider="custom",
        endpoint="openai-responses",
        api="openai-responses",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAIResponsesConfig(
            long_cache_retention=True,
            prompt_cache_key=True,
        ),
        capabilities=Capabilities(input=("text",), stream=True, max_tokens=4096),
    )

    def _resolve_request(_model, options=None):
        return request

    monkeypatch.setattr(
        "loushang.ai.api.streaming.resolve_request_for_model",
        _resolve_request,
    )

    async def _run() -> None:
        event_stream = await stream(
            model,
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(
                cache_retention="long",
                cache_key="session-override",
            ),
        )
        await event_stream.result()

    asyncio.run(_run())

    assert _FakeAsyncOpenAI.last_create_kwargs["prompt_cache_key"] == "session-override"
    assert _FakeAsyncOpenAI.last_create_kwargs["prompt_cache_retention"] == "24h"


def _patch_resolved_request(
    monkeypatch: pytest.MonkeyPatch,
    *,
    capabilities: Capabilities | None = None,
    api: str = "faux",
    provider: str = "faux",
) -> None:
    def _resolve_request(_model, options=None):
        reasoning_enabled = None
        if options is not None and getattr(options, "reasoning", None) is not None:
            reasoning_enabled = is_reasoning_requested(options)
        return _provider_request(
            api=api,
            provider=provider,
            endpoint=api,
            base_url=None,
            model_id=getattr(_model, "id", "test-model"),
            options=options,
            capabilities=capabilities or Capabilities(input=("text",), stream=True),
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=(
                get_reasoning_effort(options) if reasoning_enabled is True else None
            ),
            temperature=(
                getattr(options, "temperature", None) if options is not None else None
            ),
        )

    monkeypatch.setattr(
        "loushang.ai.api.streaming.resolve_request_for_model",
        _resolve_request,
    )


def _provider_request(
    *,
    provider: str,
    endpoint: str,
    api: str,
    base_url: str | None,
    model_id: str = "gpt-test",
    capabilities: Capabilities | None = None,
    adapter_config: object | None = None,
    **kwargs: object,
) -> ProviderRequest:
    resolved_capabilities = capabilities or Capabilities(input=("text",), stream=True)
    resolved_base_url = base_url or "https://provider.test/v1"
    model = Model(
        id=model_id,
        provider=provider,
        endpoint=endpoint,
        api=api,
        base_url=resolved_base_url,
        auth=Auth(kind="none"),
        capabilities=resolved_capabilities,
        adapter=adapter_config,  # type: ignore[arg-type]
    )
    request_values = dict(kwargs)
    if "max_tokens" in request_values:
        request_values["max_output_tokens"] = request_values.pop("max_tokens")
    request_values.setdefault("context", NormalizedContext(system_prompt=None))
    request_values.setdefault("options", None)
    return ProviderRequest(
        model=model,
        base_url=resolved_base_url,
        **request_values,  # type: ignore[arg-type]
    )


def _fake_openai_module(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncOpenAI.last_init_kwargs = {}
    _FakeAsyncOpenAI.last_create_kwargs = {}
    _FakeAsyncOpenAI.chunks = [
        SimpleNamespace(
            id="chatcmpl_public",
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )
    ]
    _FakeAsyncOpenAI.events = [
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                status="completed",
                usage=SimpleNamespace(
                    input_tokens=1,
                    output_tokens=1,
                    total_tokens=2,
                    input_tokens_details=SimpleNamespace(cached_tokens=0),
                ),
            ),
        )
    ]
    module = ModuleType("openai")
    module.AsyncOpenAI = _FakeAsyncOpenAI
    module.Omit = _FakeOmit
    monkeypatch.setitem(sys.modules, "openai", module)


class _FakeOmit:
    pass


class _FakeAsyncOpenAI:
    last_init_kwargs: dict[str, object] = {}
    last_create_kwargs: dict[str, object] = {}
    chunks: list[object] = []
    events: list[object] = []

    def __init__(self, **kwargs) -> None:
        type(self).last_init_kwargs = kwargs
        self.chat = SimpleNamespace(completions=_FakeCompletions(type(self)))
        self.responses = _FakeResponses(type(self))


class _FakeCompletions:
    def __init__(self, owner: type[_FakeAsyncOpenAI]) -> None:
        self._owner = owner

    async def create(self, **kwargs):
        self._owner.last_create_kwargs = kwargs
        return _FakeStream(self._owner.chunks)


class _FakeResponses:
    def __init__(self, owner: type[_FakeAsyncOpenAI]) -> None:
        self._owner = owner

    async def create(self, **kwargs):
        self._owner.last_create_kwargs = kwargs
        return _FakeStream(self._owner.events)


class _FakeStream:
    def __init__(self, chunks: list[object]) -> None:
        self._iterator = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc
