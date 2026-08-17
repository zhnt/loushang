from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from heapq import heapify, heappop, heappush
from pathlib import Path
from typing import Generic, TypeVar
from urllib.parse import quote

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.registry import source_info_from_extension
from loushang.harness.extensions.routing_types import (
    RegisteredExtensionHandler,
    RouteErrorPolicy,
)
from loushang.harness.extensions.types import (
    ExtensionHandler,
    LoadedExtension,
    extension_is_active,
)
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.source import SourceInfo

S = TypeVar("S")

ExtensionContextFactory = Callable[[LoadedExtension], object]
ExtensionRuntimeErrorHandler = Callable[[LoadedExtension, str, Exception], None]
RouteReducer = Callable[
    [S, object, "ResolvedExtensionRoute"],
    "RouteStep[S] | Awaitable[RouteStep[S]]",
]

_SKIPPED = object()


@dataclass(frozen=True)
class ResolvedExtensionRoute:
    route_id: str
    extension: LoadedExtension
    registration: RegisteredExtensionHandler
    registration_index: int
    source_info: SourceInfo[Path]


@dataclass(frozen=True)
class RouteStep(Generic[S]):
    state: S
    stop: bool = False


class ExtensionRouteError(RuntimeError):
    def __init__(
        self,
        route: ResolvedExtensionRoute,
        error: Exception,
    ) -> None:
        super().__init__(f"Extension route {route.route_id!r} failed: {error}")
        self.route = route
        self.error = error


@dataclass(frozen=True)
class ExtensionRoutePlan:
    _routes_by_event: Mapping[str, tuple[ResolvedExtensionRoute, ...]]
    diagnostics: tuple[DiagnosticDraft, ...] = ()

    @classmethod
    def from_extensions(
        cls,
        extensions: Sequence[LoadedExtension],
        *,
        diagnostics: list[DiagnosticDraft] | None = None,
    ) -> ExtensionRoutePlan:
        planning_diagnostics: list[DiagnosticDraft] = []
        registrations = tuple(
            (
                extension,
                _registrations_for_extension(
                    extension,
                    diagnostics=planning_diagnostics,
                ),
            )
            for extension in extensions
        )
        return cls._compile(
            registrations,
            planning_diagnostics=planning_diagnostics,
            diagnostics=diagnostics,
        )

    @classmethod
    def from_extension_registrations(
        cls,
        registrations: Sequence[
            tuple[LoadedExtension, Sequence[RegisteredExtensionHandler]]
        ],
        *,
        diagnostics: list[DiagnosticDraft] | None = None,
    ) -> ExtensionRoutePlan:
        """Compile explicit registrations without applying legacy synthesis."""

        return cls._compile(
            registrations,
            planning_diagnostics=[],
            diagnostics=diagnostics,
        )

    @classmethod
    def _compile(
        cls,
        extension_registrations: Sequence[
            tuple[LoadedExtension, Sequence[RegisteredExtensionHandler]]
        ],
        *,
        planning_diagnostics: list[DiagnosticDraft],
        diagnostics: list[DiagnosticDraft] | None,
    ) -> ExtensionRoutePlan:
        valid_extension_registrations = []
        for extension, registrations in extension_registrations:
            if _extension_id(extension):
                valid_extension_registrations.append((extension, registrations))
                continue
            planning_diagnostics.append(
                _planning_diagnostic(
                    extension,
                    code="invalid_extension_route_identity",
                    message="Extension route identity must not be empty.",
                )
            )
        extension_registrations = tuple(valid_extension_registrations)
        declared_by_event: dict[str, list[ResolvedExtensionRoute]] = {}
        registration_index = 0
        used_route_ids: set[str] = set()
        active_extension_ids = {
            _extension_id(extension)
            for extension, _ in extension_registrations
            if extension_is_active(extension)
        }
        inactive_extension_ids = {
            _extension_id(extension)
            for extension, _ in extension_registrations
            if not extension_is_active(extension)
        } - active_extension_ids
        inactive_route_ids = {
            _canonical_route_id(
                _extension_id(extension),
                registration.event_name,
                registration.local_route_id,
            )
            for extension, registrations in extension_registrations
            if not extension_is_active(extension)
            for registration in registrations
        }

        for extension, registrations in extension_registrations:
            if not extension_is_active(extension):
                continue
            extension_id = _extension_id(extension)
            for registration in registrations:
                canonical_route_id = _canonical_route_id(
                    extension_id,
                    registration.event_name,
                    registration.local_route_id,
                )
                route_id = canonical_route_id
                if route_id in used_route_ids:
                    duplicate_count = 2
                    route_id = f"{canonical_route_id}#duplicate-{duplicate_count}"
                    while route_id in used_route_ids:
                        duplicate_count += 1
                        route_id = f"{canonical_route_id}#duplicate-{duplicate_count}"
                    planning_diagnostics.append(
                        _planning_diagnostic(
                            extension,
                            code="duplicate_extension_route_id",
                            message=(
                                "Duplicate extension route id: "
                                f"{registration.local_route_id}"
                            ),
                            metadata={
                                "event": registration.event_name,
                                "route_id": canonical_route_id,
                                "resolved_route_id": route_id,
                            },
                        )
                    )
                used_route_ids.add(route_id)
                route = ResolvedExtensionRoute(
                    route_id=route_id,
                    extension=extension,
                    registration=registration,
                    registration_index=registration_index,
                    source_info=source_info_from_extension(extension),
                )
                declared_by_event.setdefault(registration.event_name, []).append(route)
                registration_index += 1

        ordered_by_event = {
            event_name: _order_routes(
                routes,
                diagnostics=planning_diagnostics,
                inactive_extension_ids=inactive_extension_ids,
                inactive_route_ids=inactive_route_ids,
            )
            for event_name, routes in declared_by_event.items()
        }
        if diagnostics is not None:
            diagnostics.extend(planning_diagnostics)
        return cls(
            _routes_by_event=ordered_by_event,
            diagnostics=tuple(planning_diagnostics),
        )

    def routes_for(self, event_name: str) -> tuple[ResolvedExtensionRoute, ...]:
        return self._routes_by_event.get(event_name, ())

    def has_routes(self, event_name: str) -> bool:
        return bool(self.routes_for(event_name))


