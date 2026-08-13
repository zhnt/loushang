"""Shared lifecycle for providers contributed by an extension."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loushang.ai.api_registry import APIRegistry
from loushang.ai.model import Provider

ProviderFactory = Callable[..., Provider]


@dataclass
class ExtensionProviderRuntime:
    """Own provider registration lifecycle while Product supplies conversion."""

    model_registry: object | None
    api_registry: APIRegistry
    provider_factory: ProviderFactory

    def register_provider(self, name: str, config: object) -> None:
        registrar = getattr(self.model_registry, "register_provider", None)
        if not callable(registrar):
            return
        registrar(
            self.provider_factory(
                name,
                config,
                existing_provider=self.get_registered_provider(name),
            )
        )

    def unregister_provider(self, name: str) -> None:
        remover = getattr(self.model_registry, "unregister_provider", None)
        if callable(remover):
            remover(name)
        self.api_registry.unregister_api_adapters(f"provider:{name}")

    def get_registered_provider(self, name: str) -> Provider | None:
        ai_registry = getattr(self.model_registry, "ai_registry", None)
        getter = getattr(ai_registry, "get_provider", None)
        if not callable(getter):
            return None
        return getter(name)


__all__ = ["ExtensionProviderRuntime", "ProviderFactory"]
