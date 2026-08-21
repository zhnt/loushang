from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from loushang.harness.resources.plugins.manifest import PluginManifestError
from loushang.harness.resources.plugins.resolver import PluginResolver
from loushang.harness.resources.plugins.types import (
    InstalledPlugin,
    PluginResolvedResources,
    PluginSource,
    PluginSourceBinding,
    ResolvedPluginPackage,
)


class PluginBindingValidator(Protocol):
    """Read-only validation port used by inventory resolution."""

    def validate_plugin_package(self, package: ResolvedPluginPackage) -> None: ...


class PluginBindingStore(Protocol):
    """Runtime publication and durable source-binding port."""

    def publish_plugin_packages(
        self,
        packages: Sequence[ResolvedPluginPackage],
    ) -> tuple[ResolvedPluginPackage, ...]: ...

    def bind_plugin_packages(
        self,
        packages: Sequence[ResolvedPluginPackage],
    ) -> tuple[PluginSourceBinding, ...]: ...


@dataclass(frozen=True)
class PluginResolutionDiagnostic:
    code: str
    message: str
    path: Path

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "path": str(self.path),
        }


@dataclass(frozen=True)
class PluginInspection:
    """Read-only projection of one configured source.

    Inventory callers may retain a broken or not-yet-materialized source.  A
    runtime caller may publish only inspections carrying a canonical package
    and no diagnostics.
    """

    source: PluginSource
    package: ResolvedPluginPackage | None = None
    plugin: InstalledPlugin | None = None
    diagnostics: tuple[PluginResolutionDiagnostic, ...] = ()
    error: Exception | None = field(default=None, compare=False, repr=False)

    @property
    def runtime_ready(self) -> bool:
        return self.package is not None and not self.diagnostics

    def raise_for_error(self) -> None:
        if self.error is not None:
            raise self.error


@dataclass(frozen=True)
class PluginRuntimeResolution:
    packages: tuple[ResolvedPluginPackage, ...]
    plugins: tuple[InstalledPlugin, ...]
    bindings: tuple[PluginSourceBinding, ...]

    def close(self) -> None:
        closed: set[int] = set()
        for package in self.packages:
            handle = package.revision_handle
            if handle is not None and id(handle) not in closed:
                handle.close()
                closed.add(id(handle))


class PluginResolutionAuthority:
    """Single Plugin source path for inventory and runtime admission.

    ``inspect`` is read-only. ``publish_runtime`` is the only production
    transition from inspected mutable sources to durable bindings over
    published revisions.
    """

    def __init__(
        self,
        *,
        resolver: PluginResolver | None = None,
        disabled_plugins: Sequence[str] = (),
    ) -> None:
        self._resolver = resolver or PluginResolver()
        self._disabled_plugins = frozenset(disabled_plugins)

    @property
    def resolver(self) -> PluginResolver:
        return self._resolver

    def inspect(
        self,
        source: PluginSource,
        *,
        binding_validator: PluginBindingValidator | None = None,
    ) -> PluginInspection:
        """Parse and project one source without publishing or writing state."""

        if source.kind == "remote" and source.path is None:
            return PluginInspection(
                source=source,
                plugin=self._resolver.resolve_plugin(source),
            )
        try:
            package = self._resolver.resolve_package(source)
        except (FileNotFoundError, PluginManifestError, ValueError) as exc:
            return _failed_inspection(source, exc)

        plugin = self.project_package(package)
        if binding_validator is None:
            return PluginInspection(
                source=package.source,
                package=package,
                plugin=plugin,
            )
        try:
            binding_validator.validate_plugin_package(package)
        except PluginManifestError as exc:
            return PluginInspection(
                source=package.source,
                package=package,
                plugin=plugin,
                diagnostics=(_diagnostic(exc, source=package.source),),
                error=exc,
            )
        return PluginInspection(
            source=package.source,
            package=package,
            plugin=plugin,
        )

    def project_package(self, package: ResolvedPluginPackage) -> InstalledPlugin:
        source_enabled = (
            package.source.enabled
            and package.manifest.name not in self._disabled_plugins
        )
        return self._resolver.project_package(
            package,
            source_enabled=source_enabled,
        )

    def publish_runtime(
        self,
        inspections: Sequence[PluginInspection],
        *,
        binding_store: PluginBindingStore,
    ) -> PluginRuntimeResolution:
        """Publish all inspected packages, then atomically bind the batch."""

        packages: list[ResolvedPluginPackage] = []
        for inspection in inspections:
            if not inspection.runtime_ready:
                inspection.raise_for_error()
                raise PluginManifestError(
                    "Plugin source has no runtime-ready resolved package: "
                    f"{_source_path(inspection.source)}",
                    code="unresolved_plugin_package",
                    path=_source_path(inspection.source),
                )
            assert inspection.package is not None
            packages.append(inspection.package)

        published: tuple[ResolvedPluginPackage, ...] = ()
        try:
            published = tuple(binding_store.publish_plugin_packages(packages))
            _assert_published_lineage(tuple(packages), published)
            _verify_published_packages(published)
            bindings = tuple(binding_store.bind_plugin_packages(published))
            _assert_binding_lineage(published, bindings)
            plugins = tuple(self.project_package(package) for package in published)
        except Exception as exc:
            _annotate_source_error(exc, published)
            _close_packages(published)
            raise
        return PluginRuntimeResolution(
            packages=published,
            plugins=plugins,
            bindings=bindings,
        )

    def resolve_resources(self, plugin: InstalledPlugin) -> PluginResolvedResources:
        return self._resolver.resolve_resources(plugin)