class ExtensionRouter:
    """Invoke product-neutral extension routes from one compiled plan."""

    def __init__(
        self,
        plan: ExtensionRoutePlan,
        *,
        diagnostics: list[DiagnosticDraft],
        runtime_error_handler: ExtensionRuntimeErrorHandler | None = None,
        include_route_id_in_error_metadata: bool = True,
        include_provenance_in_error_metadata: bool = True,
    ) -> None:
        self._plan = plan
        self._diagnostics = diagnostics
        self._runtime_error_handler = runtime_error_handler
        self._include_route_id_in_error_metadata = include_route_id_in_error_metadata
        self._include_provenance_in_error_metadata = (
            include_provenance_in_error_metadata
        )

    @classmethod
    def from_extensions(
        cls,
        extensions: Sequence[LoadedExtension],
        *,
        diagnostics: list[DiagnosticDraft],
        runtime_error_handler: ExtensionRuntimeErrorHandler | None = None,
        include_route_id_in_error_metadata: bool = True,
        include_provenance_in_error_metadata: bool = True,
    ) -> ExtensionRouter:
        return cls(
            ExtensionRoutePlan.from_extensions(
                extensions,
                diagnostics=diagnostics,
            ),
            diagnostics=diagnostics,
            runtime_error_handler=runtime_error_handler,
            include_route_id_in_error_metadata=(include_route_id_in_error_metadata),
            include_provenance_in_error_metadata=(include_provenance_in_error_metadata),
        )

    @property
    def plan(self) -> ExtensionRoutePlan:
        return self._plan

    def has_handlers(self, event_name: str) -> bool:
        return self._plan.has_routes(event_name)

    async def observe(
        self,
        event_name: str,
        event: object,
        *,
        context_factory: ExtensionContextFactory,
    ) -> tuple[object, ...]:
        results: list[object] = []
        contexts: dict[int, object] = {}
        for route in self._plan.routes_for(event_name):
            result = await self._invoke(
                route,
                event,
                context_factory=context_factory,
                contexts=contexts,
            )
            if result is not _SKIPPED and result is not None:
                results.append(result)
        return tuple(results)

    async def first(
        self,
        event_name: str,
        event: object,
        *,
        predicate: Callable[[object], bool],
        context_factory: ExtensionContextFactory,
    ) -> object | None:
        contexts: dict[int, object] = {}
        for route in self._plan.routes_for(event_name):
            result = await self._invoke(
                route,
                event,
                context_factory=context_factory,
                contexts=contexts,
            )
            if result is _SKIPPED or result is None:
                continue
            if predicate(result):
                return result
        return None

    async def reduce(
        self,
        event_name: str,
        state: S,
        *,
        event_factory: Callable[[S, ResolvedExtensionRoute], object],
        reducer: RouteReducer[S],
        context_factory: ExtensionContextFactory,
    ) -> RouteStep[S]:
        current = RouteStep(state=state)
        contexts: dict[int, object] = {}
        for route in self._plan.routes_for(event_name):
            event = event_factory(current.state, route)
            result = await self._invoke(
                route,
                event,
                context_factory=context_factory,
                contexts=contexts,
            )
            if result is _SKIPPED or result is None:
                continue
            next_step = reducer(current.state, result, route)
            if inspect.isawaitable(next_step):
                next_step = await next_step
            if not isinstance(next_step, RouteStep):
                raise TypeError("extension route reducer must return RouteStep")
            current = next_step
            if current.stop:
                return current
        return current

    async def intercept(
        self,
        event_name: str,
        state: S,
        *,
        event_factory: Callable[[S, ResolvedExtensionRoute], object],
        reducer: RouteReducer[S],
        context_factory: ExtensionContextFactory,
    ) -> RouteStep[S]:
        return await self.reduce(
            event_name,
            state,
            event_factory=event_factory,
            reducer=reducer,
            context_factory=context_factory,
        )

    async def _invoke(
        self,
        route: ResolvedExtensionRoute,
        event: object,
        *,
        context_factory: ExtensionContextFactory,
        contexts: dict[int, object],
    ) -> object:
        extension_key = id(route.extension)
        if extension_key not in contexts:
            contexts[extension_key] = context_factory(route.extension)
        try:
            result = route.registration.handler(event, contexts[extension_key])
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as exc:
            self._record_error(route, exc)
            if route.registration.on_error == "fail_chain":
                raise ExtensionRouteError(route, exc) from exc
            return _SKIPPED

    def _record_error(
        self,
        route: ResolvedExtensionRoute,
        error: Exception,
    ) -> None:
        event_name = route.registration.event_name
        source_info = route.source_info
        metadata: dict[str, object] = {}
        if self._include_provenance_in_error_metadata:
            metadata.update(
                {
                    "extension_name": route.extension.name,
                    "hook": event_name,
                    "source": source_info.source,
                    "scope": source_info.scope,
                    "origin": source_info.origin,
                    "base_dir": (
                        source_info.base_dir.as_posix()
                        if source_info.base_dir is not None
                        else route.extension.source_path.parent.as_posix()
                    ),
                }
            )
        if self._include_route_id_in_error_metadata:
            metadata["route_id"] = route.route_id
        self._diagnostics.append(
            resource_diagnostic(
                code=f"extension_{event_name}_failed",
                message=f"Extension hook '{event_name}' failed: {error}",
                source_path=route.extension.source_path,
                metadata=metadata,
            )
        )
        if self._runtime_error_handler is None:
            return
        with suppress(Exception):
            self._runtime_error_handler(route.extension, event_name, error)


