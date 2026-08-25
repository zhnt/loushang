from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.declarations import extension_declaration_id
from loushang.harness.extensions.routing import (
    ExtensionRouteError,
    ExtensionRoutePlan,
    ResolvedExtensionRoute,
)
from loushang.harness.extensions.types import (
    ExtensionResourceContribution,
    LoadedExtension,
)
from loushang.harness.resources._catalog_extension_source import (
    ExtensionResourceRouteContribution,
)
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
    ThemeDescriptor,
)


@dataclass(frozen=True, slots=True)
class ExtensionResourceCatalogDiscovery:
    """Unpublished projection and exact routed inputs for one Catalog pass."""

    projection: ResourceBundle
    route_contributions: tuple[ExtensionResourceRouteContribution, ...]


class ExtensionResourceRuntime:
    """Runs resource contribution hooks and merges their neutral descriptors."""

    def __init__(
        self,
        extensions: Sequence[LoadedExtension],
        *,
        diagnostics: list[DiagnosticDraft],
        route_plan: ExtensionRoutePlan | None = None,
    ) -> None:
        self._extensions = tuple(extensions)
        self._diagnostics = diagnostics
        self._route_plan = route_plan or ExtensionRoutePlan.from_extensions(
            self._extensions, diagnostics=diagnostics
        )

    def discover(self, bundle: ResourceBundle, *, context: object) -> ResourceBundle:
        merged = bundle
        diagnostics: list[DiagnosticDraft] = []
        for route in self._route_plan.routes_for("resources_discover"):
            merged = self._apply_route(
                route=route,
                bundle=merged,
                context=context,
                diagnostics=diagnostics,
            )
        return self._finish(merged, diagnostics)

    async def discover_async(
        self,
        bundle: ResourceBundle,
        *,
        context: object,
    ) -> ResourceBundle:
        merged = bundle
        diagnostics: list[DiagnosticDraft] = []
        for route in self._route_plan.routes_for("resources_discover"):
            merged = await self._apply_route_async(
                route=route,
                bundle=merged,
                context=context,
                diagnostics=diagnostics,
            )
        return self._finish(merged, diagnostics)

    async def prepare_catalog_inputs_async(
        self,
        bundle: ResourceBundle,
        *,
        context: object,
    ) -> ExtensionResourceCatalogDiscovery:
        """Run one defensive, non-publishing pass for the Resource Catalog owner."""

        merged = _defensive_bundle(bundle)
        diagnostics: list[DiagnosticDraft] = []
        routed: list[ExtensionResourceRouteContribution] = []
        for route_order, route in enumerate(
            self._route_plan.routes_for("resources_discover")
        ):
            route_diagnostics: list[DiagnosticDraft] = []
            try:
                contribution = _invoke_resource_handler(
                    route.registration.handler,
                    bundle=_defensive_bundle(merged),
                    context=context,
                )
                if inspect.isawaitable(contribution):
                    contribution = await contribution
            except Exception as exc:
                _record_resource_error(route, exc, diagnostics=route_diagnostics)
                diagnostics.extend(route_diagnostics)
                if route.registration.on_error == "fail_chain":
                    self._diagnostics.extend(diagnostics)
                    raise ExtensionRouteError(route, exc) from exc
                routed.append(
                    _catalog_route_contribution(
                        route,
                        route_order=route_order,
                        contribution=None,
                        diagnostics=route_diagnostics,
                    )
                )
                continue

            merged, routed_contribution = _apply_catalog_route_output(
                route=route,
                route_order=route_order,
                bundle=merged,
                contribution=contribution,
                diagnostics=route_diagnostics,
            )
            diagnostics.extend(route_diagnostics)
            routed.append(routed_contribution)
        return ExtensionResourceCatalogDiscovery(
            projection=self._finish(merged, diagnostics),
            route_contributions=tuple(routed),
        )

    def prepare_catalog_inputs(
        self,
        bundle: ResourceBundle,
        *,
        context: object,
    ) -> ExtensionResourceCatalogDiscovery:
        """Synchronous initial-bootstrap form of the defensive Catalog pass."""

        merged = _defensive_bundle(bundle)
        diagnostics: list[DiagnosticDraft] = []
        routed: list[ExtensionResourceRouteContribution] = []
        for route_order, route in enumerate(
            self._route_plan.routes_for("resources_discover")
        ):
            route_diagnostics: list[DiagnosticDraft] = []
            try:
                contribution = _invoke_resource_handler(
                    route.registration.handler,
                    bundle=_defensive_bundle(merged),
                    context=context,
                )
            except Exception as exc:
                _record_resource_error(route, exc, diagnostics=route_diagnostics)
                diagnostics.extend(route_diagnostics)
                if route.registration.on_error == "fail_chain":
                    self._diagnostics.extend(diagnostics)
                    raise ExtensionRouteError(route, exc) from exc
                routed.append(
                    _catalog_route_contribution(
                        route,
                        route_order=route_order,
                        contribution=None,
                        diagnostics=route_diagnostics,
                    )
                )
                continue
            if inspect.isawaitable(contribution):
                if inspect.iscoroutine(contribution):
                    contribution.close()
                error = RuntimeError(
                    "Async extension hooks are not supported in synchronous discovery."
                )
                route_diagnostics.append(
                    resource_diagnostic(
                        code="unsupported_async_extension_hook",
                        message="Async extension hooks require async Catalog preparation.",
                        source_path=route.extension.source_path,
                    )
                )
                diagnostics.extend(route_diagnostics)
                if route.registration.on_error == "fail_chain":
                    self._diagnostics.extend(diagnostics)
                    raise ExtensionRouteError(route, error) from error
                routed.append(
                    _catalog_route_contribution(
                        route,
                        route_order=route_order,
                        contribution=None,
                        diagnostics=route_diagnostics,
                    )
                )
                continue

            merged, routed_contribution = _apply_catalog_route_output(
                route=route,
                route_order=route_order,
                bundle=merged,
                contribution=contribution,
                diagnostics=route_diagnostics,
            )
            diagnostics.extend(route_diagnostics)
            routed.append(routed_contribution)
        return ExtensionResourceCatalogDiscovery(
            projection=self._finish(merged, diagnostics),
            route_contributions=tuple(routed),
        )

    def _apply_route(
        self,
        *,
        route: ResolvedExtensionRoute,
        bundle: ResourceBundle,
        context: object,
        diagnostics: list[DiagnosticDraft],
    ) -> ResourceBundle:
        try:
            contribution = _invoke_resource_handler(
                route.registration.handler,
                bundle=bundle,
                context=context,
            )
        except Exception as exc:
            _record_resource_error(route, exc, diagnostics=diagnostics)
            if route.registration.on_error == "fail_chain":
                self._diagnostics.extend(diagnostics)
                raise ExtensionRouteError(route, exc) from exc
            return bundle
        if inspect.isawaitable(contribution):
            if inspect.iscoroutine(contribution):
                contribution.close()
            error = RuntimeError(
                "Async extension hooks are not supported in synchronous discovery."
            )
            diagnostics.append(
                resource_diagnostic(
                    code="unsupported_async_extension_hook",
                    message="Async extension hooks are not supported in P0/v1.",
                    source_path=route.extension.source_path,
                )
            )
            if route.registration.on_error == "fail_chain":
                self._diagnostics.extend(diagnostics)
                raise ExtensionRouteError(route, error) from error
            return bundle
        return _merge_contribution(
            bundle,
            contribution,
            extension=route.extension,
            diagnostics=diagnostics,
        )

    async def _apply_route_async(
        self,
        *,
        route: ResolvedExtensionRoute,
        bundle: ResourceBundle,
        context: object,
        diagnostics: list[DiagnosticDraft],
    ) -> ResourceBundle:
        try:
            contribution = _invoke_resource_handler(
                route.registration.handler,
                bundle=bundle,
                context=context,
            )
            if inspect.isawaitable(contribution):
                contribution = await contribution
        except Exception as exc:
            _record_resource_error(route, exc, diagnostics=diagnostics)
            if route.registration.on_error == "fail_chain":
                self._diagnostics.extend(diagnostics)
                raise ExtensionRouteError(route, exc) from exc
            return bundle
        return _merge_contribution(
            bundle,
            contribution,
            extension=route.extension,
            diagnostics=diagnostics,
        )

    def _finish(
        self,
        bundle: ResourceBundle,
        diagnostics: list[DiagnosticDraft],
    ) -> ResourceBundle:
        if not diagnostics:
            return bundle
        self._diagnostics.extend(diagnostics)
        return bundle.merge(diagnostics=diagnostics)