def _failed_inspection(
    source: PluginSource,
    error: Exception,
) -> PluginInspection:
    return PluginInspection(
        source=source,
        diagnostics=(_diagnostic(error, source=source),),
        error=error,
    )


def _diagnostic(
    error: Exception,
    *,
    source: PluginSource,
) -> PluginResolutionDiagnostic:
    if isinstance(error, PluginManifestError):
        return PluginResolutionDiagnostic(
            code=error.code,
            message=str(error),
            path=error.path,
        )
    return PluginResolutionDiagnostic(
        code="plugin_source_unresolved",
        message=str(error),
        path=_source_path(source),
    )


def _source_path(source: PluginSource) -> Path:
    if source.path is not None:
        return source.path
    return Path(source.url or "")


def _assert_published_lineage(
    inspected: tuple[ResolvedPluginPackage, ...],
    published: tuple[ResolvedPluginPackage, ...],
) -> None:
    if len(inspected) != len(published):
        path = inspected[0].root if inspected else Path()
        raise PluginManifestError(
            "Plugin revision publisher changed the resolved package count.",
            code="invalid_plugin_revision_publication",
            path=path,
        )
    for before, after in zip(inspected, published, strict=True):
        if before.source != after.source or before.manifest.name != after.manifest.name:
            raise PluginManifestError(
                "Plugin revision publisher changed source or Plugin identity: "
                f"{before.root}",
                code="invalid_plugin_revision_publication",
                path=before.root,
            )


def _close_packages(packages: Sequence[ResolvedPluginPackage]) -> None:
    closed: set[int] = set()
    for package in packages:
        handle = package.revision_handle
        if handle is not None and id(handle) not in closed:
            handle.close()
            closed.add(id(handle))


def _verify_published_packages(
    packages: Sequence[ResolvedPluginPackage],
) -> None:
    for package in packages:
        handle = package.revision_handle
        if handle is None or package.content_digest is None:
            raise PluginManifestError(
                f"Plugin revision publisher returned an unverified package: "
                f"{package.root}",
                code="unverified_plugin_revision",
                path=package.root,
            )
        dependency_lock = package.dependency_lock
        if dependency_lock is None:
            raise PluginManifestError(
                "Plugin revision publisher returned no dependency closure lock: "
                f"{package.root}",
                code="unverified_plugin_dependency_closure",
                path=package.root,
            )
        if (
            handle.root != package.root
            or handle.content_digest != package.content_digest
            or package.manifest.root != package.root
            or dependency_lock.package_content_digest != package.content_digest
        ):
            raise PluginManifestError(
                f"Plugin revision handle does not match the published package: "
                f"{package.root}",
                code="invalid_plugin_revision_publication",
                path=package.root,
            )
        handle.verify()


def _assert_binding_lineage(
    packages: Sequence[ResolvedPluginPackage],
    bindings: Sequence[PluginSourceBinding],
) -> None:
    if len(packages) != len(bindings):
        path = packages[0].root if packages else Path()
        raise PluginManifestError(
            "Plugin binding store changed the resolved package count.",
            code="invalid_plugin_source_binding",
            path=path,
        )
    for package, binding in zip(packages, bindings, strict=True):
        if (
            binding.plugin_id != package.manifest.name
            or binding.source_kind != package.source.kind
            or binding.source != _source_value(package.source)
            or binding.dependency_lock != package.dependency_lock
        ):
            raise PluginManifestError(
                "Plugin binding store changed source or Plugin identity: "
                f"{package.root}",
                code="invalid_plugin_source_binding",
                path=package.root,
            )


def _annotate_source_error(
    error: Exception,
    packages: Sequence[ResolvedPluginPackage],
) -> None:
    error_path = getattr(error, "path", None)
    if not isinstance(error_path, Path):
        return
    for package in packages:
        try:
            error_path.relative_to(package.root)
        except ValueError:
            continue
        with suppress(AttributeError, TypeError):
            setattr(error, "plugin_source", str(_source_value(package.source)))
        return


def _source_value(source: PluginSource) -> str:
    if source.kind == "remote" and source.url is not None:
        return source.url
    return str(source.path or "")


__all__ = [
    "PluginBindingStore",
    "PluginBindingValidator",
    "PluginInspection",
    "PluginResolutionAuthority",
    "PluginResolutionDiagnostic",
    "PluginRuntimeResolution",
]