def _registrations_for_extension(
    extension: LoadedExtension,
    *,
    diagnostics: list[DiagnosticDraft],
) -> tuple[RegisteredExtensionHandler, ...]:
    registrations = tuple(extension.handler_registrations)
    if not registrations:
        return tuple(
            RegisteredExtensionHandler(
                local_route_id=f"legacy-{handler_index:04d}",
                event_name=event_name,
                handler=handler,
            )
            for event_name, handlers in extension.hooks.items()
            for handler_index, handler in enumerate(handlers, start=1)
        )

    projected: dict[str, list[ExtensionHandler]] = {}
    for registration in registrations:
        projected.setdefault(registration.event_name, []).append(registration.handler)
    if extension.hooks and not _same_hook_projection(extension.hooks, projected):
        diagnostics.append(
            _planning_diagnostic(
                extension,
                code="conflicting_extension_hook_registrations",
                message=(
                    "Loaded extension hooks differ from authoritative handler "
                    "registrations."
                ),
            )
        )
    return registrations


def _same_hook_projection(
    left: Mapping[str, Sequence[ExtensionHandler]],
    right: Mapping[str, Sequence[ExtensionHandler]],
) -> bool:
    if tuple(left) != tuple(right):
        return False
    return all(
        len(left[name]) == len(right[name])
        and all(
            left_handler is right_handler
            for left_handler, right_handler in zip(left[name], right[name], strict=True)
        )
        for name in left
    )


