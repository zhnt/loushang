"""Product-bound session resource refresh coordination.

The runtime owns the ordered refresh pipeline while Products bind resource
loading, settings, runtime discovery, diagnostics, and prompt/tool rebuilding.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from loushang.harness.extensions.declarations import (
    ExtensionCapabilityDeclarationSnapshot,
)
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
ExtensionDeclarationPreflight = Callable[[ExtensionCapabilityDeclarationSnapshot], None]
ResourceCatalogRefresh = Callable[[str], Awaitable[ResourceBundle | None]]


class CatalogRefreshRequiresAsyncError(RuntimeError):
    """A Catalog-owned refresh cannot be linearized synchronously."""


class ResourceRefreshRuntimeClosedError(RuntimeError):
    """The Session refresh authority has started its shutdown barrier."""


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
    extension_declaration_preflight: ExtensionDeclarationPreflight | None = None
    refresh_catalog: ResourceCatalogRefresh | None = None
    _coordinator: ResourceRefreshCoordinator[ResourceBundle] = field(init=False)
    _discovery: RuntimeResourceDiscovery[ResourceBundle] = field(init=False)
    _resource_revision: int = field(init=False, default=0)
    _catalog_refresh_lock: asyncio.Lock = field(init=False)
    _closing: bool = field(init=False, default=False)
    _closed: bool = field(init=False, default=False)
    _close_task: asyncio.Task[None] | None = field(init=False, default=None)
    _requested_refresh_task: asyncio.Task[None] | None = field(
        init=False,
        default=None,
    )
    _requested_refresh_running: bool = field(init=False, default=False)
    _requested_refresh_pending: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._resource_revision = 1 if self.get_resource_bundle() is not None else 0
        self._catalog_refresh_lock = asyncio.Lock()
        self._discovery = RuntimeResourceDiscovery(self.get_extension_runtime)
        self._coordinator = ResourceRefreshCoordinator(
            load_resource=self._load_resource_bundle,
            discover_resource=self._discovery.discover,
            discover_resource_async=self._discovery.discover_async,
            commit_resource=self._commit_resource_bundle,
            prepare_refresh=self.prepare_resource_refresh,
        )

    @property
    def resource_revision(self) -> int:
        """Return the Session-local ordinal of the effective resource view."""

        return self._resource_revision

    def get_prompt_templates(self) -> list[PromptFragmentDescriptor]:
        resource_bundle = self.get_resource_bundle()
        if resource_bundle is not None:
            return list(resource_bundle.prompts)
        return []

    def refresh(self, *, reason: str = "refresh") -> None:
        self._require_open()
        if self.refresh_catalog is not None:
            raise CatalogRefreshRequiresAsyncError(
                "Catalog-owned Resource refresh requires refresh_async()"
            )
        self._coordinator.refresh(reason=reason)

    async def refresh_async(self, *, reason: str = "refresh") -> None:
        await self._refresh_async(reason=reason, admitted=False)

    async def _refresh_async(self, *, reason: str, admitted: bool) -> None:
        if not admitted:
            self._require_open()
        elif self._closed:
            raise ResourceRefreshRuntimeClosedError(
                "Session Resource refresh runtime is closed"
            )
        catalog_refresh = self.refresh_catalog
        if catalog_refresh is not None:
            async with self._catalog_refresh_lock:
                # close() may win the lock after the first check.  A refresh
                # that had already entered the lock is allowed to finish;
                # queued callers fail without starting a new generation.
                if not admitted:
                    self._require_open()
                elif self._closed:
                    raise ResourceRefreshRuntimeClosedError(
                        "Session Resource refresh runtime is closed"
                    )
                if self.prepare_resource_refresh is not None:
                    prepared = self.prepare_resource_refresh()
                    if inspect.isawaitable(prepared):
                        await prepared
                previous = self.get_resource_bundle()
                try:
                    await catalog_refresh(reason)
                except BaseException:
                    if self.get_resource_bundle() is not previous:
                        self._resource_revision += 1
                    raise
                else:
                    self._resource_revision += 1
            return
        await self._coordinator.refresh_async(reason=reason)

    def request_refresh(self) -> None:
        if self._closing or self._closed:
            return
        if self.refresh_catalog is not None:
            task = self._requested_refresh_task
            if task is not None and not task.done():
                if self._requested_refresh_running:
                    self._requested_refresh_pending = True
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                self.record_refresh_failure(
                    CatalogRefreshRequiresAsyncError(
                        "Catalog-owned Resource refresh requires a running event loop"
                    )
                )
                return
            task = loop.create_task(self._run_requested_catalog_refresh())
            self._requested_refresh_task = task
            return
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

        if self.refresh_catalog is not None:
            del bindings
            await self.refresh_async(reason=reason)
            return self.get_resource_bundle()

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
        previous_resource_revision = self._resource_revision
        try:
            declaration_preflight = self.extension_declaration_preflight
            if declaration_preflight is not None:
                candidate_declarations = getattr(
                    candidate,
                    "capability_declarations",
                    None,
                )
                if not isinstance(
                    candidate_declarations,
                    ExtensionCapabilityDeclarationSnapshot,
                ):
                    raise TypeError(
                        "staged Extension generation does not expose capability "
                        "declarations"
                    )
                preflight_result = declaration_preflight(candidate_declarations)
                if inspect.isawaitable(preflight_result):
                    if inspect.iscoroutine(preflight_result):
                        preflight_result.close()
                    raise TypeError(
                        "Extension declaration preflight must be synchronous"
                    )
                if preflight_result is not None:
                    raise TypeError("Extension declaration preflight must return None")
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
                        if self.get_resource_bundle() is not previous_resource:
                            self.set_resource_bundle(previous_resource)
                            self.rebuild_prompt_and_tools_view()
                    except BaseException:
                        publication_error.add_note(
                            "previous resource bundle view restoration failed"
                        )
                    finally:
                        self._resource_revision = previous_resource_revision
                await candidate.rollback()
            raise

    def request_resource_refresh(self) -> None:
        """Request a best-effort refresh for callers that cannot await it."""

        self.request_refresh()

    async def close(self, *, cancel: bool = False) -> None:
        """Close refresh admission and join every entered Catalog refresh."""

        if self._closed:
            return
        task = self._close_task
        if task is None:
            self._closing = True
            task = asyncio.create_task(self._close_once(cancel=cancel))
            self._close_task = task
        await _join_close(task)

    async def _close_once(self, *, cancel: bool) -> None:
        try:
            task = self._requested_refresh_task
            if task is not None:
                if cancel and not task.done():
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            # Explicit refresh_async() callers are not owned tasks and must
            # not be cancelled.  Taking the lock after closing admission is
            # the join barrier for any one that already entered publication.
            if self.refresh_catalog is not None:
                async with self._catalog_refresh_lock:
                    pass
        finally:
            self._requested_refresh_task = None
            self._requested_refresh_pending = False
            self._closed = True

    async def _run_requested_catalog_refresh(self) -> None:
        self._requested_refresh_running = True
        try:
            while True:
                self._requested_refresh_pending = False
                try:
                    await self._refresh_async(reason="refresh", admitted=True)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.record_refresh_failure(exc)
                else:
                    self.sync_extension_diagnostics()
                if not self._requested_refresh_pending:
                    return
        finally:
            self._requested_refresh_running = False

    def _require_open(self) -> None:
        if self._closing or self._closed:
            raise ResourceRefreshRuntimeClosedError(
                "Session Resource refresh runtime is closed"
            )

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
        previous = self.get_resource_bundle()
        try:
            self.set_resource_bundle(resource_bundle)
            self.rebuild_prompt_and_tools_view()
        except BaseException as error:
            try:
                self.set_resource_bundle(previous)
                self.rebuild_prompt_and_tools_view()
            except BaseException as restoration_error:
                error.add_note(
                    "previous resource bundle view restoration also failed: "
                    f"{restoration_error!r}"
                )
            raise
        self._resource_revision += 1

    def _commit_resource_generation(self, resource_bundle: ResourceBundle) -> None:
        self._commit_resource_bundle(resource_bundle)


async def _join_close(task: asyncio.Task[None]) -> None:
    """Finish the Session-owned close barrier before propagating cancellation."""

    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if caller is None or caller.cancelling() == 0:
                return task.result()
            cancellation = exc
    task.result()
    if cancellation is not None:
        raise cancellation


__all__ = [
    "CatalogRefreshRequiresAsyncError",
    "ResourceRefreshRuntimeClosedError",
    "RefreshFailureRecorder",
    "ResourceBundleProvider",
    "ResourceCatalogRefresh",
    "ResourceLoaderPort",
    "ResourceLoaderProvider",
    "ResourceSettingsPort",
    "ResourceSettingsProvider",
    "ExtensionDeclarationPreflight",
    "SessionResourceRefreshRuntime",
]
