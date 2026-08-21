from __future__ import annotations

from pathlib import Path

from loushang.harness.resources.plugins.lifecycle import is_remote_plugin_source
from loushang.harness.resources.plugins.manifest import PluginManifestError
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
        self._source_plugin_ids: dict[tuple[str, str], str] = {}
        self._bound_plugins: dict[tuple[str, str], InstalledPlugin] = {}
        self._disabled_plugins = set(disabled_plugins or ())

    def add_plugin_source(
        self, path: str | Path, *, enabled: bool = True
    ) -> InstalledPlugin:
        if isinstance(path, str) and is_remote_plugin_source(path):
            source = PluginSource(url=path, kind="remote", enabled=enabled)
            plugin = self.resolver.resolve_plugin(source)
            return self._register_bound_plugin(source, plugin)
        source = PluginSource(path=Path(path).expanduser(), enabled=enabled)
        return self.add_resolved_plugin_package(
            self.resolver.resolve_package(source)
        )

    def add_resolved_plugin_package(
        self,
        package: ResolvedPluginPackage,
    ) -> InstalledPlugin:
        """Register one descriptor while applying Product disable state once."""

        source = package.source
        plugin = self._project_resolved_package(package)
        return self._register_bound_plugin(source, plugin)

    def remove_plugin_source(self, path: str | Path) -> InstalledPlugin | None:
        if isinstance(path, str) and is_remote_plugin_source(path):
            source = self._remote_sources.get(path)
            if source is None:
                return None
            return self._remove_bound_source(source)
        source_path = Path(path).expanduser().resolve()
        source = self._sources.get(source_path)
        if source is None:
            return None
        return self._remove_bound_source(source)

    def enable_plugin(self, name: str) -> InstalledPlugin:
        return self._set_plugin_enabled(name, True)

    def disable_plugin(self, name: str) -> InstalledPlugin:
        return self._set_plugin_enabled(name, False)

    def refresh_plugins(self) -> list[InstalledPlugin]:
        prepared: list[tuple[PluginSource, InstalledPlugin]] = []
        for source in list(self._sources.values()):
            package = self.resolver.resolve_package(source)
            plugin = self._project_resolved_package(package)
            self._assert_source_identity(source, plugin.manifest.name)
            prepared.append((source, plugin))
        for source in list(self._remote_sources.values()):
            plugin = (
                self.resolver.resolve_plugin(source)
                if source.path is None
                else self._project_resolved_package(
                    self.resolver.resolve_package(source)
                )
            )
            self._assert_source_identity(source, plugin.manifest.name)
            prepared.append((source, plugin))
        return [
            self._register_bound_plugin(source, plugin)
            for source, plugin in prepared
        ]

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
        else:
            source_path = plugin.source.path
            if source_path is None:
                raise ValueError(f"local plugin {name!r} has no source path")
            source = PluginSource(path=source_path, enabled=enabled)
        if source.path is None:
            updated = self.resolver.resolve_plugin(source)
            self._assert_source_identity(source, updated.manifest.name)
            if enabled:
                self._disabled_plugins.discard(name)
            else:
                self._disabled_plugins.add(name)
            return self._register_bound_plugin(source, updated)
        package = self.resolver.resolve_package(source)
        self._assert_source_identity(source, package.manifest.name)
        if enabled:
            self._disabled_plugins.discard(name)
        else:
            self._disabled_plugins.add(name)
        return self.add_resolved_plugin_package(package)

    def _register_bound_plugin(
        self,
        source: PluginSource,
        plugin: InstalledPlugin,
    ) -> InstalledPlugin:
        key = _source_key(source)
        self._assert_source_identity(source, plugin.manifest.name)
        registered = self.registry.register(plugin)
        if source.kind == "remote":
            assert source.url is not None
            self._remote_sources[source.url] = source
        else:
            assert source.path is not None
            self._sources[source.path] = source
        self._source_plugin_ids[key] = plugin.manifest.name
        self._bound_plugins[key] = plugin
        return registered

    def _project_resolved_package(
        self,
        package: ResolvedPluginPackage,
    ) -> InstalledPlugin:
        source = package.source
        return self.resolver.project_package(
            package,
            source_enabled=(
                source.enabled and package.manifest.name not in self._disabled_plugins
            ),
        )

    def _assert_source_identity(self, source: PluginSource, plugin_id: str) -> None:
        key = _source_key(source)
        bound_id = self._source_plugin_ids.get(key)
        if bound_id is None or bound_id == plugin_id:
            return
        path = source.path or Path(source.url or "")
        raise PluginManifestError(
            f"Plugin source identity changed from {bound_id!r} to {plugin_id!r}: "
            f"{path}",
            code="plugin_identity_changed",
            path=path,
        )

    def _remove_bound_source(self, source: PluginSource) -> InstalledPlugin | None:
        key = _source_key(source)
        plugin_id = self._source_plugin_ids.pop(key, None)
        removed = self._bound_plugins.pop(key, None)
        if source.kind == "remote":
            assert source.url is not None
            self._remote_sources.pop(source.url, None)
        else:
            assert source.path is not None
            self._sources.pop(source.path, None)
        if plugin_id is None:
            return None
        current = self.registry.get_plugin(plugin_id)
        if current is not None and _source_key(current.source) == key:
            self.registry.unregister(plugin_id)
            replacement_entry = next(
                (
                    (candidate_key, candidate)
                    for candidate_key, candidate in reversed(
                        self._bound_plugins.items()
                    )
                    if self._source_plugin_ids.get(candidate_key) == plugin_id
                ),
                None,
            )
            if replacement_entry is not None:
                replacement_key, replacement = replacement_entry
                if replacement.resolved_package is not None:
                    replacement = self._project_resolved_package(
                        replacement.resolved_package
                    )
                    self._bound_plugins[replacement_key] = replacement
                self.registry.register(replacement)
        return removed


def _source_key(source: PluginSource) -> tuple[str, str]:
    if source.kind == "remote":
        if source.url is None:
            raise ValueError("Remote plugin source requires a URL.")
        return "remote", source.url
    if source.path is None:
        raise ValueError("Local plugin source requires a path.")
    return "local", str(source.path)