def _order_routes(
    routes: Sequence[ResolvedExtensionRoute],
    *,
    diagnostics: list[DiagnosticDraft],
    inactive_extension_ids: set[str],
    inactive_route_ids: set[str],
) -> tuple[ResolvedExtensionRoute, ...]:
    if len(routes) < 2 and not any(
        route.registration.after or route.registration.before for route in routes
    ):
        return tuple(routes)

    route_by_id = {route.route_id: route for route in routes}
    routes_by_extension: dict[str, list[ResolvedExtensionRoute]] = {}
    for route in routes:
        routes_by_extension.setdefault(_extension_id(route.extension), []).append(route)
    edges: dict[str, set[str]] = {route.route_id: set() for route in routes}

    for route in routes:
        for relation, references in (
            ("after", route.registration.after),
            ("before", route.registration.before),
        ):
            for reference in references:
                targets = _resolve_reference(
                    route,
                    reference,
                    route_by_id=route_by_id,
                    routes_by_extension=routes_by_extension,
                    inactive_extension_ids=inactive_extension_ids,
                    inactive_route_ids=inactive_route_ids,
                    diagnostics=diagnostics,
                )
                for target in targets:
                    if target.route_id == route.route_id:
                        diagnostics.append(
                            _route_diagnostic(
                                route,
                                code="extension_route_self_reference",
                                message=(
                                    f"Extension route {route.route_id!r} references itself."
                                ),
                                metadata={"reference": reference},
                            )
                        )
                        continue
                    source_id, target_id = (
                        (target.route_id, route.route_id)
                        if relation == "after"
                        else (route.route_id, target.route_id)
                    )
                    edges[source_id].add(target_id)

    components = _strongly_connected_components(routes, edges)
    component_by_route = {
        route_id: component_index
        for component_index, component in enumerate(components)
        for route_id in component
    }
    component_edges: dict[int, set[int]] = {
        index: set() for index in range(len(components))
    }
    indegrees = {index: 0 for index in range(len(components))}
    for source_id, target_ids in edges.items():
        source_component = component_by_route[source_id]
        for target_id in target_ids:
            target_component = component_by_route[target_id]
            if source_component == target_component:
                continue
            if target_component not in component_edges[source_component]:
                component_edges[source_component].add(target_component)
                indegrees[target_component] += 1

    cyclic_components = sorted(
        (
            tuple(
                sorted(
                    (route_by_id[route_id] for route_id in component),
                    key=_route_order_key,
                )
            )
            for component in components
            if len(component) > 1
        ),
        key=lambda cycle_routes: _route_order_key(cycle_routes[0]),
    )
    for cycle_routes in cyclic_components:
        diagnostics.append(
            _route_diagnostic(
                cycle_routes[0],
                code="extension_route_order_cycle",
                message="Extension route ordering contains a dependency cycle.",
                metadata={"route_ids": tuple(route.route_id for route in cycle_routes)},
            )
        )

    component_routes = {
        index: tuple(
            sorted(
                (route_by_id[route_id] for route_id in component),
                key=_route_order_key,
            )
        )
        for index, component in enumerate(components)
    }
    ready = [
        (_route_order_key(component_routes[index][0]), index)
        for index, indegree in indegrees.items()
        if indegree == 0
    ]
    heapify(ready)
    ordered: list[ResolvedExtensionRoute] = []
    while ready:
        _, component_index = heappop(ready)
        ordered.extend(component_routes[component_index])
        for target_index in component_edges[component_index]:
            indegrees[target_index] -= 1
            if indegrees[target_index] == 0:
                heappush(
                    ready,
                    (
                        _route_order_key(component_routes[target_index][0]),
                        target_index,
                    ),
                )
    return tuple(ordered)