def _invoke_resource_handler(
    handler: object,
    *,
    bundle: ResourceBundle,
    context: object,
) -> object:
    callback = cast(Callable[[ResourceBundle, object], object], handler)
    return callback(bundle, context)


def _record_resource_error(
    route: ResolvedExtensionRoute,
    error: Exception,
    *,
    diagnostics: list[DiagnosticDraft],
) -> None:
    diagnostics.append(
        resource_diagnostic(
            code="extension_resources_discover_failed",
            message=f"Extension resource discovery failed: {error}",
            source_path=route.extension.source_path,
            metadata={
                "extension_name": route.extension.name,
                "hook": "resources_discover",
                "route_id": route.route_id,
            },
        )
    )


def _merge_contribution(
    bundle: ResourceBundle,
    contribution: object,
    *,
    extension: LoadedExtension,
    diagnostics: list[DiagnosticDraft],
) -> ResourceBundle:
    normalized = _normalize_contribution(
        contribution,
        extension=extension,
        diagnostics=diagnostics,
    )
    if normalized is None:
        return bundle
    return _merge_normalized_contribution(bundle, normalized)


def _apply_catalog_route_output(
    contribution: object,
    *,
    route: ResolvedExtensionRoute,
    route_order: int,
    bundle: ResourceBundle,
    diagnostics: list[DiagnosticDraft],
) -> tuple[ResourceBundle, ExtensionResourceRouteContribution]:
    normalized = _normalize_contribution(
        contribution,
        extension=route.extension,
        diagnostics=diagnostics,
    )
    if normalized is not None:
        normalized = _bind_contribution_source_facts(
            normalized,
            extension=route.extension,
        )
        bundle = _merge_normalized_contribution(bundle, normalized)
    return bundle, _catalog_route_contribution(
        route,
        route_order=route_order,
        contribution=normalized,
        diagnostics=diagnostics,
    )


