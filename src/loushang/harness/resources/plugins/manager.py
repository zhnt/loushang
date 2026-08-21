from __future__ import annotations

from pathlib import Path

from loushang.harness.resources.plugins.lifecycle import is_remote_plugin_source
from loushang.harness.resources.plugins.registry import PluginRegistry
from loushang.harness.resources.plugins.resolver import PluginResolver
from loushang.harness.resources.plugins.types import (
    InstalledPlugin,
    PluginResolvedResources,
    PluginSource,
    ResolvedPluginPackage,
)


class PluginManager:
    def __init__(
        self,
        *,
        resolver: PluginResolver | None = None,
        registry: PluginRegistry | None = None,
        disabled_plugins: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.resolver = resolver or PluginResolver()
        self.registry = registry or PluginRegistry()
        self._sources: dict[Path, PluginSource] = {}
        self._remote_sources: dict[str, PluginSource] = {}
        self._disabled_plugins = set(disabled_plugins or ())

    def add_plugin_source(
        self, path: str | Path, *, enabled: bool = True
    ) -> InstalledPlugin:
        if isinstance(path, str) and is_remote_plugin_source(path):
            source = PluginSource(url=path, kind="remote", enabled=enabled)
            self._remote_sources[path] = source
            return self.registry.register(self.resolver.resolve_plugin(source))
        source_path = Path(path).expanduser().resolve()
        source = PluginSource(path=source_path, enabled=enabled)
        return self.add_resolved_plugin_package(
            self.resolver.resolve_package(source)
        )

    def add_resolved_plugin_package(
        self,
        package: ResolvedPluginPackage,
    ) -> InstalledPlugin:
        """Register one descriptor while applying Product disable state once."""

        source = package.source
        if source.kind == "remote":
            if source.url is None:
                raise ValueError("Materialized remote plugin requires a source URL.")
            self._remote_sources[source.url] = source
        else:
            if source.path is None:
                raise ValueError("Local plugin source requires a path.")
            self._sources[source.path] = source
        plugin = self.resolver.project_package(
            package,
            source_enabled=(
                source.enabled and package.manifest.name not in self._disabled_plugins
            ),
        )
        return self.registry.register(plugin)

    def remove_plugin_source(self, path: str | Path) -> InstalledPlugin | None:
        if isinstance(path, str) and is_remote_plugin_source(path):
            source = self._remote_sources.pop(path, None)
            if source is None:
                return None
            plugin = self.resolver.resolve_plugin(source)
            return self.registry.unregister(plugin.manifest.name)
        source_path = Path(path).expanduser().resolve()
        source = self._sources.pop(source_path, None)
        if source is None:
            return None
        plugin = self.resolver.resolve_plugin(source)
        return self.registry.unregister(plugin.manifest.name)

    def enable_plugin(self, name: str) -> InstalledPlugin:
        return self._set_plugin_enabled(name, True)

    def disable_plugin(self, name: str) -> InstalledPlugin:
        return self._set_plugin_enabled(name, False)

    def refresh_plugins(self) -> list[InstalledPlugin]:
        refreshed: list[InstalledPlugin] = []
        for source in list(self._sources.values()):
            plugin = self.add_resolved_plugin_package(
                self.resolver.resolve_package(source)
            )
            refreshed.append(plugin)
        for source in list(self._remote_sources.values()):
            if source.path is None:
                plugin = self.registry.register(self.resolver.resolve_plugin(source))
            else:
                plugin = self.add_resolved_plugin_package(
                    self.resolver.resolve_package(source)
                )
            refreshed.append(plugin)
        return refreshed

    def list_plugins(self) -> list[InstalledPlugin]:
        return self.registry.list_plugins()

    def get_plugin(self, name: str) -> InstalledPlugin | None:
        return self.registry.get_plugin(name)

    def list_enabled_plugins(self) -> list[InstalledPlugin]:
        return self.registry.list_enabled_plugins()

    def list_remote_plugins(self) -> list[InstalledPlugin]:
        return [
            plugin
            for plugin in self.registry.list_plugins()
            if plugin.source.kind == "remote"
        ]

    def resolve_plugin(self, name: str) -> PluginResolvedResources:
        plugin = self.registry.get_plugin(name)
        if plugin is None:
            raise KeyError(name)
        return self.resolver.resolve_resources(plugin)

    def resolve_package_roots(self) -> tuple[Path, ...]:
        roots: list[Path] = []
        for plugin in self.registry.list_enabled_plugins():
            if plugin.source.kind == "remote" and plugin.source.path is None:
                continue
            roots.extend(self.resolver.resolve_resources(plugin).package_roots)
        return tuple(roots)

    def _set_plugin_enabled(self, name: str, enabled: bool) -> InstalledPlugin:
        plugin = self.registry.get_plugin(name)
        if plugin is None:
            raise KeyError(name)
        if plugin.source.kind == "remote":
            source_url = plugin.source.url
            if source_url is None:
                raise ValueError(f"remote plugin {name!r} has no source URL")
            source = PluginSource(
                path=plugin.source.path,
                url=source_url,
                kind="remote",
                enabled=enabled,
            )
            self._remote_sources[source_url] = source
        else:
            source_path = plugin.source.path
            if source_path is None:
                raise ValueError(f"local plugin {name!r} has no source path")
            source = PluginSource(path=source_path, enabled=enabled)
            self._sources[source_path] = source
        if enabled:
            self._disabled_plugins.discard(name)
        else:
            self._disabled_plugins.add(name)
        if source.path is None:
            updated = self.resolver.resolve_plugin(source)
            return self.registry.register(updated)
        return self.add_resolved_plugin_package(
            self.resolver.resolve_package(source)
        )