def _strongly_connected_components(
    routes: Sequence[ResolvedExtensionRoute],
    edges: Mapping[str, set[str]],
) -> tuple[tuple[str, ...], ...]:
    registration_indexes = {
        route.route_id: route.registration_index for route in routes
    }
    route_ids = tuple(
        route.route_id
        for route in sorted(routes, key=lambda item: item.registration_index)
    )
    adjacency = {
        route_id: tuple(sorted(edges[route_id], key=registration_indexes.__getitem__))
        for route_id in route_ids
    }
    visited: set[str] = set()
    finish_order: list[str] = []
    for start_id in route_ids:
        if start_id in visited:
            continue
        visited.add(start_id)
        stack: list[tuple[str, int]] = [(start_id, 0)]
        while stack:
            route_id, target_index = stack[-1]
            targets = adjacency[route_id]
            if target_index >= len(targets):
                stack.pop()
                finish_order.append(route_id)
                continue
            target_id = targets[target_index]
            stack[-1] = (route_id, target_index + 1)
            if target_id in visited:
                continue
            visited.add(target_id)
            stack.append((target_id, 0))

    reverse_edges: dict[str, list[str]] = {route_id: [] for route_id in route_ids}
    for source_id, target_ids in adjacency.items():
        for target_id in target_ids:
            reverse_edges[target_id].append(source_id)
    for source_ids in reverse_edges.values():
        source_ids.sort(key=registration_indexes.__getitem__)

    components: list[tuple[str, ...]] = []
    assigned: set[str] = set()
    for start_id in reversed(finish_order):
        if start_id in assigned:
            continue
        assigned.add(start_id)
        component: list[str] = []
        stack = [(start_id, 0)]
        while stack:
            route_id, source_index = stack[-1]
            if source_index == 0:
                component.append(route_id)
            sources = reverse_edges[route_id]
            if source_index >= len(sources):
                stack.pop()
                continue
            source_id = sources[source_index]
            stack[-1] = (route_id, source_index + 1)
            if source_id in assigned:
                continue
            assigned.add(source_id)
            stack.append((source_id, 0))
        components.append(tuple(component))
    return tuple(components)


def _resolve_reference(
    route: ResolvedExtensionRoute,
    reference: str,
    *,
    route_by_id: Mapping[str, ResolvedExtensionRoute],
    routes_by_extension: Mapping[str, Sequence[ResolvedExtensionRoute]],
    inactive_extension_ids: set[str],
    inactive_route_ids: set[str],
    diagnostics: list[DiagnosticDraft],
) -> tuple[ResolvedExtensionRoute, ...]:
    if reference.startswith("route:"):
        route_id = reference.removeprefix("route:")
        if not route_id:
            diagnostics.append(
                _route_diagnostic(
                    route,
                    code="malformed_extension_route_reference",
                    message=f"Malformed extension route reference: {reference}",
                    metadata={"reference": reference},
                )
            )
            return ()
        target = route_by_id.get(route_id)
        if target is not None:
            return (target,)
        if route_id in inactive_route_ids:
            return ()
    elif reference.startswith("extension:"):
        extension_id = reference.removeprefix("extension:")
        if not extension_id:
            diagnostics.append(
                _route_diagnostic(
                    route,
                    code="malformed_extension_route_reference",
                    message=f"Malformed extension route reference: {reference}",
                    metadata={"reference": reference},
                )
            )
            return ()
        targets = tuple(routes_by_extension.get(extension_id, ()))
        if targets:
            return targets
        if extension_id in inactive_extension_ids:
            return ()
    else:
        diagnostics.append(
            _route_diagnostic(
                route,
                code="malformed_extension_route_reference",
                message=f"Malformed extension route reference: {reference}",
                metadata={"reference": reference},
            )
        )
        return ()

    diagnostics.append(
        _route_diagnostic(
            route,
            code="missing_extension_route_reference",
            message=f"Unknown extension route reference: {reference}",
            metadata={"reference": reference},
        )
    )
    return ()


def _route_order_key(route: ResolvedExtensionRoute) -> tuple[int, int]:
    return (-route.registration.priority, route.registration_index)


def _canonical_route_id(
    extension_id: str,
    event_name: str,
    local_route_id: str,
) -> str:
    return "/".join(
        quote(component, safe="")
        for component in (extension_id, event_name, local_route_id)
    )


def _extension_id(extension: LoadedExtension) -> str:
    manifest = extension.manifest
    manifest_id = getattr(manifest, "id", None)
    if isinstance(manifest_id, str):
        return manifest_id.strip()
    return extension.name.strip()


def _planning_diagnostic(
    extension: LoadedExtension,
    *,
    code: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> DiagnosticDraft:
    return resource_diagnostic(
        code=code,
        message=message,
        source_path=extension.source_path,
        resource_type="extension",
        metadata={"extension_name": extension.name, **(metadata or {})},
    )


def _route_diagnostic(
    route: ResolvedExtensionRoute,
    *,
    code: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> DiagnosticDraft:
    return _planning_diagnostic(
        route.extension,
        code=code,
        message=message,
        metadata={"route_id": route.route_id, **(metadata or {})},
    )


__all__ = [
    "ExtensionContextFactory",
    "ExtensionRouteError",
    "ExtensionRoutePlan",
    "ExtensionRouter",
    "ExtensionRuntimeErrorHandler",
    "RegisteredExtensionHandler",
    "ResolvedExtensionRoute",
    "RouteErrorPolicy",
    "RouteReducer",
    "RouteStep",
]
