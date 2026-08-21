from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from loushang.harness.resources.plugins.lifecycle import (
    is_remote_plugin_source,
    remote_plugin_name,
)
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)
from loushang.harness.resources.plugins.types import (
    InstalledPlugin,
    PluginManifest,
    PluginResolvedResources,
    PluginSource,
    ResolvedPluginPackage,
)


class PluginResolver:
    """Resolve local plugin directories into resource-loader package roots."""

    def __init__(
        self,
        *,
        manifest_parser: PluginManifestParser | None = None,
    ) -> None:
        self._manifest_parser = manifest_parser or PluginManifestParser()

    def resolve_package(
        self,
        source: PluginSource | str | Path,
    ) -> ResolvedPluginPackage:
        """Resolve one local source through the canonical manifest authority."""

        plugin_source = (
            source
            if isinstance(source, PluginSource)
            else _plugin_source_from_input(source)
        )
        if plugin_source.kind == "remote" and plugin_source.path is None:
            raise ValueError(
                "Remote plugin sources must be materialized before manifest resolution."
            )
        if plugin_source.path is None:
            raise ValueError("Local plugin source requires a path.")
        return self._manifest_parser.parse(
            plugin_source.path,
            source=plugin_source,
        )

    def project_package(
        self,
        resolved_package: ResolvedPluginPackage,
        *,
        source_enabled: bool | None = None,
    ) -> InstalledPlugin:
        """Project effective installed state without reparsing the package."""

        enabled = (
            resolved_package.source.enabled
            if source_enabled is None
            else source_enabled
        )
        source = replace(resolved_package.source, enabled=enabled)
        return InstalledPlugin(
            manifest=resolved_package.manifest,
            source=source,
            enabled=enabled and resolved_package.manifest.enabled,
            resolved_package=resolved_package,
        )

    def resolve_plugin(self, source: PluginSource | str | Path) -> InstalledPlugin:
        plugin_source = (
            source
            if isinstance(source, PluginSource)
            else _plugin_source_from_input(source)
        )
        if plugin_source.kind == "remote" and plugin_source.path is None:
            url = plugin_source.url or ""
            name = remote_plugin_name(url)
            manifest = PluginManifest(
                name=name,
                root=Path(),
                enabled=False,
                metadata={
                    "source": url,
                    "lifecycle": "remote_registered",
                    "security": "allowed",
                },
            )
            return InstalledPlugin(
                manifest=manifest, source=plugin_source, enabled=False
            )
        if plugin_source.path is None:
            raise ValueError("Local plugin source requires a path.")
        resolved_package = self.resolve_package(plugin_source)
        return self.project_package(resolved_package)

    def resolve_resources(self, plugin: InstalledPlugin) -> PluginResolvedResources:
        if not plugin.enabled:
            return PluginResolvedResources(plugin=plugin, package_roots=())
        if plugin.resolved_package is None:
            raise PluginManifestError(
                f"Enabled plugin has no canonical resolved package: "
                f"{plugin.manifest.root}",
                code="unresolved_plugin_package",
                path=plugin.manifest.root,
            )
        handle = plugin.resolved_package.revision_handle
        if handle is not None:
            handle.verify()
        package = self._manifest_parser.revalidate(plugin.resolved_package)
        if handle is not None:
            handle.verify()
        package_root = package.package_root
        return PluginResolvedResources(
            plugin=plugin,
            package_roots=(package_root,),
            revision_handle=package.revision_handle,
        )


def _plugin_source_from_input(source: str | Path) -> PluginSource:
    if isinstance(source, str) and is_remote_plugin_source(source):
        return PluginSource(url=source, kind="remote")
    return PluginSource(path=Path(source))