def _normalize_contribution(
    contribution: object,
    *,
    extension: LoadedExtension,
    diagnostics: list[DiagnosticDraft],
) -> ExtensionResourceContribution | None:
    if contribution is None:
        return None
    normalized = coerce_resource_contribution(contribution, extension=extension)
    if not isinstance(normalized, ExtensionResourceContribution):
        diagnostics.append(
            resource_diagnostic(
                code="invalid_extension_resource_contribution",
                message=(
                    "resources_discover hooks must return "
                    "ExtensionResourceContribution or None."
                ),
                source_path=extension.source_path,
            )
        )
        return None
    diagnostics.extend(normalized.diagnostics)
    return normalized


def _merge_normalized_contribution(
    bundle: ResourceBundle,
    contribution: ExtensionResourceContribution,
) -> ResourceBundle:
    return bundle.merge(
        prompt_descriptors=list(contribution.prompt_descriptors),
        skills=list(contribution.skills),
        extensions=list(contribution.extensions),
        prompts=list(contribution.prompts),
        themes=list(contribution.themes),
    )


def _bind_contribution_source_facts(
    contribution: ExtensionResourceContribution,
    *,
    extension: LoadedExtension,
) -> ExtensionResourceContribution:
    def bind(descriptor):  # type: ignore[no-untyped-def]
        return replace(
            descriptor,
            source=extension.source,
            source_kind=extension.source_kind,
            source_scope=extension.source_scope,
            source_root_order=extension.source_root_order,
        )

    return ExtensionResourceContribution(
        prompt_descriptors=[bind(item) for item in contribution.prompt_descriptors],
        skills=[bind(item) for item in contribution.skills],
        extensions=[bind(item) for item in contribution.extensions],
        prompts=[bind(item) for item in contribution.prompts],
        themes=[bind(item) for item in contribution.themes],
        diagnostics=list(contribution.diagnostics),
    )


