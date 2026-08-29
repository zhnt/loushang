from __future__ import annotations

import json
from pathlib import Path


def test_plugin_authority_publishes_local_package_roots(tmp_path: Path) -> None:
    from loushang.coding.resource_runtime import CodingPackageMaterializer
    from loushang.harness.resources.plugins import (
        PluginResolutionAuthority,
        PluginSource,
    )

    plugin_root = _plugin(
        tmp_path / "plugins" / "review-pack",
        name="review-pack",
        package_root="package",
    )
    package_root = plugin_root / "package"
    package_root.mkdir()
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=plugin_root))
    materializer = CodingPackageMaterializer(install_root=tmp_path / "installed")

    runtime = authority.publish_runtime((inspection,), binding_store=materializer)
    try:
        [plugin] = runtime.plugins
        resources = authority.resolve_resources(plugin)

        assert plugin.manifest.name == "review-pack"
        assert plugin.manifest.version == "1.0.0"
        assert resources.package_roots == (runtime.packages[0].root / "package",)
        assert resources.package_roots[0] != package_root
    finally:
        runtime.close()


def test_published_plugin_roots_feed_coding_resource_loader(tmp_path: Path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer,
        CodingResourceLoader,
    )
    from loushang.harness.resources.plugins import (
        PluginResolutionAuthority,
        PluginSource,
    )

    project = tmp_path / "project"
    project.mkdir()
    plugin_root = _plugin(tmp_path / "plugins" / "debug-pack", name="debug-pack")
    skill_dir = plugin_root / "skills" / "debug"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Debugging skill", encoding="utf-8")
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=plugin_root))
    materializer = CodingPackageMaterializer(install_root=tmp_path / "installed")

    runtime = authority.publish_runtime((inspection,), binding_store=materializer)
    try:
        roots = authority.resolve_resources(runtime.plugins[0]).package_roots
        bundle = CodingResourceLoader(package_roots=roots).discover_resources(project)

        assert [skill.name for skill in bundle.skills] == ["debug"]
        assert bundle.skills[0].source_kind == "external_package"
        assert bundle.skills[0].content == "Debugging skill"
    finally:
        runtime.close()


def test_plugin_authority_applies_product_disabled_policy(tmp_path: Path) -> None:
    from loushang.harness.resources.plugins import (
        PluginResolutionAuthority,
        PluginSource,
    )

    plugin_root = _plugin(tmp_path / "plugins" / "demo", name="demo")
    inspection = PluginResolutionAuthority(disabled_plugins=("demo",)).inspect(
        PluginSource(path=plugin_root)
    )

    assert inspection.plugin is not None
    assert inspection.plugin.enabled is False
    assert inspection.runtime_ready is True


def test_remote_plugin_source_remains_inert_without_materialization() -> None:
    from loushang.harness.resources.plugins import (
        PluginResolutionAuthority,
        PluginSource,
    )

    source = "https://packages.example.invalid/review-pack.git"
    inspection = PluginResolutionAuthority().inspect(
        PluginSource(url=source, kind="remote")
    )

    assert inspection.package is None
    assert inspection.plugin is not None
    assert inspection.plugin.enabled is False
    assert inspection.plugin.source.url == source
    assert inspection.runtime_ready is False


def test_public_plugin_surface_excludes_retired_inventory_adapters() -> None:
    import loushang.harness.resources.plugins as public_plugins

    assert hasattr(public_plugins, "PluginResolutionAuthority")
    assert hasattr(public_plugins, "PluginRegistry")
    assert hasattr(public_plugins, "PluginSource")
    assert not hasattr(public_plugins, "PluginManager")
    assert not hasattr(public_plugins, "PluginResolver")


def _plugin(
    root: Path,
    *,
    name: str,
    package_root: str | None = None,
) -> Path:
    root.mkdir(parents=True)
    manifest: dict[str, object] = {"name": name, "version": "1.0.0"}
    if package_root is not None:
        manifest["packageRoot"] = package_root
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root
