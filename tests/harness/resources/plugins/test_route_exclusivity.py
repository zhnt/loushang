from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import loushang.harness.resources.plugins as public_plugins
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import PluginResolutionAuthority
from loushang.harness.resources.plugins.manager import PluginManager
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)
from loushang.harness.resources.plugins.resolver import PluginResolver
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionError,
    PluginRevisionStore,
)
from loushang.harness.resources.plugins.types import (
    PublishedPluginPackage,
    ResolvedPluginPackage,
    VerifiedPluginRevision,
)


def test_public_plugin_surface_excludes_legacy_runtime_adapters() -> None:
    assert "PluginManager" not in public_plugins.__all__
    assert "PluginResolver" not in public_plugins.__all__
    assert not hasattr(public_plugins, "PluginManager")
    assert not hasattr(public_plugins, "PluginResolver")
    assert hasattr(public_plugins, "PluginResolutionAuthority")
    assert hasattr(public_plugins, "PublishedPluginPackage")


def test_package_states_cannot_be_confused_at_runtime(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "review-pack")
    resolved = PluginManifestParser().parse(root)

    assert isinstance(resolved, ResolvedPluginPackage)
    assert not isinstance(resolved, VerifiedPluginRevision)
    assert not hasattr(resolved, "content_digest")
    assert not hasattr(resolved, "revision_handle")
    assert not hasattr(resolved, "dependency_lock")

    verified = PluginRevisionStore(tmp_path / "revisions").publish(resolved)
    assert isinstance(verified, VerifiedPluginRevision)
    assert not isinstance(verified, PublishedPluginPackage)
    assert not hasattr(verified, "dependency_lock")
    with pytest.raises(ValueError, match="revision evidence"):
        replace(verified, content_digest="0" * 64)

    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    with pytest.raises(PluginManifestError) as caught:
        materializer.bind_plugin_packages((verified,))  # type: ignore[arg-type]
    assert caught.value.code == "unpublished_plugin_package"
    verified.revision_handle.close()


def test_legacy_manager_and_resolver_cannot_publish_runtime_resources(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "review-pack")
    manager = PluginManager()

    plugin = manager.add_plugin_source(root)
    assert plugin.enabled is False
    assert manager.enable_plugin("review-pack").enabled is False
    assert manager.refresh_plugins()[0].enabled is False
    assert manager.list_enabled_plugins() == []
    with pytest.raises(PluginManifestError) as caught:
        manager.resolve_plugin("review-pack")
    assert caught.value.code == "plugin_manager_inventory_only"
    with pytest.raises(PluginManifestError) as caught:
        manager.resolve_package_roots()
    assert caught.value.code == "plugin_manager_inventory_only"

    direct_plugin = PluginResolver().resolve_plugin(root)
    with pytest.raises(PluginManifestError) as caught:
        PluginResolver().resolve_resources(direct_plugin)
    assert caught.value.code == "plugin_runtime_authority_required"


def test_authority_alone_projects_published_frozen_resources(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "review-pack")
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(public_plugins.PluginSource(path=root))
    assert inspection.plugin is not None
    with pytest.raises(PluginManifestError) as caught:
        authority.resolve_resources(inspection.plugin)
    assert caught.value.code == "unpublished_plugin_package"

    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    runtime = authority.publish_runtime((inspection,), binding_store=materializer)
    published = runtime.packages[0]
    plugin = runtime.plugins[0]
    original_root = published.root

    (root / "plugin.json").write_text(
        json.dumps({"name": "mutated-after-publication"}),
        encoding="utf-8",
    )

    resources = authority.resolve_resources(plugin)
    assert resources.package_roots == (original_root,)
    with pytest.raises(PluginManifestError) as caught:
        PluginResolver().resolve_resources(plugin)
    assert caught.value.code == "plugin_runtime_authority_required"

    published.revision_handle.close()
    with pytest.raises(PluginRevisionError):
        authority.resolve_resources(plugin)


def _plugin(root: Path) -> Path:
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack"}),
        encoding="utf-8",
    )
    return root
