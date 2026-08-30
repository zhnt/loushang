from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.resources._catalog_input_receipt import (
    CatalogPluginPackageInput,
)
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
    PackageMaterializer,
    resolve_session_package_install_root,
)
from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.packages.roots import (
    SelectedPluginPackageInput,
    configure_resource_loader_roots,
    resolve_package_resource_roots,
)
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.plugins.authority import PluginResolutionAuthority
from loushang.harness.resources.plugins.dependencies import (
    lock_plugin_dependency_closure,
)
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionError,
    PluginRevisionStore,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
    ResolvedPluginPackage,
)


@dataclass(frozen=True)
class _Settings:
    package_roots: tuple[str, ...]
    plugin_sources: tuple[str, ...] = ()
    package_sources: tuple[PackageSourceConfig, ...] = ()
    disabled_plugins: tuple[str, ...] = ()


class _SettingsManager:
    def __init__(self, settings: _Settings, global_base_dir: Path) -> None:
        self._settings = settings
        self.global_base_dir = global_base_dir
        self.project_base_dir = None

    def get_settings(self) -> _Settings:
        return self._settings

    def get_global_settings(self) -> dict[str, object]:
        return {"resource_roots": ["resources"]}


class _Loader:
    def __init__(self) -> None:
        self.mounts: tuple[PackageResourceMount, ...] = ()
        self.package_roots: tuple[str, ...] = ()
        self.user_roots: tuple[Path, ...] = ()
        self.explicit_roots: frozenset[Path] = frozenset()

    def set_package_mounts(
        self,
        mounts: tuple[PackageResourceMount, ...],
        *,
        catalog_plugin_package_inputs: tuple[CatalogPluginPackageInput, ...] = (),
    ) -> None:
        del catalog_plugin_package_inputs
        self.mounts = mounts
        self.package_roots = tuple(str(mount.root) for mount in mounts if mount.enabled)

    def set_user_resource_roots(
        self,
        roots: tuple[Path, ...],
        *,
        explicit_roots: frozenset[Path],
    ) -> None:
        self.user_roots = roots
        self.explicit_roots = explicit_roots


def test_configure_resource_loader_roots_binds_standard_settings(tmp_path) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    global_base = tmp_path / "global"
    loader = _Loader()

    result = configure_resource_loader_roots(
        resource_loader=loader,
        settings_manager=_SettingsManager(
            _Settings(package_roots=(str(package_root),)),
            global_base,
        ),
        materializer=PackageMaterializer(install_root=tmp_path / "installed"),
        session_id="session-1",
    )

    resource_root = (global_base / "resources").resolve()
    assert result.roots == (str(package_root.resolve()),)
    assert loader.mounts == result.mounts
    assert loader.package_roots == result.roots
    assert resource_root in loader.user_roots
    assert loader.explicit_roots == frozenset({resource_root})


def test_product_selected_plugin_uses_independent_loader_lease(
    tmp_path: Path,
) -> None:
    source = tmp_path / "selected"
    prompt = source / "prompts" / "standard.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("selected prompt", encoding="utf-8")
    (source / "plugin.json").write_text(
        json.dumps({"name": "selected.base"}),
        encoding="utf-8",
    )
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    runtime = PluginResolutionAuthority().publish_runtime(
        (PluginResolutionAuthority().inspect(PluginSource(path=source)),),
        binding_store=materializer,
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    loader = ResourceLoader(user_resource_roots=())

    resolved = configure_resource_loader_roots(
        resource_loader=loader,
        settings_manager=_SettingsManager(_Settings(package_roots=()), tmp_path),
        materializer=materializer,
        selected_plugin_packages=(
            SelectedPluginPackageInput(package=package, binding=binding),
        ),
    )

    [mount] = resolved.mounts
    [catalog_input] = resolved.catalog_plugin_package_inputs
    loader_handle = mount.revision_handle
    assert loader_handle is not None
    assert loader_handle is catalog_input.package.revision_handle
    assert loader_handle is not package.revision_handle
    assert catalog_input.binding is binding
    assert catalog_input.source_root_order == 0
    assert [item.text for item in loader.discover_resources(tmp_path).prompts] == [
        "selected prompt"
    ]
    refreshed = configure_resource_loader_roots(
        resource_loader=loader,
        settings_manager=_SettingsManager(_Settings(package_roots=()), tmp_path),
        materializer=materializer,
        selected_plugin_packages=(
            SelectedPluginPackageInput(package=package, binding=binding),
        ),
    )
    [refreshed_handle] = refreshed.revision_handles
    assert refreshed_handle is not loader_handle
    assert loader_handle.closed is True
    assert package.revision_handle.closed is False
    loader.close()
    assert refreshed_handle.closed is True
    assert package.revision_handle.closed is False
    runtime.close()


def test_product_selected_plugin_rejects_configured_duplicate_without_closing_owner(
    tmp_path: Path,
) -> None:
    source = tmp_path / "selected"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps({"name": "selected.base"}),
        encoding="utf-8",
    )
    materializer = PackageMaterializer(install_root=tmp_path / "installed")
    authority = PluginResolutionAuthority()
    runtime = authority.publish_runtime(
        (authority.inspect(PluginSource(path=source)),),
        binding_store=materializer,
    )
    [package] = runtime.packages
    [binding] = runtime.bindings

    with pytest.raises(
        ValueError,
        match="Product-selected Plugin duplicates a configured Plugin source: selected.base",
    ):
        resolve_package_resource_roots(
            package_roots=(),
            plugin_sources=(str(source),),
            package_sources=(),
            materializer=materializer,
            selected_plugin_packages=(
                SelectedPluginPackageInput(package=package, binding=binding),
            ),
        )

    assert package.revision_handle.closed is False
    runtime.close()


