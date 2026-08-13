from __future__ import annotations

import importlib.util

import pytest

from loushang.ai.api_registry import APIRegistry
from loushang.ai.bootstrap import register_builtin_api_adapters
from loushang.ai.provider import ProviderRequest, ProviderRequestValidator
from loushang.ai.provider_registry import ProviderRegistry


class _Adapter:
    api = "custom"

    async def invoke_raw(self, request):
        del request
        yield {"type": "response_done"}


class _ValidatingAdapter(_Adapter):
    def __init__(self) -> None:
        self.validated_requests: list[ProviderRequest] = []

    def validate_request(self, request: ProviderRequest) -> None:
        self.validated_requests.append(request)


class _MissingAPIAdapter:
    async def invoke_raw(self, request):
        del request
        yield {"type": "response_done"}


class _MissingInvokeRawAdapter:
    api = "missing-stream"


class _NonCallableInvokeRawAdapter:
    api = "non-callable"
    invoke_raw = object()


class _NonCallableRequestValidatorAdapter(_Adapter):
    validate_request = object()


class _InvalidRequestValidatorSignatureAdapter(_Adapter):
    def validate_request(self) -> None:
        return None


def test_api_registry_manages_adapters_by_source() -> None:
    registry = APIRegistry()
    adapter = _Adapter()
    other = _Adapter()
    other.api = "other"

    registry.register_api_adapter(adapter, source_id="plugin-a")
    registry.register_api_adapter(other, source_id="plugin-b")

    assert registry.get_api_adapter("custom") is adapter
    assert {item.api for item in registry.list_api_adapters()} == {"custom", "other"}

    registry.unregister_api_adapters("plugin-a")

    assert {item.api for item in registry.list_api_adapters()} == {"other"}

    registry.clear_api_adapters()

    assert registry.list_api_adapters() == []


@pytest.mark.parametrize(
    ("adapter", "message"),
    [
        (_MissingAPIAdapter(), "api"),
        (_MissingInvokeRawAdapter(), "invoke_raw"),
        (_NonCallableInvokeRawAdapter(), "callable"),
    ],
)
def test_api_registry_rejects_invalid_adapter_shape(
    adapter: object,
    message: str,
) -> None:
    registry = APIRegistry()

    with pytest.raises(TypeError, match=message):
        registry.register_api_adapter(adapter)  # type: ignore[arg-type]


def test_api_registry_accepts_typed_request_validator() -> None:
    registry = APIRegistry()
    adapter = _ValidatingAdapter()

    registry.register_api_adapter(adapter)

    registered = registry.get_api_adapter("custom")
    assert registered is adapter
    assert isinstance(registered, ProviderRequestValidator)


@pytest.mark.parametrize(
    ("adapter", "message"),
    [
        (_NonCallableRequestValidatorAdapter(), "validate_request must be callable"),
        (
            _InvalidRequestValidatorSignatureAdapter(),
            "validate_request must accept exactly one ProviderRequest",
        ),
    ],
)
def test_api_registry_rejects_invalid_request_validator_shape(
    adapter: object,
    message: str,
) -> None:
    registry = APIRegistry()

    with pytest.raises(TypeError, match=message):
        registry.register_api_adapter(adapter)  # type: ignore[arg-type]


def test_register_builtin_api_adapters_registers_only_core_protocol_adapters() -> None:
    registry = APIRegistry()

    register_builtin_api_adapters(registry)

    assert {adapter.api for adapter in registry.list_api_adapters()} == {
        "anthropic-messages",
        "openai-completions",
        "openai-responses",
    }


def test_provider_registry_prefers_vendor_adapter_then_uses_api_fallback() -> None:
    api_registry = APIRegistry()
    generic_adapter = _Adapter()
    vendor_adapter = _Adapter()
    api_registry.register_api_adapter(generic_adapter)
    registry = ProviderRegistry(api_registry)
    registry.register_provider_adapter("vendor", "custom", vendor_adapter)

    assert registry.resolve_api_adapter("vendor", "custom") is vendor_adapter
    assert registry.resolve_api_adapter("other", "custom") is generic_adapter


def test_azure_openai_provider_module_is_not_in_core() -> None:
    assert (
        importlib.util.find_spec("loushang.ai.protocols.azure_openai_responses") is None
    )


def test_bedrock_provider_module_is_not_in_core() -> None:
    assert importlib.util.find_spec("loushang.ai.protocols.bedrock_converse") is None
