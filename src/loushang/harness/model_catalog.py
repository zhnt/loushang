"""Layered model catalog operations shared by product runtimes."""

from __future__ import annotations

from dataclasses import replace
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

log = get_log(__name__).bind(component="ModelCatalog")


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
        providers = _registry_provider_snapshot(self._ai_registry)
        providers[provider.id] = provider
        self._replace_ai_registry(AiModelRegistry.from_providers(providers))

    def unregister_provider(self, provider_id: str) -> None:
        providers = _registry_provider_snapshot(self._ai_registry)
        providers.pop(provider_id, None)
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
