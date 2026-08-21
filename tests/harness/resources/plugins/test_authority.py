from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import PluginResolutionAuthority
from loushang.harness.resources.plugins.declarations import (
    PluginContributionIndex,
    PluginContributionReservation,
)
from loushang.harness.resources.plugins.manifest import PluginManifestError
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    ResolvedPluginPackage,
)


def test_inventory_inspection_does_not_publish_or_bind(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugins" / "review-pack")
    materializer = PackageMaterializer(install_root=tmp_path / "installed")

    inspection = PluginResolutionAuthority().inspect(
        PluginSource(path=root),
        binding_validator=materializer,
    )

    assert inspection.package is not None
    assert inspection.plugin is not None
    assert inspection.diagnostics == ()
    assert materializer.get_plugin_binding(root) is None
    assert materializer.lockfile_path.exists() is False
    assert (tmp_path / "plugin-revisions").exists() is False


def test_runtime_resolution_publishes_before_atomic_binding(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugins" / "review-pack")
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=root))
    store = _RecordingBindingStore(tmp_path / "revisions")

    resolution = authority.publish_runtime(
        (inspection,),
        binding_store=store,
    )

    assert store.events == ["publish", "bind"]
    assert inspection.package is not None
    assert resolution.packages[0].root != inspection.package.root
    assert resolution.packages[0].revision_handle is not None
    assert resolution.plugins[0].manifest.name == "review-pack"
    assert resolution.bindings[0].plugin_id == "review-pack"
    resolution.close()


def test_runtime_resolution_rejects_publisher_identity_change_before_binding(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review-pack")
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=root))
    store = _IdentityChangingBindingStore(tmp_path / "revisions")

    with pytest.raises(PluginManifestError) as caught:
        authority.publish_runtime((inspection,), binding_store=store)

    assert caught.value.code == "invalid_plugin_revision_publication"
    assert store.events == ["publish"]


def test_runtime_resolution_rejects_publisher_contribution_change_before_binding(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review-pack")
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=root))
    store = _ContributionChangingBindingStore(tmp_path / "revisions")

    with pytest.raises(PluginManifestError) as caught:
        authority.publish_runtime((inspection,), binding_store=store)

    assert caught.value.code == "invalid_plugin_revision_publication"
    assert store.events == ["publish"]


def test_runtime_resolution_rejects_unverified_publication_before_binding(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review-pack")
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=root))
    store = _UnverifiedBindingStore(tmp_path / "revisions")

    with pytest.raises(PluginManifestError) as caught:
        authority.publish_runtime((inspection,), binding_store=store)

    assert caught.value.code == "unpublished_plugin_package"
    assert store.events == ["publish"]


def test_runtime_resolution_rejects_missing_durable_binding(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugins" / "review-pack")
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=root))
    store = _MissingBindingStore(tmp_path / "revisions")

    with pytest.raises(PluginManifestError) as caught:
        authority.publish_runtime((inspection,), binding_store=store)

    assert caught.value.code == "invalid_plugin_source_binding"
    assert store.events == ["publish", "bind"]


def test_published_package_type_rejects_missing_dependency_closure(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugins" / "review-pack")
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=root))
    assert inspection.package is not None
    store = PackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    [published] = store.publish_plugin_packages((inspection.package,))

    with pytest.raises(ValueError, match="dependency lock"):
        replace(published, dependency_lock=None)

    published.revision_handle.close()


def _plugin(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "version": "1"}),
        encoding="utf-8",
    )
    return root


class _RecordingBindingStore:
    def __init__(self, root: Path | None = None) -> None:
        self.events: list[str] = []
        revision_root = root or Path.cwd() / ".test-plugin-revisions"
        self._delegate = PackageMaterializer(
            install_root=revision_root / "installed",
            plugin_revision_root=revision_root,
        )

    def publish_plugin_packages(
        self,
        packages: tuple[ResolvedPluginPackage, ...],
    ) -> tuple[ResolvedPluginPackage, ...]:
        self.events.append("publish")
        return self._delegate.publish_plugin_packages(packages)

    def bind_plugin_packages(
        self,
        packages: tuple[ResolvedPluginPackage, ...],
    ) -> tuple[PluginSourceBinding, ...]:
        self.events.append("bind")
        return self._delegate.bind_plugin_packages(packages)


class _IdentityChangingBindingStore(_RecordingBindingStore):
    def publish_plugin_packages(
        self,
        packages: tuple[ResolvedPluginPackage, ...],
    ) -> tuple[ResolvedPluginPackage, ...]:
        [package] = super().publish_plugin_packages(packages)
        return (
            replace(
                package,
                manifest=replace(package.manifest, name="renamed-pack"),
            ),
        )


class _ContributionChangingBindingStore(_RecordingBindingStore):
    def publish_plugin_packages(
        self,
        packages: tuple[ResolvedPluginPackage, ...],
    ) -> tuple[ResolvedPluginPackage, ...]:
        [package] = super().publish_plugin_packages(packages)
        return (
            replace(
                package,
                contribution_index=PluginContributionIndex(
                    items=(
                        PluginContributionReservation(
                            contribution_id="forged-provider",
                            kind="capability_provider",
                            owner="coding.lsp",
                            entrypoint="forged.py:declare",
                            execution_model="in_process",
                            requested_authorities=(),
                        ),
                    )
                ),
            ),
        )


class _UnverifiedBindingStore(_RecordingBindingStore):
    def publish_plugin_packages(
        self,
        packages: tuple[ResolvedPluginPackage, ...],
    ) -> tuple[ResolvedPluginPackage, ...]:
        self.events.append("publish")
        return packages


class _MissingBindingStore(_RecordingBindingStore):
    def bind_plugin_packages(
        self,
        packages: tuple[ResolvedPluginPackage, ...],
    ) -> tuple[PluginSourceBinding, ...]:
        del packages
        self.events.append("bind")
        return ()
