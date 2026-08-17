"""Layered model catalog operations shared by product runtimes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from loushang.ai.model.domain import (
    Endpoint,
    Model,
    Provider,
)
from loushang.ai.model.loader import (
    _combine_model_registries,
    load_builtin_model_registry,
    load_model_registry_from_directory,
)
from loushang.ai.model.registry import (
    ModelRegistry as AiModelRegistry,
)
from loushang.ai.model.registry import (
    get_default_model_registry,
    resolve_model_ref,
)
from loushang.ai.model.selection import ModelSelection
from loushang.foundation.observability import get_log
from loushang.harness.runtime.registration import (
    RegistrationDisposalResult,
    RegistrationIdentity,
    RegistrationLease,
    RegistrationOwner,
)

log = get_log(__name__).bind(component="ModelCatalog")


@dataclass(frozen=True)
class _ProviderLayer:
    owner: RegistrationOwner
    identity: RegistrationIdentity
    provider: Provider | None
    published: bool = True


def _registry_provider_snapshot(
    registry: AiModelRegistry,
) -> dict[str, Provider]:
    return registry.providers


class ModelCatalog:
    """Product-neutral model catalog facade over the AI model registry.

    The catalog owns layered loading and model reference resolution. Products
    provide preferences and presentation, while provider/model facts remain in
    ``loushang.ai``.
    """

    def __init__(self, ai_registry: AiModelRegistry | None = None) -> None:
        self._ai_registry = (
            ai_registry if ai_registry is not None else get_default_model_registry()
        )
        self._provider_layers: dict[str, list[_ProviderLayer]] = {}
        self._provider_baselines: dict[str, Provider | None] = {}

    @property
    def ai_registry(self) -> AiModelRegistry:
        return self._ai_registry

    def _replace_ai_registry(self, registry: AiModelRegistry) -> None:
        self._ai_registry = registry

    def reload(
        self,
        *,
        user_dir: Path | None = None,
        project_dir: Path | None = None,
    ) -> None:
        sources = [("<builtin>", load_builtin_model_registry().providers)]
        for path in (user_dir, project_dir):
            if path is not None and path.is_dir():
                sources.append(
                    (str(path), load_model_registry_from_directory(path).providers)
                )
        self._replace_ai_registry(_combine_model_registries(sources))
        self._provider_layers.clear()
        self._provider_baselines.clear()

    def reload_if_project_layer(
        self,
        *,
        project_dir: str | Path,
        user_dir: str | Path | None = None,
    ) -> bool:
        """Reload layered models only when a project layer exists."""

        resolved_project_dir = Path(project_dir).expanduser()
        if not resolved_project_dir.is_dir():
            return False
        resolved_user_dir = (
            Path(user_dir).expanduser() if user_dir is not None else None
        )
        self.reload(
            user_dir=(
                resolved_user_dir
                if resolved_user_dir is not None and resolved_user_dir.is_dir()
                else None
            ),
            project_dir=resolved_project_dir,
        )
        return True

    def register_model(self, model: Model) -> None:
        providers = _registry_provider_snapshot(self._ai_registry)
        provider = providers.get(model.provider_id) or Provider(id=model.provider_id)
        endpoint = provider.endpoints.get(model.endpoint_id) or Endpoint(
            id=model.endpoint_id,
            provider=model.provider_id,
            api=model.api or model.endpoint_id,
            base_url=model.base_url,
            base_url_env=model.base_url_env,
            region=model.region,
            lane=model.lane,
            preferred=model.preferred_endpoint,
            adapter=model.adapter,
            defaults=model.defaults,
        )
        models = dict(endpoint.models)
        models[model.id] = model
        endpoints = dict(provider.endpoints)
        endpoints[endpoint.id] = replace(endpoint, models=models)
        providers[provider.id] = replace(provider, endpoints=endpoints)
        self._replace_ai_registry(AiModelRegistry.from_providers(providers))

    def register_provider(self, provider: Provider) -> None:
        self._provider_layers.pop(provider.id, None)
        self._provider_baselines.pop(provider.id, None)
        providers = _registry_provider_snapshot(self._ai_registry)
        providers[provider.id] = provider
        self._replace_ai_registry(AiModelRegistry.from_providers(providers))

    def unregister_provider(self, provider_id: str) -> None:
        self._provider_layers.pop(provider_id, None)
        self._provider_baselines.pop(provider_id, None)
        providers = _registry_provider_snapshot(self._ai_registry)
        providers.pop(provider_id, None)
        self._replace_ai_registry(AiModelRegistry.from_providers(providers))

    def bind_provider(
        self,
        provider: Provider,
        *,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        """Bind one exact Provider layer and restore the prior winner on removal."""

        return self._bind_provider(provider, owner=owner, published=True)

    def stage_provider(
        self,
        provider: Provider,
        *,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        """Add an invisible Provider layer activated by its registration scope."""

        return self._bind_provider(provider, owner=owner, published=False)

    def bind_provider_removal(
        self,
        provider_id: str,
        *,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        """Bind an owner-scoped tombstone without deleting another owner's layer."""

        return self._bind_provider_layer(
            provider_id,
            None,
            owner=owner,
            published=True,
        )

    def stage_provider_removal(
        self,
        provider_id: str,
        *,
        owner: RegistrationOwner,
    ) -> RegistrationLease:
        """Stage an invisible owner-scoped Provider tombstone."""

        return self._bind_provider_layer(
            provider_id,
            None,
            owner=owner,
            published=False,
        )

    def _bind_provider(
        self,
        provider: Provider,
        *,
        owner: RegistrationOwner,
        published: bool,
    ) -> RegistrationLease:
        if not isinstance(provider, Provider):
            raise TypeError("ModelCatalog.bind_provider expects a Provider")
        if not isinstance(owner, RegistrationOwner):
            raise TypeError("ModelCatalog.bind_provider owner must be a RegistrationOwner")
        return self._bind_provider_layer(
            provider.id,
            provider,
            owner=owner,
            published=published,
        )

    def _bind_provider_layer(
        self,
        provider_id: str,
        provider: Provider | None,
        *,
        owner: RegistrationOwner,
        published: bool,
    ) -> RegistrationLease:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("Provider id must be a non-empty string")
        layers = self._provider_layers.get(provider_id)
        if layers is None:
            layers = []
            self._provider_layers[provider_id] = layers
            self._provider_baselines[provider_id] = self._ai_registry.get_provider(
                provider_id
            )
        identity = RegistrationIdentity.create(
            surface="model_provider",
            public_key=provider_id,
        )
        layers.append(
            _ProviderLayer(
                owner=owner,
                identity=identity,
                provider=provider,
                published=published,
            )
        )
        if published:
            self._publish_provider(provider_id, provider)
        return RegistrationLease(
            owner=owner,
            identity=identity,
            dispose=lambda: self._remove_bound_provider(
                owner=owner,
                identity=identity,
            ),
            activate=(
                None
                if published
                else lambda: self._set_bound_provider_published(
                    owner=owner,
                    identity=identity,
                    published=True,
                )
            ),
            deactivate=(
                None
                if published
                else lambda: self._set_bound_provider_published(
                    owner=owner,
                    identity=identity,
                    published=False,
                )
            ),
            rollback=lambda: self._remove_bound_provider(
                owner=owner,
                identity=identity,
            ),
        )

    def get_owner_provider_state(
        self,
        provider_id: str,
        *,
        owner: RegistrationOwner,
    ) -> tuple[bool, Provider | None]:
        """Return the last staged or published action for one exact owner."""

        layers = self._provider_layers.get(provider_id, ())
        for layer in reversed(layers):
            if layer.owner == owner:
                return True, layer.provider
        return False, None

    def _remove_bound_provider(
        self,
        *,
        owner: RegistrationOwner,
        identity: RegistrationIdentity,
    ) -> RegistrationDisposalResult:
        provider_id = identity.public_key
        if identity.surface != "model_provider" or provider_id is None:
            return RegistrationDisposalResult(
                state="failed_terminal",
                diagnostic_code="provider_registration_identity_invalid",
            )
        layers = self._provider_layers.get(provider_id)
        if layers is None:
            return RegistrationDisposalResult(state="already_removed")
        for index, layer in enumerate(layers):
            if layer.identity.registration_id != identity.registration_id:
                continue
            if layer.owner != owner:
                return RegistrationDisposalResult(
                    state="failed_terminal",
                    diagnostic_code="provider_registration_owner_mismatch",
                )
            layers.pop(index)
            published_layer = next(
                (item for item in reversed(layers) if item.published),
                None,
            )
            if published_layer is not None:
                self._publish_provider(provider_id, published_layer.provider)
            else:
                baseline = self._provider_baselines.get(provider_id)
                if not layers:
                    self._provider_baselines.pop(provider_id, None)
                    self._provider_layers.pop(provider_id, None)
                self._publish_provider(provider_id, baseline)
            return RegistrationDisposalResult(state="removed")
        return RegistrationDisposalResult(state="already_removed")

    def _set_bound_provider_published(
        self,
        *,
        owner: RegistrationOwner,
        identity: RegistrationIdentity,
        published: bool,
    ) -> None:
        provider_id = identity.public_key
        layers = self._provider_layers.get(provider_id or "")
        if identity.surface != "model_provider" or provider_id is None or layers is None:
            raise RuntimeError("staged Provider registration is unavailable")
        for index, layer in enumerate(layers):
            if layer.identity.registration_id != identity.registration_id:
                continue
            if layer.owner != owner:
                raise RuntimeError("staged Provider registration owner changed")
            layers[index] = _ProviderLayer(
                owner=layer.owner,
                identity=layer.identity,
                provider=layer.provider,
                published=published,
            )
            effective = next(
                (item for item in reversed(layers) if item.published),
                None,
            )
            self._publish_provider(
                provider_id,
                effective.provider
                if effective is not None
                else self._provider_baselines.get(provider_id),
            )
            return
        raise RuntimeError("staged Provider registration was removed")

    def _publish_provider(
        self,
        provider_id: str,
        provider: Provider | None,
    ) -> None:
        providers = _registry_provider_snapshot(self._ai_registry)
        if provider is None:
            providers.pop(provider_id, None)
        else:
            providers[provider_id] = provider
        self._replace_ai_registry(AiModelRegistry.from_providers(providers))

    def get_model(self, name: str) -> ModelSelection | None:
        try:
            model = resolve_model_ref(self._ai_registry, name)
        except (KeyError, ValueError):
            return None
        return ModelSelection(
            provider=model.provider_id,
            endpoint_id=model.endpoint_id,
            model_id=model.id,
        )

    def list_models(self) -> list[ModelSelection]:
        return [
            ModelSelection(
                provider=model.provider_id,
                endpoint_id=model.endpoint_id,
                model_id=model.id,
            )
            for model in self._ai_registry.list_models()
        ]

    def resolve_model(
        self, selection_input: ModelSelection | str | Model
    ) -> ModelSelection:
        if isinstance(selection_input, ModelSelection):
            return selection_input
        if isinstance(selection_input, Model):
            return ModelSelection(
                provider=selection_input.provider_id,
                endpoint_id=selection_input.endpoint_id,
                model_id=selection_input.id,
            )
        model = resolve_model_ref(self._ai_registry, selection_input)
        return ModelSelection(
            provider=model.provider_id,
            endpoint_id=model.endpoint_id,
            model_id=model.id,
        )

    def build_model(self, selection_input: ModelSelection | str | Model) -> Model:
        selection = self.resolve_model(selection_input)
        return self._resolve_model(selection)

    def _resolve_model(self, selection: ModelSelection) -> Model:
        try:
            return self._ai_registry.resolve_model_selection(selection)
        except KeyError:
            log.problem(
                "model_selection_not_found",
                source="config",
                message=(
                    "Model selection not found: "
                    f"{selection.provider}:{selection.endpoint_id}:{selection.model_id}"
                ),
                recoverable=True,
                provider_id=selection.provider,
                endpoint_id=selection.endpoint_id,
                model_id=selection.model_id,
            )
            raise


__all__ = ["ModelCatalog"]
