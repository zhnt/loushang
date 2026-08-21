from __future__ import annotations

from pathlib import Path

from loushang.harness.resources.plugins.lifecycle import (
    is_remote_plugin_source,
    remote_plugin_name,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
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
        if plugin_source.kind == "remote":
            raise ValueError(
                "Remote plugin sources must be materialized before manifest resolution."
            )
        if plugin_source.path is None:
            raise ValueError("Local plugin source requires a path.")
        return self._manifest_parser.parse(
            plugin_source.path,
            source=plugin_source,
        )

    def resolve_plugin(self, source: PluginSource | str | Path) -> InstalledPlugin:
        plugin_source = (
            source
            if isinstance(source, PluginSource)
            else _plugin_source_from_input(source)
        )
        if plugin_source.kind == "remote":
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
        manifest = resolved_package.manifest
        return InstalledPlugin(
            manifest=manifest,
            source=resolved_package.source,
            enabled=plugin_source.enabled and manifest.enabled,
            resolved_package=resolved_package,
        )

    def resolve_resources(self, plugin: InstalledPlugin) -> PluginResolvedResources:
        if not plugin.enabled:
            return PluginResolvedResources(plugin=plugin, package_roots=())
        package_root = (
            plugin.resolved_package.package_root
            if plugin.resolved_package is not None
            else plugin.manifest.package_root or plugin.manifest.root
        )
        return PluginResolvedResources(plugin=plugin, package_roots=(package_root,))


def _plugin_source_from_input(source: str | Path) -> PluginSource:
    if isinstance(source, str) and is_remote_plugin_source(source):
        return PluginSource(url=source, kind="remote")
    return PluginSource(path=Path(source))
