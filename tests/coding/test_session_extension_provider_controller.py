from __future__ import annotations

import asyncio

import pytest

from loushang.ai.api_registry import APIRegistry
from loushang.ai.model import Endpoint, Model, Provider
from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
from loushang.harness.extensions import ExtensionProviderRuntime
from loushang.harness.extensions.provider_config import (
    provider_from_extension_config,
)
from loushang.harness.model_catalog import ModelCatalog as ModelRegistry
from loushang.harness.runtime import RegistrationOwner, RegistrationScope


class _APIAdapter:
    api = "proxy-api"

    async def invoke_raw(self, request):
        del request
        await asyncio.sleep(0)
        yield {"type": "response_done"}

    async def stream_simple(self, model, context, options, request):
        return await asyncio.sleep(0)


def test_extension_provider_controller_registers_native_provider_against_existing_provider() -> (
    None
):
    ai_registry = AiModelRegistry.from_providers(
        {
            "proxy": Provider(
                id="proxy",
                name="Existing Proxy",
                endpoints={
                    "proxy-simple": Endpoint(
                        id="proxy-simple",
                        provider="proxy",
                        api="proxy-api",
                        base_url="https://old.example.com",
                        models={
                            "old-model": Model(
                                id="old-model",
                                provider="proxy",
                                endpoint="proxy-simple",
                                name="Old Model",
                            ),
                        },
                    )
                },
            )
        }
    )
    model_registry = ModelRegistry(ai_registry=ai_registry)
    controller = ExtensionProviderRuntime(
        model_registry=model_registry,
        api_registry=APIRegistry(),
        provider_factory=provider_from_extension_config,
    )

    controller.register_provider(
        "proxy",
        {
            "website": "https://proxy.example.com",
            "endpoints": {
                "proxy-simple": {
                    "baseUrl": "https://new.example.com",
                },
                "proxy-advanced": {
                    "api": "proxy-api",
                    "models": {
                        "new-model": {
                            "displayName": "New Model",
                            "input": ["text", "image"],
                            "reasoning": True,
                        }
                    },
                },
            },
        },
    )

    current = model_registry.ai_registry
    provider = current.get_provider("proxy")
    assert provider is not None
    assert provider.name == "Existing Proxy"
    assert provider.website == "https://proxy.example.com"
    endpoint = current.get_endpoint("proxy", "proxy-simple")
    assert endpoint is not None
    assert endpoint.api == "proxy-api"
    assert endpoint.base_url == "https://new.example.com"
    assert current.get_model("proxy", "proxy-simple", "old-model").name == "Old Model"
    new_model = current.get_model("proxy", "proxy-advanced", "new-model")
    assert new_model.name == "New Model"
    assert new_model.supports_image_input is True
    assert new_model.supports_thinking is True


def test_extension_provider_controller_registers_canonical_endpoint_auth() -> None:
    ai_registry = AiModelRegistry()
    model_registry = ModelRegistry(ai_registry=ai_registry)
    controller = ExtensionProviderRuntime(
        model_registry=model_registry,
        api_registry=APIRegistry(),
        provider_factory=provider_from_extension_config,
    )

    controller.register_provider(
        "proxy",
        {
            "endpoints": {
                "proxy-simple": {
                    "api": "proxy-api",
                    "auth": {
                        "kind": "apiKey",
                        "apiKeyEnv": "PROXY_API_KEY",
                    },
                }
            },
        },
    )

    endpoint = model_registry.ai_registry.get_endpoint("proxy", "proxy-simple")
    assert endpoint is not None
    assert endpoint.auth is not None
    assert endpoint.auth.api_key_env == "PROXY_API_KEY"


def test_extension_provider_controller_unregisters_provider_and_source_registrations() -> (
    None
):
    ai_registry = AiModelRegistry({"proxy": Provider(id="proxy")})
    api_registry = APIRegistry()
    model_registry = ModelRegistry(ai_registry=ai_registry)
    api_registry.register_api_adapter(_APIAdapter(), source_id="provider:proxy")
    controller = ExtensionProviderRuntime(
        model_registry=model_registry,
        api_registry=api_registry,
        provider_factory=provider_from_extension_config,
    )

    controller.unregister_provider("proxy")

    assert model_registry.ai_registry.get_provider("proxy") is None
    assert api_registry.list_api_adapters() == []