def _catalog_route_contribution(
    route: ResolvedExtensionRoute,
    *,
    route_order: int,
    contribution: ExtensionResourceContribution | None,
    diagnostics: list[DiagnosticDraft],
) -> ExtensionResourceRouteContribution:
    normalized = contribution or ExtensionResourceContribution()
    return ExtensionResourceRouteContribution(
        extension_id=extension_declaration_id(route.extension),
        route_id=route.route_id,
        source_class=route.extension.source_kind,
        scope_id=route.extension.source_scope,
        source_root_order=route.extension.source_root_order,
        route_order=route_order,
        prompt_descriptors=tuple(normalized.prompt_descriptors),
        skills=tuple(normalized.skills),
        extensions=tuple(normalized.extensions),
        prompts=tuple(normalized.prompts),
        themes=tuple(normalized.themes),
        diagnostics=tuple(diagnostics),
    )


def _defensive_bundle(bundle: ResourceBundle) -> ResourceBundle:
    return ResourceBundle(
        cwd=bundle.cwd,
        agents_path=bundle.agents_path,
        agents_md=bundle.agents_md,
        prompt_fragments=list(bundle.prompt_fragments),
        prompt_descriptors=list(bundle.prompt_descriptors),
        skills=list(bundle.skills),
        extensions=list(bundle.extensions),
        prompts=list(bundle.prompts),
        themes=list(bundle.themes),
        diagnostics=list(bundle.diagnostics),
    )


def coerce_resource_contribution(
    contribution: object,
    *,
    extension: LoadedExtension,
) -> object:
    if not isinstance(contribution, dict):
        return contribution
    diagnostics: list[DiagnosticDraft] = []
    return ExtensionResourceContribution(
        prompts=_prompt_descriptors_from_paths(
            _as_path_list(contribution.get("promptPaths")),
            extension=extension,
            diagnostics=diagnostics,
        ),
        skills=_skill_descriptors_from_paths(
            _as_path_list(contribution.get("skillPaths")),
            extension=extension,
            diagnostics=diagnostics,
        ),
        themes=_theme_descriptors_from_paths(
            _as_path_list(contribution.get("themePaths")),
            extension=extension,
            diagnostics=diagnostics,
        ),
        diagnostics=diagnostics,
    )


def _as_path_list(value: object) -> list[Path]:
    if not isinstance(value, list):
        return []
    return [Path(item) for item in value if isinstance(item, str | Path)]


