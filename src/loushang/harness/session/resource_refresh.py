"""Product-bound session resource refresh coordination.

The runtime owns the ordered refresh pipeline while Products bind resource
loading, settings, runtime discovery, diagnostics, and prompt/tool rebuilding.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from loushang.harness.resources.activation import SkillActivationRuntime
from loushang.harness.resources.refresh import (
    ResourceRefreshCoordinator,
    RuntimeResourceDiscovery,
)
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
)


class ResourceLoaderPort(Protocol):
    """Load the Product's current resource bundle for a session cwd."""

    def reload_resources(self, cwd: str) -> ResourceBundle: ...


class ResourceSettingsPort(Protocol):
    """Expose the shared resource-activation setting needed at refresh time."""

    def get_disabled_skills(self) -> list[str]: ...


ResourceLoaderProvider = Callable[[], ResourceLoaderPort | None]
ResourceBundleProvider = Callable[[], ResourceBundle | None]
ResourceSettingsProvider = Callable[[], ResourceSettingsPort | None]
RefreshFailureRecorder = Callable[[Exception], None]


@dataclass
class SessionResourceRefreshRuntime:
    """Refresh a bound Product resource bundle without Product imports."""

    get_resource_loader: ResourceLoaderProvider
    get_resource_bundle: ResourceBundleProvider
    get_cwd: Callable[[], str]
    get_extension_runtime: Callable[[], object | None]
    get_settings: ResourceSettingsProvider
    set_resource_bundle: Callable[[ResourceBundle | None], None]
    rebuild_prompt_and_tools_view: Callable[[], None]
    record_refresh_failure: RefreshFailureRecorder
    sync_extension_diagnostics: Callable[[], None]
    prepare_resource_refresh: Callable[[], None] | None = None
    skill_activation_runtime: SkillActivationRuntime = field(
        default_factory=SkillActivationRuntime
    )
    _coordinator: ResourceRefreshCoordinator[ResourceBundle] = field(init=False)
    _discovery: RuntimeResourceDiscovery[ResourceBundle] = field(init=False)

    def __post_init__(self) -> None:
        self._discovery = RuntimeResourceDiscovery(self.get_extension_runtime)
        self._coordinator = ResourceRefreshCoordinator(
            load_resource=self._load_resource_bundle,
            discover_resource=self._discovery.discover,
            discover_resource_async=self._discovery.discover_async,
            commit_resource=self._commit_resource_bundle,
            prepare_refresh=self.prepare_resource_refresh,
        )

    def get_prompt_templates(self) -> list[PromptFragmentDescriptor]:
        resource_loader = self.get_resource_loader()
        if resource_loader is not None:
            get_prompts = getattr(resource_loader, "get_prompts", None)
            if not callable(get_prompts):
                return []
            prompts = get_prompts().get("prompts", [])
            return list(prompts) if isinstance(prompts, list) else []
        resource_bundle = self.get_resource_bundle()
        if resource_bundle is not None:
            return list(resource_bundle.prompts)
        return []

    def refresh(self, *, reason: str = "refresh") -> None:
        self._coordinator.refresh(reason=reason)

    async def refresh_async(self, *, reason: str = "refresh") -> None:
        await self._coordinator.refresh_async(reason=reason)

    def request_refresh(self) -> None:
        if self.get_resource_loader() is None:
            return
        try:
            self.refresh()
        except Exception as exc:
            self.record_refresh_failure(exc)
            return
        self.sync_extension_diagnostics()

    async def refresh_resources(self) -> None:
        """Refresh the bound resource bundle through the standard session port."""

        await self.refresh_async(reason="refresh")

    async def reload_extension_generation(
        self,
        bindings: object,
        *,
        reason: str = "reload",
    ) -> ResourceBundle | None:
        """Stage, publish, then retire one Extension/resource generation."""

        if self.prepare_resource_refresh is not None:
            prepared = self.prepare_resource_refresh()
            if inspect.isawaitable(prepared):
                await prepared
        extension_runtime = self.get_extension_runtime()
        resource_bundle = self._load_resource_bundle()
        if resource_bundle is None:
            activate_generation = getattr(
                extension_runtime,
                "activate_runtime_generation",
                None,
            )
            if not callable(activate_generation):
                raise TypeError(
                    "Extension runtime does not support generation activation"
                )
            activated = activate_generation(bindings)
            if inspect.isawaitable(activated):
                await activated
            return None
        prepare_generation = getattr(extension_runtime, "prepare_generation", None)
        if not callable(prepare_generation):
            raise TypeError(
                "Extension runtime does not support staged generation reload"
            )
        candidate = prepare_generation(resource_bundle.extensions)
        published = False
        publication_started = False
        previous_resource = self.get_resource_bundle()
        try:
            discovered = await candidate.discover_resources_async(
                resource_bundle,
                reason=reason,
            )
            await candidate.activate(bindings)
            publication_started = True
            retirement = candidate.publish(
                lambda: self._commit_resource_generation(discovered)
            )
            published = True
            await retirement.retire()
            return discovered
        except BaseException as publication_error:
            if not published:
                if publication_started:
                    try:
                        self.set_resource_bundle(previous_resource)
                        self.rebuild_prompt_and_tools_view()
                    except BaseException:
                        publication_error.add_note(
                            "previous resource bundle view restoration failed"
                        )
                await candidate.rollback()
            raise

    def request_resource_refresh(self) -> None:
        """Request a best-effort refresh for callers that cannot await it."""

        self.request_refresh()

    def _load_resource_bundle(self) -> ResourceBundle | None:
        resource_loader = self.get_resource_loader()
        if resource_loader is None:
            return None
        resource_bundle = resource_loader.reload_resources(self.get_cwd())
        if resource_bundle.prompt_fragments and not resource_bundle.prompt_descriptors:
            resource_bundle = replace(
                resource_bundle,
                prompt_descriptors=[
                    PromptFragmentDescriptor(
                        name=f"runtime-reload-{index}",
                        source_path=Path(resource_bundle.cwd)
                        / f".loushang-runtime-reload-{index}.md",
                        text=fragment,
                    )
                    for index, fragment in enumerate(resource_bundle.prompt_fragments)
                    if isinstance(fragment, str) and fragment.strip()
                ],
            )
        return resource_bundle

    def _commit_resource_bundle(self, resource_bundle: ResourceBundle) -> None:
        settings = self.get_settings()
        if settings is not None:
            disabled_skills = tuple(settings.get_disabled_skills())
            resource_bundle = self.skill_activation_runtime.apply(
                resource_bundle, disabled_skills
            )
        self.set_resource_bundle(resource_bundle)
        self.rebuild_prompt_and_tools_view()

    def _commit_resource_generation(self, resource_bundle: ResourceBundle) -> None:
        self._commit_resource_bundle(resource_bundle)


__all__ = [
    "RefreshFailureRecorder",
    "ResourceBundleProvider",
    "ResourceLoaderPort",
    "ResourceLoaderProvider",
    "ResourceSettingsPort",
    "ResourceSettingsProvider",
    "SessionResourceRefreshRuntime",
]
