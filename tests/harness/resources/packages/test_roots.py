from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
    PackageMaterializer,
    resolve_session_package_install_root,
)
from loushang.harness.resources.packages.roots import configure_resource_loader_roots
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.plugins.types import (
    PluginSourceBinding,
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
        self.package_roots: tuple[str, ...] = ()
        self.user_roots: tuple[Path, ...] = ()
        self.explicit_roots: frozenset[Path] = frozenset()

    def set_package_roots(
        self,
        roots: tuple[str, ...],
        filters: dict[Path, PackageSourceConfig],
    ) -> None:
        assert filters == {}
        self.package_roots = roots

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
    assert loader.package_roots == result.roots
    assert resource_root in loader.user_roots
    assert loader.explicit_roots == frozenset({resource_root})


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


def test_session_package_install_root_follows_session_layout(tmp_path) -> None:
    assert resolve_session_package_install_root(
        session_dir=tmp_path / "sessions",
        cwd=tmp_path / "project",
    ) == tmp_path / "packages"
    assert resolve_session_package_install_root(
        session_dir=tmp_path / "custom-session",
        cwd=tmp_path / "project",
    ) == tmp_path / "custom-session" / "packages"


class _InstalledMaterializer:
    def __init__(self, *, source: str, target_path: Path) -> None:
        self._record = PackageMaterializationRecord(
            source=source,
            name=target_path.name,
            lifecycle="installed",
            target_path=target_path,
        )

    def get_record(self, source: str) -> PackageMaterializationRecord | None:
        return self._record if source == self._record.source else None

    def bind_plugin_packages(
        self,
        packages: tuple[ResolvedPluginPackage, ...],
    ) -> tuple[PluginSourceBinding, ...]:
        del packages
        return ()