def test_materialized_remote_plugin_disabled_by_manifest_is_not_mounted(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources.packages.roots import (
        resolve_package_resource_roots,
    )

    source = "https://packages.example.invalid/review-pack.git"
    root = tmp_path / "packages" / "review-pack"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "enabled": False}),
        encoding="utf-8",
    )
    materializer = _InstalledMaterializer(source=source, target_path=root)

    resolved = resolve_package_resource_roots(
        package_roots=(),
        plugin_sources=(source,),
        package_sources=(),
        materializer=materializer,  # type: ignore[arg-type]
    )

    assert resolved.roots == ()
    [mount] = resolved.mounts
    assert mount.enabled is False


def test_invalid_materialized_remote_plugin_records_manifest_diagnostic(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources.packages.roots import (
        resolve_package_resource_roots,
    )

    source = "https://packages.example.invalid/review-pack.git"
    root = tmp_path / "packages" / "review-pack"
    root.mkdir(parents=True)
    manifest_path = root / "plugin.json"
    manifest_path.write_text(json.dumps({"name": 7}), encoding="utf-8")
    materializer = _InstalledMaterializer(source=source, target_path=root)
    diagnostics = DiagnosticsService()

    resolved = resolve_package_resource_roots(
        package_roots=(),
        plugin_sources=(source,),
        package_sources=(),
        materializer=materializer,  # type: ignore[arg-type]
        diagnostics_service=diagnostics,
        session_id="session-1",
    )

    assert resolved.roots == ()
    [record] = diagnostics.get_last_diagnostics()
    assert record.code == "invalid_package_manifest"
    assert record.source_path == manifest_path.resolve()
    assert record.details["plugin_source"] == source


def test_invalid_local_plugin_records_same_manifest_diagnostic(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources.packages.roots import (
        resolve_package_resource_roots,
    )

    root = tmp_path / "plugins" / "review-pack"
    root.mkdir(parents=True)
    manifest_path = root / "plugin.json"
    manifest_path.write_text(json.dumps({"name": 7}), encoding="utf-8")
    diagnostics = DiagnosticsService()

    resolved = resolve_package_resource_roots(
        package_roots=(),
        plugin_sources=(str(root),),
        package_sources=(),
        materializer=PackageMaterializer(install_root=tmp_path / "installed"),
        diagnostics_service=diagnostics,
        session_id="session-1",
    )

    assert resolved.roots == ()
    [record] = diagnostics.get_last_diagnostics()
    assert record.code == "invalid_package_manifest"
    assert record.source == "package"
    assert record.source_path == manifest_path.resolve()
    assert record.details["plugin_source"] == str(root)


def test_configured_plugin_mount_uses_leased_content_addressed_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plugins" / "review-pack"
    prompt = root / "prompts" / "review.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("review v1", encoding="utf-8")
    skill = root / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: review\ndescription: Review changes.\n---\n\nReview.",
        encoding="utf-8",
    )
    extension = root / "extensions" / "review.py"
    extension.parent.mkdir()
    extension.write_text("", encoding="utf-8")
    theme = root / "themes" / "dark.json"
    theme.parent.mkdir()
    theme.write_text("{}", encoding="utf-8")
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack"}),
        encoding="utf-8",
    )
    loader = ResourceLoader(user_resource_roots=())
    materializer = PackageMaterializer(install_root=tmp_path / "installed")

    resolved = configure_resource_loader_roots(
        resource_loader=loader,
        settings_manager=_SettingsManager(
            _Settings(package_roots=(), plugin_sources=(str(root),)),
            tmp_path / "global",
        ),
        materializer=materializer,
    )

    [mounted_root] = resolved.roots
    [mount] = resolved.mounts
    assert mount.verified is True
    assert Path(mounted_root).parent.name == "sha256"
    assert len(resolved.revision_handles) == 1
    [catalog_input] = resolved.catalog_plugin_package_inputs
    assert catalog_input.source_root_order == 0
    assert catalog_input.package.revision_handle is mount.revision_handle
    binding = materializer.get_plugin_binding(root)
    assert binding is not None
    assert catalog_input.binding == binding
    assert binding.content_digest == resolved.revision_handles[0].content_digest
    assert binding.revision_kind == "content_sha256"
    prompt.write_text("review v2", encoding="utf-8")
    mounted_files = {
        Path(mounted_root) / "prompts" / "review.md",
        Path(mounted_root) / "skills" / "review" / "SKILL.md",
        Path(mounted_root) / "themes" / "dark.json",
    }
    original_read_text = Path.read_text

    def reject_path_reopen(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if path in mounted_files:
            raise AssertionError("verified Package resources must use the mount reader")
        return original_read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", reject_path_reopen)
    bundle = loader.discover_resources(tmp_path)
    receipt = loader._take_initial_resource_catalog_input_receipt()
    assert receipt.catalog_plugin_package_inputs == (catalog_input,)
    assert [descriptor.text for descriptor in bundle.prompts] == ["review v1"]
    assert bundle.prompts[0].revision_ref is not None
    assert bundle.prompts[0].revision_ref.content_digest == mount.content_digest
    assert bundle.prompts[0].revision_ref.relative_path == "prompts/review.md"
    assert bundle.skills[0].revision_ref is not None
    assert bundle.skills[0].revision_ref.relative_path == "skills/review/SKILL.md"
    assert bundle.extensions[0].revision_ref is not None
    assert bundle.extensions[0].revision_ref.relative_path == "extensions/review.py"
    assert bundle.themes[0].revision_ref is not None
    assert bundle.themes[0].revision_ref.relative_path == "themes/dark.json"
    assert bundle.themes[0].content == "{}"
    handle = resolved.revision_handles[0]
    loader.close()
    assert handle.closed is True
    with pytest.raises(PluginRevisionError) as caught:
        loader.discover_resources(tmp_path)
    assert caught.value.code == "plugin_revision_handle_closed"


def test_resource_loader_rejects_changed_published_plugin_revision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins" / "review-pack"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack"}),
        encoding="utf-8",
    )
    loader = ResourceLoader(user_resource_roots=())
    resolved = configure_resource_loader_roots(
        resource_loader=loader,
        settings_manager=_SettingsManager(
            _Settings(package_roots=(), plugin_sources=(str(root),)),
            tmp_path / "global",
        ),
        materializer=PackageMaterializer(install_root=tmp_path / "installed"),
    )
    manifest = Path(resolved.roots[0]) / "plugin.json"
    manifest.chmod(0o644)
    manifest.write_text(json.dumps({"name": "tampered"}), encoding="utf-8")

    with pytest.raises(PluginRevisionError) as caught:
        loader.discover_resources(tmp_path)

    assert caught.value.code == "plugin_revision_changed"


