from __future__ import annotations

from pathlib import Path

from loushang.harness.resources.plugins.lifecycle import is_remote_plugin_source
from loushang.harness.resources.plugins.registry import PluginRegistry
from loushang.harness.resources.plugins.resolver import PluginResolver
from loushang.harness.resources.plugins.types import (
    InstalledPlugin,
    PluginResolvedResources,
    PluginSource,
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
        self._sources[source_path] = source
        plugin = self.resolver.resolve_plugin(source)
        if plugin.manifest.name in self._disabled_plugins:
            plugin = self.resolver.resolve_plugin(
                PluginSource(path=source_path, enabled=False)
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
            plugin = self.resolver.resolve_plugin(source)
            if plugin.manifest.name in self._disabled_plugins:
                plugin = self.resolver.resolve_plugin(
                    PluginSource(path=source.path, enabled=False)
                )
            self.registry.register(plugin)
            refreshed.append(plugin)
        for source in list(self._remote_sources.values()):
            plugin = self.resolver.resolve_plugin(source)
            self.registry.register(plugin)
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
            if plugin.source.kind == "remote":
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
        updated = self.resolver.resolve_plugin(source)
        return self.registry.register(updated)