def test_extension_provider_controller_rejects_pi_style_provider_config() -> None:
    controller = ExtensionProviderRuntime(
        model_registry=ModelRegistry(ai_registry=AiModelRegistry()),
        api_registry=APIRegistry(),
        provider_factory=provider_from_extension_config,
    )

    with pytest.raises(ValueError, match="pi-style flat provider config"):
        controller.register_provider(
            "proxy",
            {
                "api": "proxy-api",
                "baseUrl": "https://proxy.example.com",
                "models": [{"id": "proxy-model"}],
            },
        )


def test_staged_provider_updates_reduce_in_same_owner_call_order() -> None:
    model_registry = ModelRegistry(ai_registry=AiModelRegistry())

    def merge_provider(
        name: str,
        config: object,
        *,
        existing_provider: Provider | None,
    ) -> Provider:
        assert isinstance(config, dict)
        return Provider(
            id=name,
            name=str(config.get("name") or getattr(existing_provider, "name", "")),
            website=str(
                config.get("website") or getattr(existing_provider, "website", "")
            ),
        )

    controller = ExtensionProviderRuntime(
        model_registry=model_registry,
        api_registry=APIRegistry(),
        provider_factory=merge_provider,
    )
    owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="models",
        runtime_id="session-1",
        generation=1,
    )
    first = controller.stage_provider("proxy", {"name": "First"}, owner)
    second = controller.stage_provider(
        "proxy",
        {"website": "https://proxy.example.com"},
        owner,
    )
    scope = RegistrationScope(owner)
    scope.add(first)
    scope.add(second)
    scope.commit()

    provider = model_registry.ai_registry.get_provider("proxy")
    assert provider is not None
    assert provider.name == "First"
    assert provider.website == "https://proxy.example.com"


def test_staged_provider_register_after_removal_starts_from_empty_state() -> None:
    baseline = Provider(id="proxy", name="Baseline")
    model_registry = ModelRegistry(
        ai_registry=AiModelRegistry.from_providers({"proxy": baseline})
    )
    inherited: list[Provider | None] = []

    def replace_provider(
        name: str,
        config: object,
        *,
        existing_provider: Provider | None,
    ) -> Provider:
        assert isinstance(config, dict)
        inherited.append(existing_provider)
        return Provider(id=name, name=str(config["name"]))

    controller = ExtensionProviderRuntime(
        model_registry=model_registry,
        api_registry=APIRegistry(),
        provider_factory=replace_provider,
    )
    owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="models",
        runtime_id="session-1",
        generation=1,
    )
    removal = controller.stage_provider_removal("proxy", owner)
    replacement = controller.stage_provider("proxy", {"name": "Replacement"}, owner)
    scope = RegistrationScope(owner)
    scope.add(removal)
    scope.add(replacement)
    scope.commit()

    assert inherited == [None]
    assert model_registry.ai_registry.get_provider("proxy") == Provider(
        id="proxy",
        name="Replacement",
    )


def test_staged_provider_removal_masks_and_restores_source_api_adapters() -> None:
    baseline = Provider(id="proxy", name="Baseline")
    model_registry = ModelRegistry(
        ai_registry=AiModelRegistry.from_providers({"proxy": baseline})
    )
    api_registry = APIRegistry()
    adapter = _APIAdapter()
    api_registry.register_api_adapter(adapter, source_id="provider:proxy")
    controller = ExtensionProviderRuntime(
        model_registry=model_registry,
        api_registry=api_registry,
        provider_factory=provider_from_extension_config,
    )
    owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="models",
        runtime_id="session-1",
        generation=1,
    )
    removal = controller.stage_provider_removal("proxy", owner)

    assert api_registry.list_api_adapters() == [adapter]
    removal.activate()
    assert model_registry.ai_registry.get_provider("proxy") is None
    assert api_registry.list_api_adapters() == []
    removal.deactivate()
    assert model_registry.ai_registry.get_provider("proxy") == baseline
    assert api_registry.list_api_adapters() == [adapter]
    removal.activate()
    assert removal.rollback_registration().state == "removed"
    assert model_registry.ai_registry.get_provider("proxy") == baseline
    assert api_registry.list_api_adapters() == [adapter]