def test_unsafe_plugin_revision_diagnostic_retains_configured_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins" / "review-pack"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack"}),
        encoding="utf-8",
    )
    (root / "linked.txt").symlink_to(tmp_path / "outside.txt")
    diagnostics = DiagnosticsService()

    with pytest.raises(PluginRevisionError) as caught:
        resolve_package_resource_roots(
            package_roots=(),
            plugin_sources=(str(root),),
            package_sources=(),
            materializer=PackageMaterializer(install_root=tmp_path / "installed"),
            diagnostics_service=diagnostics,
            session_id="session-1",
        )

    assert caught.value.code == "unsafe_plugin_revision_entry"
    [record] = diagnostics.get_last_diagnostics()
    assert record.code == "unsafe_plugin_revision_entry"
    assert record.details["plugin_source"] == str(root)


def test_session_package_install_root_follows_session_layout(tmp_path) -> None:
    assert (
        resolve_session_package_install_root(
            session_dir=tmp_path / "sessions",
            cwd=tmp_path / "project",
        )
        == tmp_path / "packages"
    )
    assert (
        resolve_session_package_install_root(
            session_dir=tmp_path / "custom-session",
            cwd=tmp_path / "project",
        )
        == tmp_path / "custom-session" / "packages"
    )


class _InstalledMaterializer:
    def __init__(self, *, source: str, target_path: Path) -> None:
        self._record = PackageMaterializationRecord(
            source=source,
            name=target_path.name,
            lifecycle="installed",
            target_path=target_path,
        )
        self._revision_store = PluginRevisionStore(
            target_path.parent / ".plugin-revisions"
        )

    def get_record(self, source: str) -> PackageMaterializationRecord | None:
        return self._record if source == self._record.source else None

    def bind_plugin_packages(
        self,
        packages: tuple[PublishedPluginPackage, ...],
    ) -> tuple[PluginSourceBinding, ...]:
        return tuple(
            PluginSourceBinding(
                source=(
                    package.source.url
                    if package.source.kind == "remote"
                    else str(package.source.path)
                )
                or "",
                source_identity=f"{package.source.kind}:{package.manifest.name}",
                source_kind=package.source.kind,
                plugin_id=package.manifest.name,
                manifest_digest=package.manifest_digest,
                content_digest=package.content_digest,
                dependency_lock=package.dependency_lock,
            )
            for package in packages
        )

    def publish_plugin_packages(
        self,
        packages: tuple[ResolvedPluginPackage, ...],
    ) -> tuple[PublishedPluginPackage, ...]:
        return tuple(
            PublishedPluginPackage.from_verified_revision(
                package,
                dependency_lock=lock_plugin_dependency_closure(
                    package_content_digest=package.content_digest,
                    installed_distributions=(),
                ),
            )
            for package in self._revision_store.publish_all(packages)
        )
