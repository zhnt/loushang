"""Shared lifecycle for providers contributed by an extension."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loushang.ai.api_registry import APIRegistry, DetachedAPIAdapters
from loushang.ai.model import Provider
from loushang.harness.runtime.registration import (
    RegistrationDisposalResult,
    RegistrationLease,
    RegistrationOwner,
)

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

    def bind_provider(
        self,
        name: str,
        config: object,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        registrar = getattr(self.model_registry, "bind_provider", None)
        if not callable(registrar):
            raise RuntimeError("Model registry does not support live Provider binding")
        provider = self.provider_factory(
            name,
            config,
            existing_provider=self.get_owner_provider(name, owner=owner),
        )
        lease = registrar(provider, owner=owner)
        if not isinstance(lease, RegistrationLease):
            raise TypeError("live Provider binding must return a RegistrationLease")
        return lease

    def stage_provider(
        self,
        name: str,
        config: object,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        registrar = getattr(self.model_registry, "stage_provider", None)
        if not callable(registrar):
            raise RuntimeError("Model registry does not support staged Provider binding")
        provider = self.provider_factory(
            name,
            config,
            existing_provider=self.get_owner_provider(name, owner=owner),
        )
        lease = registrar(provider, owner=owner)
        if not isinstance(lease, RegistrationLease):
            raise TypeError("staged Provider binding must return a RegistrationLease")
        return lease

    def bind_provider_removal(
        self,
        name: str,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        registrar = getattr(self.model_registry, "bind_provider_removal", None)
        if not callable(registrar):
            raise RuntimeError(
                "Model registry does not support owner-scoped Provider removal"
            )
        lease = registrar(name, owner=owner)
        if not isinstance(lease, RegistrationLease):
            raise TypeError("live Provider removal must return a RegistrationLease")
        return self._provider_removal_lease(name, lease, staged=False)

    def _provider_removal_lease(
        self,
        name: str,
        lease: RegistrationLease,
        *,
        staged: bool,
    ) -> RegistrationLease:
        detached: DetachedAPIAdapters | None = None

        def detach_adapters() -> None:
            nonlocal detached
            detached = self.api_registry.detach_api_adapters(f"provider:{name}")

        def restore_adapters() -> None:
            nonlocal detached
            if detached is not None:
                detached.restore()
                detached = None

        async def dispose_removal() -> RegistrationDisposalResult:
            restore_adapters()
            return await lease.dispose()

        def activate_removal() -> None:
            lease.activate()
            try:
                detach_adapters()
            except BaseException:
                lease.deactivate()
                raise

        def deactivate_removal() -> None:
            restore_adapters()
            lease.deactivate()

        def rollback_removal() -> RegistrationDisposalResult:
            restore_adapters()
            return lease.rollback_registration()

        if not staged:
            detach_adapters()
        return RegistrationLease(
            owner=lease.owner,
            identity=lease.identity,
            dispose=dispose_removal,
            activate=activate_removal if staged else None,
            deactivate=deactivate_removal if staged else None,
            rollback=rollback_removal,
        )

    def get_owner_provider(
        self,
        name: str,
        *,
        owner: RegistrationOwner,
    ) -> Provider | None:
        getter = getattr(self.model_registry, "get_owner_provider_state", None)
        if callable(getter):
            found, provider = getter(name, owner=owner)
            if found:
                return provider
        return self.get_registered_provider(name)

    def stage_provider_removal(
        self,
        name: str,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        registrar = getattr(self.model_registry, "stage_provider_removal", None)
        if not callable(registrar):
            raise RuntimeError(
                "Model registry does not support staged Provider removal"
            )
        lease = registrar(name, owner=owner)
        if not isinstance(lease, RegistrationLease):
            raise TypeError("staged Provider removal must return a RegistrationLease")
        return self._provider_removal_lease(name, lease, staged=True)

    def get_registered_provider(self, name: str) -> Provider | None:
        ai_registry = getattr(self.model_registry, "ai_registry", None)
        getter = getattr(ai_registry, "get_provider", None)
        if not callable(getter):
            return None
        return getter(name)


__all__ = ["ExtensionProviderRuntime", "ProviderFactory"]
