from __future__ import annotations

import json


def test_plugin_manager_resolves_local_plugin_package_roots(tmp_path) -> None:
    from loushang.harness.resources.plugins import PluginManager

    plugin_root = tmp_path / "plugins" / "review-pack"
    package_root = plugin_root / "package"
    package_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "version": "1.0.0", "packageRoot": "package"}),
        encoding="utf-8",
    )

    manager = PluginManager()
    plugin = manager.add_plugin_source(plugin_root)

    assert plugin.manifest.name == "review-pack"
    assert plugin.manifest.version == "1.0.0"
    assert manager.get_plugin("review-pack") == plugin
    assert manager.resolve_plugin("review-pack").package_roots == (package_root.resolve(),)
    assert manager.resolve_package_roots() == (package_root.resolve(),)


def test_plugin_manager_package_roots_feed_default_resource_loader(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources.plugins import PluginManager

    project = tmp_path / "project"
    plugin_root = tmp_path / "plugins" / "debug-pack"
    skill_dir = plugin_root / "skills" / "debug"
    project.mkdir()
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Debugging skill", encoding="utf-8")

    manager = PluginManager()
    manager.add_plugin_source(plugin_root)

    loader = DefaultResourceLoader(package_roots=manager.resolve_package_roots())
    bundle = loader.discover_resources(project)

    assert [skill.name for skill in bundle.skills] == ["debug"]
    assert bundle.skills[0].source_kind == "external_package"
    assert bundle.skills[0].content == "Debugging skill"


def test_plugin_manager_can_disable_and_refresh_plugins(tmp_path) -> None:
    from loushang.harness.resources.plugins import PluginManager

    plugin_root = tmp_path / "plugins" / "demo"
    plugin_root.mkdir(parents=True)

    manager = PluginManager()
    manager.add_plugin_source(plugin_root)
    assert [plugin.manifest.name for plugin in manager.list_enabled_plugins()] == ["demo"]

    disabled = manager.disable_plugin("demo")
    assert disabled.enabled is False
    assert manager.list_enabled_plugins() == []
    assert manager.resolve_package_roots() == ()

    (plugin_root / "plugin.json").write_text(json.dumps({"name": "renamed"}), encoding="utf-8")
    refreshed = manager.refresh_plugins()
    assert [plugin.manifest.name for plugin in refreshed] == ["renamed"]


def test_plugin_manager_accepts_initial_disabled_plugins(tmp_path) -> None:
    from loushang.harness.resources.plugins import PluginManager

    plugin_root = tmp_path / "plugins" / "demo"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "demo"}), encoding="utf-8")

    manager = PluginManager(disabled_plugins=("demo",))
    plugin = manager.add_plugin_source(plugin_root)

    assert plugin.enabled is False
    assert manager.list_enabled_plugins() == []


def test_plugin_manager_tracks_https_remote_sources_without_local_resolution() -> None:
    from loushang.harness.resources.plugins import PluginManager

    manager = PluginManager()
    source = "https://packages.example.invalid/review-pack.git"

    remote = manager.add_plugin_source(source)

    assert remote.manifest.name == "review-pack"
    assert remote.enabled is False
    assert remote.source.kind == "remote"
    assert remote.source.url == source
    assert manager.resolve_package_roots() == ()
    assert manager.list_remote_plugins() == [remote]


def test_plugin_types_are_exported_from_harness() -> None:
    from loushang.harness.resources.plugins import (
        PluginManager,
        PluginManifest,
        PluginRegistry,
        PluginResolver,
        PluginSource,
    )

    assert PluginManager is not None
    assert PluginManifest is not None
    assert PluginRegistry is not None
    assert PluginResolver is not None
    assert PluginSource is not None