def _prompt_descriptors_from_paths(
    paths: Sequence[Path],
    *,
    extension: LoadedExtension,
    diagnostics: list[DiagnosticDraft],
) -> list[PromptFragmentDescriptor]:
    descriptors: list[PromptFragmentDescriptor] = []
    for path in paths:
        descriptor, diagnostic = _prompt_descriptor_from_path(
            path,
            extension=extension,
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        if descriptor is not None:
            descriptors.append(descriptor)
    return descriptors


def _prompt_descriptor_from_path(
    path: Path,
    *,
    extension: LoadedExtension,
) -> tuple[PromptFragmentDescriptor | None, DiagnosticDraft | None]:
    if not path.is_file():
        return None, resource_diagnostic(
            code="extension_prompt_path_not_found",
            message=f"Extension prompt path does not exist or is not a file: {path}",
            source_path=path,
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, resource_diagnostic(
            code="extension_prompt_path_read_failed",
            message=f"Failed to read extension prompt path {path}: {exc}",
            source_path=path,
        )
    return (
        PromptFragmentDescriptor(
            name=path.stem,
            source_path=path,
            text=text,
            canonical_name=path.name,
            source=extension.source,
            source_kind=extension.source_kind,
            source_scope=extension.source_scope,
            source_root=path.parent,
            source_root_order=extension.source_root_order,
        ),
        None,
    )


def _skill_descriptors_from_paths(
    paths: Sequence[Path],
    *,
    extension: LoadedExtension,
    diagnostics: list[DiagnosticDraft],
) -> list[SkillDescriptor]:
    descriptors: list[SkillDescriptor] = []
    for path in paths:
        descriptor, diagnostic = _skill_descriptor_from_path(
            path,
            extension=extension,
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        if descriptor is not None:
            descriptors.append(descriptor)
    return descriptors


def _skill_descriptor_from_path(
    path: Path,
    *,
    extension: LoadedExtension,
) -> tuple[SkillDescriptor | None, DiagnosticDraft | None]:
    skill_file = path / "SKILL.md" if path.is_dir() else path
    if not skill_file.is_file():
        return None, resource_diagnostic(
            code="extension_skill_path_not_found",
            message=(
                f"Extension skill path does not exist or is not a skill file: {path}"
            ),
            source_path=path,
        )
    try:
        content = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        return None, resource_diagnostic(
            code="extension_skill_path_read_failed",
            message=f"Failed to read extension skill path {skill_file}: {exc}",
            source_path=skill_file,
        )
    return (
        SkillDescriptor(
            name=(
                skill_file.parent.name
                if skill_file.name == "SKILL.md"
                else skill_file.stem
            ),
            source_path=skill_file,
            content=content,
            canonical_name=(
                f"{skill_file.parent.name}/SKILL.md"
                if skill_file.name == "SKILL.md"
                else skill_file.name
            ),
            source=extension.source,
            source_kind=extension.source_kind,
            source_scope=extension.source_scope,
            source_root=(
                skill_file.parent.parent
                if skill_file.name == "SKILL.md"
                else skill_file.parent
            ),
            source_root_order=extension.source_root_order,
        ),
        None,
    )


def _theme_descriptors_from_paths(
    paths: Sequence[Path],
    *,
    extension: LoadedExtension,
    diagnostics: list[DiagnosticDraft],
) -> list[ThemeDescriptor]:
    descriptors: list[ThemeDescriptor] = []
    for path in paths:
        descriptor, diagnostic = _theme_descriptor_from_path(
            path,
            extension=extension,
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        if descriptor is not None:
            descriptors.append(descriptor)
    return descriptors


def _theme_descriptor_from_path(
    path: Path,
    *,
    extension: LoadedExtension,
) -> tuple[ThemeDescriptor | None, DiagnosticDraft | None]:
    if not path.exists():
        return None, resource_diagnostic(
            code="extension_theme_path_not_found",
            message=f"Extension theme path does not exist: {path}",
            source_path=path,
        )
    return (
        ThemeDescriptor(
            name=path.stem if path.is_file() else path.name,
            source_path=path,
            canonical_name=path.name,
            source=extension.source,
            source_kind=extension.source_kind,
            source_scope=extension.source_scope,
            source_root=path.parent,
            source_root_order=extension.source_root_order,
        ),
        None,
    )


__all__ = [
    "ExtensionResourceCatalogDiscovery",
    "ExtensionResourceRuntime",
    "coerce_resource_contribution",
]
